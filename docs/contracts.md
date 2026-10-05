# Initial behavioral contracts

These contracts describe the first functional slice. They do not specify a mapped circuit, physical delay or analog behavior.

## Four-phase channel

The producer drives `req` and `bits`; the consumer drives `ack`. Idle is `(req, ack) = (0, 0)`. The legal transition order is `00 → 10 → 11 → 01 → 00`. One round trip represents one transaction even if its data equals the preceding transaction. The producer establishes data before raising request and holds it through return to idle. The consumer raises acknowledgement only for an offered transaction and lowers it after request falls.

Initial traffic requires coordinated reset, with external request and acknowledgement held low before reset release. On an in-flight reset, assert reset before withdrawing held requests or changing their data, then return the attached domain to idle while reset is asserted. Inputs are binary during normal operation; unknown or malformed handshake behavior is outside the current buffer contract. There is no implicit periodic clock. `FourPhase.connect` requires matching domain objects; exporting a channel requires the owner's explicit domain. Direct Chisel wiring can bypass the helper, so export probes also compare actual primitive/child reset signals with the root reset. A general public protocol-monitor API remains planned.

## One-entry buffer

The functional buffer captures data once when storage is empty and a new request is present. It raises input acknowledgement and presents that captured data with output request. Input acknowledgement falls after the source lowers request, independently of how long the output stalls.

Storage remains occupied through the complete output handshake. After output acknowledgement rises, output request falls; stored data remains unchanged until output acknowledgement falls. A new input request may wait while occupied; it is not acknowledged until storage becomes available. The same still-asserted request cannot be captured twice. This makes buffers composable under backpressure.

Reset dominates: clear handshake outputs and stored data, discard the outstanding token, and require the entire attached channel domain to restart at idle. Accepted but undelivered tokens are explicitly aborted. The buffer has no committed memory or I/O effects. Independent endpoint resets are unsupported and require a future restart bridge.

For verification accounting, input acknowledgement rising accepts a token and output acknowledgement rising delivers it. A delivered token still reserves storage until output acknowledgement falls. Reset aborts only tokens not yet delivered; an interrupted return-to-idle phase does not retrospectively undo delivery. Every settled checkpoint satisfies `accepted = delivered + outstanding + aborted`. An offered input waiting for acceptance is not an accepted token.

The SV view updates data and request in the same zero-delay scheduling interval; sample offered payloads after settling. Passive control listeners remain armed on value changes. The data-hold observer allows initial settling at the request timestamp, then checks subsequent changes throughout the handshake. It is not a gate-level delta-glitch or setup/hold checker. No setup/hold guarantee follows. This is a functional storage primitive used to establish interfaces and a reference corpus before structural controller implementation.

## C-element

The two-input element starts only after explicit reset. Reset forces output zero regardless of inputs. After release, `(0,0)` forces zero, `(1,1)` forces one, and disagreement retains the previous output. No implicit initialization is assumed.

The four-state diagnostic model retains a known output with an unknown input only when both possible binary resolutions yield that same output. Otherwise output becomes unknown until a determinate transition or reset. This is digital uncertainty, not analog metastability modeling.

The independent Boolean oracle uses the characteristic equation `next = (a & b) | (previous & (a | b))`. Its test enumerates all four-transition input sequences from reset. Tests also check release under unanimous ones and reset recovery from uncertainty.

## Versioning

SV model identifiers end in `_v1`. Their behavior is part of the contract, not an incidental module name. Incompatible changes require a new model identifier and updated compatibility evidence. The Scala library remains `0.1.0-SNAPSHOT` and has no stable API promise yet. The separate `chisel-async-contract-v1` sidecar carries scoped instance IDs and checked endpoint mappings. [Timing and export](timing-and-export.md) specifies the latch/delay models, qualified compiler configuration, schema and limits.
