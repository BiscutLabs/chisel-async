# Integrating clocked logic, memory, and events

Connect chisel-async to clocked logic through Chisel's standard `DecoupledIO`
interfaces. Each bridge exposes `clock` and `reset`, so you choose its clock
explicitly. The surrounding asynchronous network remains clockless.

## Decoupled bridges

`DecoupledToFourPhase[T](gen, stages = 2, domain)` accepts on `in.fire`, stores the
payload, and presents a four-phase request. It synchronizes both acknowledgement
phases before accepting another token. Changes to an unaccepted Decoupled input
must not change the stored offer.

`FourPhaseToDecoupled[T](gen, stages = 2, domain)` synchronizes request, captures
the held data bus, and offers it through Decoupled. It raises asynchronous
acknowledgement only after `out.fire`. It then waits for synchronized request
return. Both bridges contain one token slot and require at least two control
synchronizer stages.

The bus itself is held stable; it is not independently synchronized bit by bit.
The digital contract relies on that stability and the declared control latency.
Physical implementation must separately close bus timing, synchronizer placement,
metastability MTBF, and reset recovery/removal.

Inside an `AsyncModule`, create a bridge using `asyncChild`, then assign its clock.
Inside a standard `Module`, instantiate with `Module(new ...)`, wire
`bridge.clock := clock` and `bridge.reset := reset.asAsyncReset`. The runnable
[BridgeHarness](../examples/quickstart/src/test/scala/BridgeSpec.scala) demonstrates
the latter with ordinary `:<>=` connections. It is a simulation harness; strict
async export additionally requires scoped channel/child registration.

Local reset asserts asynchronously and releases synchronously. Hold external
handshake drivers idle during coordinated reset; allow running clocks to finish
local release before sending work. A stopped clock may stall progress indefinitely
and must run again for release. The bridges do not support independently resetting
one endpoint while the other retains protocol state.

## Retained-payload capture receipts

`FourPhaseCaptureReceipt[T]` and `ClickCaptureReceipt[T]` connect a native source
that already holds its payload to a clocked consumer without a second payload
register. Their constructors take `gen`, `stages = 2`, `settlingCycles = 1`,
`maskInvalid = false`, and `domain`. Click uses native request/acknowledgement
parity in both directions; it contains no four-phase converter.

The producer owns the payload. The consumer captures `out.bits` on `out.fire`;
that edge also updates the receipt ACK. A stalled consumer or stopped receipt
clock leaves the offer pending. BD retains its payload through full return to
zero. Click retains its payload through acknowledgement and the physical
post-capture hold interval described below. Neither receipt contains payload
storage. With the defaults, each contains seven control bits: two reset-release
bits, two synchronizer bits, two state bits and one ACK bit.

### Valid and the consumer clock

Only valid-qualified logic may use `out.bits`. With the default direct connection,
the bus may change asynchronously whenever valid is low. A register that loads
it merely because `ready` is high is unsafe. Use `when(receipt.out.fire)` for
consumer capture, not `when(receipt.out.ready)`.

`maskInvalid = true` selects a typed zero while valid is low. It adds combinational
masking, not storage. It can isolate idle bus activity, but does not authorize
invalid-cycle transactions or replace valid qualification. Its propagation and
hold paths must also be qualified.

Run the receipt on the consumer's actual clock. If the receipt instead runs on
the parent clock while the consumer uses a gated subset of those edges, qualify
`out.ready` with the effective clock-gate enable so that every receipt fire has
a real consumer capture edge. Use the gate's retained running/enable state,
stable across that edge, not an unsynchronized request to start the clock.
Unrelated or phase-shifted clocks need another explicit crossing; qualifying
ready is not a general clock-domain converter.

### Synchronization, settling and hold

`stages` must be at least two. `settlingCycles` must be nonnegative. Let E be the
clock edge on which the receiver state machine detects the synchronized pending
request. Valid becomes asserted after E plus `settlingCycles` additional edges;
the earliest acceptance is the following edge. The default one-cycle setting
preserves the MCU receipt sequence. Values zero and one need no additional
counter; larger values add a control counter. These are counts of actual
receipt-clock edges, including any gating, not a time guarantee.

Select these parameters from the worst source-to-consumer data route and the
minimum control-to-capture interval. Synchronizer latency is not a substitute
for synchronizer placement/MTBF analysis or a bundled-data setup check.

