# Arbitration, two-phase channels and mixed encoding (CA-07)

CA-07 adds typed two-phase bundled channels, a two-client handshake arbiter, two/four-phase conversion, and the minimal bundled/dual-rail converter pair brought forward from CA-08. These are explicit-reset digital models with declared timing assumptions. Implementation proceeds at the user's direction while **L1 independent review and held-out acceptance remain open**. The development campaign does not close that gate.

## Public API and capacity

`new Channel(gen, resetDomain).twoPhase` returns `TwoPhase[T]`: the producer drives `req` and `bits`, and the receiver drives `ack`. Either request transition offers a token; acknowledgement matching the new request completes it. Payload is stable before request changes and through completion. Equal successive payloads still represent distinct tokens. Coordinated reset restores parity `00` and cancels undelivered work. `TwoPhase.connect` rejects mismatched payload shapes and reset domains; use `asyncChild` to inherit a parent's domain.

| API | Contract |
| --- | --- |
| `FourPhaseArbiter[T]` | Two persistent, independently requesting inputs; one buffered output. A MUTEX and cross-acknowledgement interlocks feed an exclusive merge. Complete input handshakes remain exclusive through return. |
| `TwoPhaseStage[A,B]`, `TwoPhaseBuffer[T]` | One long-hold data slot with explicit phase adapters. Type-changing transforms retain the exact output shape checks. |
| `TwoPhaseFifo[T]` | Exactly the requested number of data slots, with optional typed initial literals installed after each reset. Phase state does not add payload capacity. |
| `TwoPhaseInitialTokens[T]` | Emits its literal sequence once per reset epoch; `done` follows full internal return. |
| `TwoPhaseFork[T]` | Unbuffered all-consumer broadcast. Each branch has its own request parity. |
| `TwoPhaseJoin[A,B]` | One buffered operand per input; pairs operands in per-input order. |
| `TwoPhaseSelect[T]` | Captures `Selected[T]` in one data slot. Each destination has independent parity, including when other destinations receive intervening tokens. |
| `TwoPhaseMerge[T]` | One data slot; callers serialize complete handshakes, including each input's acknowledgement transition. It is not an arbiter. |
| `TwoPhaseArbiter[T]` | Two independently requesting inputs, normalized into `FourPhaseArbiter`; one output data slot. |
| `TwoPhaseToFourPhase[T]`, `FourPhaseToTwoPhase[T]` | One data slot each, with explicit sequential control conversion. |
| `FourPhaseToDualRail[T]`, `DualRailToFourPhase[T]` | One data slot each. Stateful completion distinguishes all-valid and all-spacer; binary data remains held throughout the internal four-phase return. |

Constructor examples, including different payload types, initialization, 65-bit transport, and both converter round trips, are executable in [EmitPhase.scala](../examples/src/main/scala/chiselasync/examples/EmitPhase.scala). All storage retains the existing long-hold stage's timing and reset assumptions.

## Arbiter provenance and service policy

