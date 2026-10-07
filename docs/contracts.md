# Protocol contracts

These are obligations for drivers, consumers and tests. For constructors and
composition patterns see the [catalog](components.md); for propagation assumptions
see [timing and export](timing-and-export.md).

## Four-phase bundled data

The producer drives `req` and `bits`; the consumer drives `ack`.

| State `(req, ack)` | Meaning | Next normal transition |
| --- | --- | --- |
| `00` | Idle | Producer establishes data, raises `req` |
| `10` | Offered | Consumer raises `ack`: delivery at this boundary |
| `11` | Acknowledged | Producer lowers `req` |
| `01` | Returning | Consumer lowers `ack` |

Keep data stable from before request rises through the complete return to `00`.
Each complete handshake carries one token even when payload bits repeat. A
consumer must not acknowledge without an offer; a producer must not issue a new
request during return. In digital tests, initial same-timestamp settling is
allowed by the relevant observer; that is not a physical setup-time guarantee.

`LongHoldBuffer` and `FourPhaseStage` reserve one slot through output `ack` falling.
They may acknowledge input return while the output remains stalled. A still-high
old request cannot be accepted twice. Idle latch data can track inputs and has no
validity until offered. `FourPhaseBuffer` implements a separate zero-delay
behavioral storage contract.

## Two-phase bundled data

Either request edge offers a token. The consumer acknowledges by matching request
parity; both acknowledgement polarities count as deliveries.

| `(req, ack)` | Meaning | Next edge |
| --- | --- | --- |
| `00` | Idle | `req` rises |
| `10` | Pending | `ack` rises |
| `11` | Idle | `req` falls |
| `01` | Pending | `ack` falls |

Data is established before the request edge and held until completion. Coordinated
reset restores `00`. The settled trace observer completes using the payload saved
at request time; a causal idle data update in the completion sample does not
change the delivered token. Changes while pending fail. This convention cannot
detect arbitrary delta-cycle glitches.

## Return-to-zero dual rail

For each bit, the pair **`(zero, one)`** is `00` for spacer, `10` for logical zero,
and `01` for logical one. `11` is illegal. Typed rails preserve the payload's
structure; arithmetic on the rails themselves is not ordinary binary arithmetic.

Rails rise monotonically from spacer to a valid word. The consumer acknowledges
completion; the producer returns monotonically to spacer; the consumer lowers
acknowledgement only after complete spacer return. Word completion is stateful:
an AND over instantaneous bit-presence signals is not a substitute for a
C-element completion tree during partial return.

Strongly indicating components wait for all input data before any output data,
and all input spacer before output spacer. A strong half-buffer also waits for
downstream acknowledgement before withdrawing output data. It can deliver before
upstream acceptance is observed; reset accounting must preserve that delivery.

`DualRailBuffer` is the earlier, weaker Muller half-buffer probe. Its rails can
appear before the whole input word is valid. Use `DualRailStrongBuffer` when the
surrounding design requires word-level strong indication.

## Decoupled and clocked bridges

Standard Chisel `Decoupled` commits on rising-edge `valid && ready`.
`DecoupledToFourPhase` captures only on that event, then holds its async offer
through both acknowledgement phases. `FourPhaseToDecoupled` synchronizes request,
captures the held bus, and acknowledges the async producer only after the clocked
consumer commits. Synchronizer depth is at least two.

The memory backend must hold response valid/data until fire and produce one
response per accepted request unless coordinated reset intervenes. See
[memory integration](clocked-integration.md#memory-transactions) for commit and
reset responsibilities.

## Reset and composition

Reset aborts pending transport state and restores idle; it does not reverse
delivered fork branches or committed backend effects. Drivers must assert reset
before releasing held signals and restart the entire connected domain together.
Clocked local release requires running clocks. Initial-token sources reinstall
their declared literal sequence once per reset epoch.

Fork acknowledgement waits for every branch in both phases. Join pairs the nth
left token with the nth right token. Select captures routing choice with data.
Exclusive merges require complete input handshakes to be serialized, including
return. Use an arbiter for independent competitors; a merge is not an arbiter.

## Model and schema versions

Packaged behavioral cells have versioned identifiers such as `_v1`. Incompatible
cell behavior requires a new model identifier and new evidence. The strict export
uses contract v3 and port ABI v2. Re-emit older exports when the validator requires
new obligations; editing a version string cannot migrate evidence. The
[compatibility policy](compatibility.md#versioning) governs library releases.