The earliest data change after capture must satisfy the consumer's hold time
plus clock-skew and uncertainty allowances. In particular, the minimum ACK
clock-to-Q, ACK route, source release, and returning data-path delay must provide
that interval. Click may release immediately upon seeing ACK: the receipt does
not add a post-ACK hold guard. If masking is enabled, the minimum valid-deassertion
and mask path must satisfy hold too. Increasing settling cycles affects setup,
not these post-capture paths. Qualify both minimum and maximum physical paths.

### Multiple sinks and reset

One receipt ACK represents only its own consumer. When a source feeds a native
store and a receipt, connect the source ACK to a native C-element join of both
sink ACKs. Retain the source data until that aggregate handshake completes. For
BD the join must cover both assertion and return; for Click it joins both phase
polarities. A clocked copy of a native sink's ACK must not be inserted into that
join. This is a bundled-data fork obligation, including its physical distribution
timing, rather than an extra function inside the receipt.

V1 supports POR-owned transport, or a coordinated reset of the entire connected
transport domain. It has **no independent application-reset close/rebase option**.
Do not reset a producer and withdraw its data while this receiver can still
capture. Independently resetting applications require a separately verified
quiescing boundary; the MCU's close/rebase bridges remain separate. Reset aborts
unaccepted transport but cannot undo a consumer effect already committed.

The [receipt test runner](../verification/run_capture_receipts.py) exercises
clock gating, both completion orders of a native multi-sink join, reset, stalls,
and actual RTL fault controls. Digital tests do not qualify physical setup/hold
or reset distribution.

## Memory transactions

`AsyncMemoryPort(MemoryShape(addressBits, dataBits), stages = 2, domain)` connects
four-phase `request`/`response` channels to clocked `backendRequest`/`backendResponse`
Decoupled channels. It supplies transport and a one-outstanding reservation, not
RAM, ROM, an address map, or a bus protocol.

| Payload | Fields |
| --- | --- |
| `MemoryRequest` | `write: Bool`, byte `address`, word `data`, byte `mask` |
| `MemoryResponse` | word `data`, `error: Bool` |

Data width must contain a power-of-two number of bytes; the address has at least
one word-index bit. Mask bit zero enables the least-significant byte. Widths are
not silently resized. Alignment, legal addresses and operation semantics belong
to the backend.

The backend runs on the supplied `clock` and uses `backendReset` for transaction
and response state. Accept a request only on `backendRequest.fire`. Return exactly
one response per accepted request unless reset intervenes, and hold response
valid/data until `backendResponse.fire`. Do not emit unsolicited responses. An
immediate response must remain available until the adapter can accept it.

Input request acknowledgement means **backend acceptance**, not completion of the
response or proof that a write can be undone. The transaction slot stays reserved
through the response's entire four-phase return. A request held high after a
response must not execute twice.

Define storage reset and commit policy separately. Coordinated reset aborts
undelivered transport state; it does not roll back committed writes. If reset
interrupts a response, the requester may not know whether an effect happened.
There is no automatic retry. An exactly-once application protocol across reset
needs additional system-level design.

The [RAM and ROM examples](../examples/src/main/scala/chiselasync/examples/EmitBoundaries.scala)
use `SyncReadMem` and `VecInit`. They demonstrate admission stalls, variable response
latency, byte masks, alignment/bounds errors and preserved storage on protocol
reset. They are examples, not mandatory semantics for your backend. Register a
supported `SyncReadMem` with `contract.synchronousMemory(...)` if using strict
export; [export limitations](timing-and-export.md#compiler-scope) apply.

## Pending events

`PendingEventBridge(width, stages = 2, domain)` samples `levels` on its explicit
clock and emits four-phase bit sets. Each bit is independently synchronized,
rising-edge detected and coalesced while pending. A held-high level produces one
event, not an event every cycle.

Both the high and low phases must span at least **`stages + 1` destination rising
edges**. A stopped clock cannot catch arbitrary short pulses. This component is
not a clockless wake-up cell or an atomic multi-bit CDC transfer.

A snapshot moves pending bits into the output bridge. Events arriving on that
snapshot edge win over clearing and enter the next batch. Further events during
a stalled output also enter the next batch, including another event on an already
offered bit. Acknowledging the old batch never clears newer pending events.

Reset discards both pending and in-flight batches. Hold levels low to establish
idle; a level held high through reset becomes a new event after local release.
Preserving events across an independently reset CPU requires a separate always-on
reset/restart protocol.

The [testing guide](testing.md) describes directed tests for memory commit and event
coalescing; the [example index](examples.md) links their executable campaigns.
