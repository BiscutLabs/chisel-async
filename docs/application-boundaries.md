# CA-09: clocked memory and event boundaries

CA-09 adds thin adapters over standard Chisel storage and the existing explicit-clock bridges. `AsyncMemoryPort` connects four-phase memory transactions to a clocked `Decoupled` backend. `PendingEventBridge` captures synchronized rising events into coalesced bit sets. Complete GPIO peripherals, address maps, interrupt policy and independent CPU/always-on reset belong to MCU integration.

These are digital, coordinated-reset contracts. Physical CDC placement, metastability MTBF, recovery/removal and held-bus timing closure remain separate. The [bridge assumptions](logical-channels.md) still apply. All clocks are explicit.

## Memory port

Inside an `AsyncModule`, register the child and inherit its coordinated reset:

```scala
val port = asyncChild("memory")(d => new AsyncMemoryPort(
  MemoryShape(addressBits = 24, dataBits = 32), stages = 2, domain = d))
port.clock := memoryClock
// request / response: four-phase channels
// backendRequest / backendResponse: ordinary Decoupled channels
// Use backendReset for the clocked backend's transaction state.
```

`MemoryRequest` contains `write`, a byte `address`, `data`, and a byte `mask`. Mask bit zero enables the least-significant byte. Word size must be a power-of-two number of bytes; address width must contain at least one word-index bit. `MemoryResponse` contains `data` and `error`. Both encodings retain those types and widths. Storage, bounds, alignment and operation semantics belong to the backend; the adapter does not build another RAM or resize addresses.

The backend must run on `clock`, use `backendReset` for transaction/response state, accept requests only on rising-edge `backendRequest.fire`, and return exactly one response per accepted request unless coordinated reset intervenes. Hold response valid/data until `backendResponse.fire`; never emit unsolicited responses. A response available in the request cycle must remain available until accepted. Storage reset and write-commit policy must be separately defined.

Input acknowledgement means **backend acceptance**, not response delivery. One backend transaction remains reserved until the response completes both acknowledgement phases. A next input may be sampled while waiting, but is not acknowledged or sent to the backend until that reservation is released. Keeping an old request high through response completion cannot execute it again.

Reset aborts undelivered transport state. A previously committed write remains committed under a backend policy that preserves memory. An interrupted requester may not know whether its write happened; a missing response does not imply rollback. The adapter performs no automatic retry. Independent endpoint reset/restart is unsupported. Domain-aware helpers reject distinct domain objects, and export checks actual child reset wiring; neither is a runtime detector for arbitrary reset misuse.

## Standard Chisel examples

[`EmitBoundaries.scala`](../examples/src/main/scala/chiselasync/examples/EmitBoundaries.scala) supplies two reference backends: 16 aligned, little-endian, 16-bit words with six-bit byte addresses. `accept` introduces admission stalls; `latency` selects 0–15 backend wait cycles. The adapter itself imposes no fixed response deadline.

| Operation | RAM (`SyncReadMem`) | ROM (`VecInit`) |
| --- | --- | --- |
| Aligned read, address 0–30 | Return word | Return word |
| Aligned write | Apply enabled bytes once at backend fire; return zero | Error, no effect |
| Zero-mask aligned write | Successful no-op, return zero | Error, no effect |
| Odd or out-of-range address | Error, no access | Error, no access |
| Error response data | Zero | Zero |
| Initial contents | Unspecified; tests initialize every byte before reading | Word `i = (i * 0x1235 + 0x5a3c) mod 65536` |
| Coordinated reset | Abort response state; preserve contents | Abort response state; preserve image |

