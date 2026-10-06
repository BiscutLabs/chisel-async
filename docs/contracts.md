# Initial behavioral contracts

These contracts describe the first functional slice. They do not specify a mapped circuit, physical delay or analog behavior.

## Logical token stream

`Channel[T]` separates payload/reset intent from its electrical binding. Bundled, dual-rail RTZ and Decoupled have distinct transfer, hold and commit semantics; see [logical-channel contracts](logical-channels.md). Clocked conversion uses explicit storage and synchronized control; it does not turn a clock into an implicit library assumption.

## Four-phase channel

The producer drives `req` and `bits`; the consumer drives `ack`. Idle is `(req, ack) = (0, 0)`. The legal transition order is `00 â†’ 10 â†’ 11 â†’ 01 â†’ 00`. One round trip represents one transaction even if its data equals the preceding transaction. The producer establishes data before raising request and holds it through return to idle. The consumer raises acknowledgement only for an offered transaction and lowers it after request falls.

Initial traffic requires coordinated reset, with external request and acknowledgement held low before reset release. On an in-flight reset, assert reset before withdrawing held requests or changing their data, then return the attached domain to idle while reset is asserted. Inputs are binary during normal operation; unknown or malformed handshake behavior is outside the current buffer contract. There is no implicit periodic clock. `FourPhase.connect` requires matching domain objects; exporting a channel requires the owner's explicit domain. Direct Chisel wiring can bypass the helper, so export probes also compare actual primitive/child reset signals with the root reset. A general public protocol-monitor API remains planned.

## Two-phase baseline (specification only)

