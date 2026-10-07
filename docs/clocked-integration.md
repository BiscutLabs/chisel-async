# Integrating clocked logic, memory, and events

The library uses normal Chisel `DecoupledIO`, clocks and storage at clocked
boundaries. Each bridge exposes `clock` and `reset`; no clock is inferred for the
surrounding asynchronous network.

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