The campaign records SHA-256 of the ROM's 32 bytes in increasing address order. Reads and writes are serialized, avoiding collisions. The RAM captures its enabled synchronous read result into response storage; it never assumes a disabled memory output remains held. This follows [Chisel's documented memory behavior](https://www.chisel-lang.org/docs/explanations/memories). Standard clocks/resets are described in [Chisel's multiple-clock guide](https://www.chisel-lang.org/docs/explanations/multi-clock); crossing logic remains this library's responsibility.

`contract.synchronousMemory(id, memory, wordBits, maskBits)` registers standard `SyncReadMem` storage. Its optional v3 `memories` record identifies depth, mask width, one-cycle read/write latency, unspecified initial contents, preserved contents on reset and undefined read-under-write. Qualification supports the pinned compiler's one inferred masked read/write port; other lowerings fail closed. The resolver checks the Chisel target against `seq.firmem` IR, emitted array dimensions and actual pin ABI. Unregistered modules still fail. This is inventory/shape checking, not arbitrary memory equivalence. Behavioral tests separately check masks, contents and reset persistence.

Nested ready/valid gates need simultaneous stored controls for observation mapping. The resolver first uses existing walking patterns, then adds paired independent source patterns only if an endpoint remains inactive. All comparisons and activity requirements remain enabled. Neither pass forces derived channel endpoints. No observation hardware ports are added.

## Pending events

`PendingEventBridge(width, stages = 2, domain)` has explicit `clock`/`reset`, input `levels`, and four-phase `out`. Each level bit is independently synchronized and rising-edge detected. **Both high and low must span at least `stages + 1` destination rising edges** to qualify for capture. A stopped clock does not capture short pulses. This is not a clockless always-on wake-up cell.

Each bit coalesces repeated events while pending. Taking a snapshot transfers the old set into the output bridge and clears only that pending bank. A rise on the snapshot edge wins over clear and enters the next batch. Events during a stalled output also enter that next batch, including another event on an already offered bit. Acknowledging the old batch never clears newer events. A continuously high input produces one rising event.

Bits are independent events; batch grouping follows their sampled arrival times. This interface does not promise an atomic multi-bit crossing of `levels`.

Reset discards both banks. Hold inputs low to establish idle; a level held high through reset is observed as a new event after local release. Both cases are tested. Preserving interrupts across CPU-only reset needs a separate always-on reset/restart protocol outside this adapter's contract.

## Verification

`python tools/qualify.py` emits/checks four additional optimized exports, runs this campaign and expanded ChiselSim suite, and repeats boundary tests against a clean published JAR. Focused replay:

```text
python tools/sbt.py "examples/runMain chiselasync.examples.EmitBoundaries target/generated"
python verification/run_boundaries.py --output target/my-new-boundary-run
```

The existing `bridge_roundtrip` export from `EmitArchitecture` is also required. Output directories must be new; each attempt retains source, metadata, IR, benches, traces and logs. `--quick` reduces phase points but retains every fault control.

The campaign has **80 positive cases and five actual-RTL controls**. Twenty clock/phase points each exercise RAM, ROM and event bridges; twenty more exercise the existing two-clock round trip at slow/fast, fast/slow, equal and unequal periods. Each memory case checks 164 accepted requests, 162 responses, two response aborts and seven resets: every byte mask, alignment/bounds errors, held requests, response stalls/delayed return, committed-write reset and stopped-clock release. An independent byte-array oracle reconstructs responses/effects from raw logs; a write witness observes the generated RAM port.

Each event case delivers 24 batches with 25 snapshots and three resets. Tests cover set coincident with snapshot, a new event coincident with acknowledgement, coalescing, held levels, stalls, reset of both banks and a level held high across reset. Controls corrupt response data, swap masks, repeat writes on held requests, make clear beat set, and clear newer events on acknowledgement. Missing-event controls require a specific bounded protocol diagnostic; the global watchdog, compiler errors or crashes cannot substitute for it.

ScalaTest/ChiselSim adds 32 memory transactions and 31 event deliveries in both source and published-consumer tests. Adversarial Python tests reject mismatched declarations/IR/arrays/pins, schema-invalid inventories and broken traces. Review/full-platform results are in [qualification](qualification.md). Historical L0/L1 acceptance remains scoped to its frozen revisions.