Two-phase bundled data encodes a token by a request transition and its completion by an acknowledgement transition. The following parity table follows the transition-signalling convention in SparsÃ¸, [Introduction to Asynchronous Circuit Design](https://orbit.dtu.dk/en/publications/introduction-to-asynchronous-circuit-design/), Â§2.1. Our baseline chooses coordinated reset to `00` and data held from before request changes until acknowledgement matches request.

| req, ack | Meaning | Next legal edge |
| --- | --- | --- |
| 00 | Idle | req rises |
| 10 | Pending token | ack rises; token delivered |
| 11 | Idle | req falls |
| 01 | Pending token | ack falls; token delivered |

Both acknowledgement polarities deliver tokens, even for repeated payloads. Reset restores `00`, aborts pending work and preserves prior delivery accounting. `TwoPhaseContract` tests all four states, illegal edges, both completion polarities and reset. This establishes CA-02's reference convention; production two-phase hardware and converters remain CA-07 work.

## Observation traces

The packaged [v1 observation schema](../src/main/resources/chiselasync/trace-v1.schema.json) and [trace format](trace-format.md) define the existing functional/timing JSONL envelope. Readers validate femtosecond ordering, units and activity independently of test completion status. Broader component-specific trace vocabularies accompany later catalog additions.

## One-entry buffer

The functional buffer captures data once when storage is empty and a new request is present. It raises input acknowledgement and presents that captured data with output request. Input acknowledgement falls after the source lowers request, independently of how long the output stalls.

Storage remains occupied through the complete output handshake. After output acknowledgement rises, output request falls; stored data remains unchanged until output acknowledgement falls. A new input request may wait while occupied; it is not acknowledged until storage becomes available. The same still-asserted request cannot be captured twice. This makes buffers composable under backpressure.

Reset dominates: clear handshake outputs and stored data, discard the outstanding token, and require the entire attached channel domain to restart at idle. Accepted but undelivered tokens are explicitly aborted. The buffer has no committed memory or I/O effects. Independent endpoint resets are unsupported and require a future restart bridge.

For verification accounting, input acknowledgement rising accepts a token and output acknowledgement rising delivers it. A delivered token still reserves storage until output acknowledgement falls. Reset aborts only tokens not yet delivered; an interrupted return-to-idle phase does not retrospectively undo delivery. Every settled checkpoint satisfies `accepted = delivered + outstanding + aborted`. An offered input waiting for acceptance is not an accepted token.

The SV view updates data and request in the same zero-delay scheduling interval; sample offered payloads after settling. Passive control listeners remain armed on value changes. The data-hold observer allows initial settling at the request timestamp, then checks subsequent changes throughout the handshake. It is not a gate-level delta-glitch or setup/hold checker. No setup/hold guarantee follows. This is a functional storage primitive used to establish interfaces and a reference corpus before structural controller implementation.

## Published long-hold stage

`FourPhaseStage[A, B](inGen, outGen, transform, timing, domain)` checks the transformed payload against the distinct output type. `LongHoldBuffer[T]` is the identity specialization. Both use the Furberâ€“Day long-hold topology with explicit primitive boundaries and require a timing policy: named `FunctionalOnly` or validated `Digital`. [Controller documentation](long-hold-controller.md) specifies the source, added timing guards, atomic input polarity, reset and ideal-wire assumptions, and independent evidence.

These stages use the same accepted/delivered/reserved accounting and full-handshake hold contract above. Their latch may transparently track data while idle; output data has no validity then. Reset takes the declared propagation time and must be held until quiescent. The new policy does not claim physical setup/hold closure. The historical behavioral buffer remains a separate reference model.

## Four-phase composition

The [CA-06 composition contracts](four-phase-composition.md) extend the long-hold foundation with exact-depth FIFO and initial tokens, unbuffered all-consumer fork, independently buffered typed join, captured select and monitored exclusive merge. Their transfer accounting differs where necessary: fork branch delivery can precede producer acknowledgement, and reset never retracts a delivered branch. Initial tokens occupy declared FIFO capacity and are reinstalled once per reset epoch. Exclusive merge serializes complete input handshakes, including return; it supplies no arbitration.

## Withdrawn structural stage (regression only)


The former single-type custom `FourPhaseStage[T]` and `StructuralFourPhaseBuffer[T]` are withdrawn. They survive as `experimental.UnsafeFourPhaseStage` and `UnsafeFourPhaseBuffer` to retain the historical zero-delay corpus and a reproducible internal delay race. The new two-type `bundled.FourPhaseStage[A, B]` is a different published controller, with a required timing argument. Do not compose new library components from the withdrawn classes. [Review response](review-response.md) records the counterexample and replacement criteria.

The control specification is independent of the implementation equations:

| Condition | Required action |
| --- | --- |
| Empty, input acknowledgement low, request high, output acknowledgement low | Capture the transformed payload, acknowledge input, reserve storage and offer output. |
| Input request falls | Lower input acknowledgement, even while output is stalled. |
| Offered output is acknowledged | Withdraw output request; retain payload and reservation. |
| Output acknowledgement falls after delivery | Release reservation; a pending new input may then be accepted. |
| Original input request remains high after output completes | Retain input acknowledgement; do not accept that request again. |
| Coordinated reset | Clear every latch and handshake output; abort undelivered tokens. |

The intended control specification above remains useful, but the custom latch equations do not implement it robustly under internal delays. In the directed counterexample, returning clears before occupied's enable closes, causing a duplicate output offer. Capture enables closing through zero-delay feedback were a design defect, not merely a future pulse-width qualification task. A replacement must establish its controller assumptions and topology before catalog expansion. The independent `TimedCapture` tests do not establish these properties for any handshake controller.

This is our functional decomposition, not a reproduction of a published controller. For the distinction between handshake correctness and physical bundled-data delay matching, see SparsÃ¸, [Introduction to Asynchronous Circuit Design](https://backend.orbit.dtu.dk/ws/portalfiles/portal/215895041/JSPA_async_book_2020_PDF.pdf), Â§2.4.1 and chapter 10. The existing transaction ledger, bounded event orders and reset prefixes remain the external oracle; they do not duplicate latch equations.

## C-element

The two-input element starts only after explicit reset. Reset forces output zero regardless of inputs. After release, `(0,0)` forces zero, `(1,1)` forces one, and disagreement retains the previous output. No implicit initialization is assumed.

The four-state diagnostic model retains a known output with an unknown input only when both possible binary resolutions yield that same output. Otherwise output becomes unknown until a determinate transition or reset. This is digital uncertainty, not analog metastability modeling.

The independent Boolean oracle uses the characteristic equation `next = (a & b) | (previous & (a | b))`. Its test enumerates all four-transition input sequences from reset. Tests also check release under unanimous ones and reset recovery from uncertainty.

## Versioning

SV model identifiers end in `_v1`. Their behavior is part of the contract, not an incidental module name. Incompatible changes require a new model identifier and updated compatibility evidence. The Scala library remains `0.1.0-SNAPSHOT` and has no stable API promise yet. The separate `chisel-async-contract-v3` sidecar carries scoped instance IDs, compiler probe identities and checked endpoint mappings. Re-emit v1/v2 exports for the current resolver. [Timing and export](timing-and-export.md) specifies the latch/delay models, qualified compiler configurations, schema and limits.