The two-client control topology follows Sparsø and Furber, *Asynchronous Circuit Design: A Tutorial*, §5.8.1–5.8.2, Figure 5.21 ([university-hosted draft](https://www.inf.pucrs.br/~calazans/graduate/SSD/Bibliography/Sparso-Furber-Short.pdf)). A MUTEX grant is gated by the other lane's acknowledgement being low before entering the exclusive merge. Mutual exclusion of grants alone does not serialize complete four-phase handshakes; the return interlocks are essential. The implementation is independently written and adds this library's buffered merge.

`MutexPolicy.PreferFirst`, `PreferSecond`, and `Alternate` specify **finite digital collision choices**. A granted requester retains service until it withdraws its request. Handover passes through zero grants. Fixed preference can starve a contender; alternating tie choice is only a model policy, not a general physical fairness theorem. The external ledger permits either legal collision winner while checking each input's order and conservation. Separate primitive tests check each declared policy, retained winners, handover and reset.

`RESOLVE_FS` models positive inertial propagation and is retained in the ExtModule parameters. A physical MUTEX can remain metastable for an unbounded time. This view neither implements an analog metastability filter nor supplies a physical resolution-time bound, mapped circuit or manufacturable arbiter. Persistent requests, eventual downstream service, binary operation after quiescent reset and ideal wires are assumptions of the finite experiment.

## Sequential phase conversion and timing

Two-phase components explicitly normalize their boundaries around the four-phase long-hold catalog. Their internal return phase costs latency and throughput. They are not a MOUSETRAP implementation, and no native two-phase throughput advantage is claimed.

The sequential convention is grounded in the [ASYNC 2000 handshake tutorial, Task 2](https://www.staff.ncl.ac.uk/alex.yakovlev/home.formal/talks/async2k/ASYNC00handson-frame.html): every input transition corresponds to one complete four-phase transaction. The adapters are independently composed primitive circuits, not a transcription of the tutorial's synthesized netlist or of a quick-return converter.

For two-to-four conversion, an atomic XOR compares request parity with a master phase latch. Downstream acknowledgement admits the new master phase; a second latch passes it back only after acknowledgement returns. A delayed input acknowledgement keeps the next input token behind closure of the master latch. The inverter's reset value is one, so reset release cannot accidentally capture the initial offer through a transparent master.

For four-to-two conversion, a resettable toggle element advances output request on each input request rise. An acknowledgement-history latch closes on that request; an atomic XOR produces input acknowledgement after the receiver changes parity. The order is `req4+ → req2 edge → ack2 edge → ack4+ → req4− → ack4−`. The toggle input is a handshake event, not a periodic clock.

`PhaseTiming(cells, returnDelay)` declares independent min/max/model propagation for every adapter cell. Cell minima are positive; `returnDelay > cells.max`. Ideal request forks and zero latch aperture ensure the history latch closes before the completion path returns. The examples use 1–10 ns cell bounds, 1 ns nominal values and a 40 ns return guard. These model inequalities do not replace physical aperture, fork-skew or pulse-width analysis.

The dual-rail encoder generates each rail from stored binary data and the held output request. The decoder uses per-bit presence plus a stateful N-input C-element, a binary holding latch, and long-hold storage. Its request admission delay equals `timing.matchedDelay`; it must exceed the maximum decoder-latch plus storage-data propagation. The storage retains its own matching delay. Both acknowledgement edges are delayed by `phase.returnDelay`, so the binary latch reopens before a new rail word can follow acknowledgement return. Partial spacer waves cannot clear stateful completion. Only coordinated reset is supported.

The v3 export adds `phase-conversion-v1` and `encoding-boundary-v1` obligations. Passive marker kinds 5/6/7 bind their actual endpoints and carry cell bounds and guards. KIND 7's `MATCHED_FS` applies to decoder admission and the storage request guard; `OUTPUT_FS` is the acknowledgement guard. The checker verifies direction, endpoint identities, child storage budgets and actual primitive parameters. These markers must be consumed or preserved before synthesis removes them. They are not an STA implementation.

## Verification and claim limits

The required development sweep has **18 fixtures × 303 configurations = 5,454 positive cases**: nominal, uniform 1 ns, uniform 10 ns, and 300 sampled independent per-cell assignments per fixture. Adapter and storage overrides are checked against their declared bounds. Additional routing cells and MUTEX resolution undergo a recorded 1–10 ns sensitivity experiment; their API parameters remain nominal values, not unrecorded worst-case bounds. Request, output, decoder-admission and return guards stay fixed. Seeds select all three finite MUTEX policies. This is a bounded regression sample, not a reliability estimate.

An external Python oracle reads settled, exact-femtosecond traces from public **and internal channel boundaries**. It has no controller latch equations or production state names. Input offers create delivery obligations; input completions are counted separately, because a converter or fork can deliver before completing its upstream handshake. Reset cancels only undelivered obligations. Hand-derived tests validate protocol order, parity, payload hold, legal arbitration choices and rail transitions.

Each positive case requires observed completions at every public and internal channel; missing boundary traces cannot pass. Multi-output consumers use different stall schedules. Each case runs traffic, blocked-capacity reset and successful restart over three reset epochs. Odd seeds first advance parity before the blocked reset; both acknowledgement polarities must deliver. Payloads include repeated values and walking bits, with 135-token streams for the 65-bit fixture. Three-bit dual-rail fixtures exercise all eight values and all 36 arrival/return permutation pairs, followed by repeated data. Round trips exercise actual mixed-encoding composition. Capacity checks count completed source transfers while the sink is blocked.

Twelve paired controls mutate real DUT source or parameters: early acknowledgement, level-for-toggle request, wrong reset parity, shortened phase return guard, overlapping grants, removed arbiter return interlock, request-only merge selection, wrong selected destination, overlapping rails, stateless completion, leaked decoded data, and early decoded request. Each baseline must deliver real traffic. Its mutant must trigger the exact declared protocol/data diagnostic; crashes, compilation failures and progress timeouts cannot pass a control. The consumer repeats all 18 fixtures at nominal and both uniform corners (54 cases) plus every control using independently emitted RTL from the published local JAR.

Development found two defects that outer token counts alone had missed. The existing exclusive merge released its mux selection on request fall while internal acknowledgement was still high; selection now persists while either is high, and its glue budget includes both controls. The decoder could assert request before its binary latch output settled; the explicit admission guard repairs that boundary. Both have permanent internal-boundary negative controls.

Run the complete suite with `python tools/qualify.py`. For focused replay after emission, run `python verification/run_phase.py`; `--fixtures encoding_from_dual --seeds 0 1 2` selects a development subset and the fixture's paired controls. Reports retain selected cases, every realized override, source/checker hashes, compile commands, raw traces and diagnostic-specific fault results under `target/verification/phase`. [Qualification status](qualification.md) records executed results. Empty selections and stale reports cannot supply success.

Physical QDI indication/fork closure, analog arbitration, independent reset domains, native two-phase performance, arbitrary compiler transformations, macOS and the full CA-08 catalog remain outside these results. Independent async review and a newly frozen held-out campaign are still required for acceptance.
