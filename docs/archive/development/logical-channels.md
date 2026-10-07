# Logical channels and first encoding probes

> Historical development record. For current usage, read the [user documentation](../../index.md).

`Channel[T]` describes a sized payload, a coordinated reset domain and an ordered token stream. It creates no wires or storage until an encoding is selected. Its `bundled`, `twoPhase`, `dualRail` and `decoupled` factories return distinct electrical interfaces. This keeps payload validation and token intent common without inventing a handshake that could represent all four encodings.

```scala
val flow = new Channel(new Packet, resetDomain)
val bundled = IO(flow.bundled)     // FourPhase[Packet]
val transition = IO(flow.twoPhase) // TwoPhase[Packet]
val dual = IO(flow.dualRail)       // DualRail[Packet]
val clocked = IO(flow.decoupled)   // standard Chisel DecoupledIO[Packet]
```

Each interface needs its own driver. These declarations do not connect or convert them. `requireCompatible` checks payload shape and reset identity; it does not authorize electrical wiring between different encodings or clocks. `FourPhase.connect`, `TwoPhase.connect` and `DualRail.connect` check their concrete encodings. Raw Chisel connections can bypass library checks. Decoupled uses the standard Chisel interface, with an explicit clock endpoint in the exported contract. No implicit clock or automatic CDC conversion is introduced.

The existing long-hold stage now constructs its distinct input/output ports from logical channels. Explicit `DecoupledToFourPhase` and `FourPhaseToDecoupled` modules demonstrate conversion, including the storage and control state that conversion requires. The [round-trip example](../../../examples/src/main/scala/chiselasync/examples/EmitArchitecture.scala) composes both with a long-hold stage and separate source/sink clocks. CA-06 adds four-phase composition; [CA-07](arbitration-and-two-phase.md) adds two-phase counterparts, arbitration and explicit two/four-phase and bundled/dual-rail converter pairs. Each conversion has storage, phase state and timing obligations.

## Shared intent, different transfer rules

The common contract is ordered delivery without duplication or loss during normal operation; coordinated reset discards undelivered work. An implementation defines its storage capacity and commit point. A valid input that has not been accepted is not automatically an owned token. Reset does not undo an already committed delivery.

| Encoding | Transfer / retention rule | Idle and reset |
| --- | --- | --- |
| Four-phase bundled | Request, acknowledge, request return, acknowledge return; data held through the complete cycle | Request and acknowledge low; reset aborts outstanding work |
| Two-phase bundled | Either request edge offers; acknowledgement matching request completes; data held through completion | Equal parity is idle; coordinated reset restores 00 |
| Dual-rail RTZ | Each bit is one of two asserted rails; rails rise monotonically to a complete word, acknowledgement rises, rails return monotonically to spacer, acknowledgement falls | Every pair is 00 spacer; 11 is illegal |
| Decoupled | A transfer occurs at a rising clock edge with valid and ready both high; input data/valid may change when no transfer occurs | Valid/ready do not encode a four-phase return; bridge outputs are inactive during reset |

Consequently the long-hold buffer's acceptance-before-offer ordering is not imposed on every encoding. In the dual-rail probe, a complete output can be consumed before the completion tree's input acknowledgement has propagated. Tests associate it with the offered word and check acceptance/delivery accounting after settling. The receiving clocked bridge acknowledges its asynchronous input only when its Decoupled output commits. These are explicit local semantics, not interchangeable event names.

## Dual-rail storage and completion

`qdi.DualRailBuffer[T]` is a small Muller half-buffer probe: two C-elements per payload bit hold rails; per-bit OR cells feed a direct N-input C-element for completion. Completion stays high during a partial spacer wave and falls only after all bits return. It is not the fully decoupled long-hold buffer and does not implement a FIFO catalog.

The later [CA-08 family](qdi-family.md) adds `DualRailStrongBuffer[T]`, small stored DIMS functions and routing. Strong storage waits for complete input data/spacer before any corresponding output transition and retains output data until downstream acknowledgement. Its separate contract and tests preserve the earlier probe's weaker indication semantics.

The topology follows Sparsø, *Asynchronous Circuit Design: A Tutorial*, March 17, 2006 draft, section 2.4.3, figures 2.12–2.13, printed page 21 / PDF page 35. The [university-hosted PDF](https://www.inf.pucrs.br/~calazans/graduate/SSD/Bibliography/Sparso-Furber-Short.pdf) was visually inspected; SHA-256 `3838e2815f653c47e3cb2040420b23589b5cc5d3101b06b95d0eaa1459d18dc6`. The implementation places the inverted downstream acknowledgement inside each atomic C-element boundary and uses ideal forks. All cell outputs have explicit positive inertial model delay. This is a bounded digital probe in the QDI work area; it is not a physical QDI qualification or a claim that arbitrary inversion/fork decomposition is safe.

Eight deterministic cases independently vary all 25 primitive delays from 1–10 ns. Each case delivers every 8-bit word, repeated payloads and post-reset traffic: 262 deliveries, one aborted accepted token and four resets. Inputs arrive and return one bit at a time. Passive observers check illegal codewords, monotonic transitions, early withdrawal, full-word completion and complete spacer return. Reset interrupts a partial word, a stalled full word and a partial spacer wave. The last two are different reset/accounting cases.

Replacing completion with only the first bit must fail `DUAL_EARLY_COMPLETE`. Replacing its stateful C-element behavior with a plain all-bits AND must fail `DUAL_EARLY_SPACER`. Passing ordinary payload traffic alone would miss the latter.

## Explicit-clock bridges

Both bridges are `RawModule`-based with explicit `Clock` and `AsyncReset`. Each has at least two control synchronizer registers and local asynchronous reset assertion / synchronous reset release. Reset is coordinated across the entire connected domain. Hold it until the asynchronous cells quiesce, and run both clocks through local release before sending new traffic. Independent endpoint reset/restart is unsupported.

`DecoupledToFourPhase` captures exactly at input `fire`. It waits a full local cycle before raising request, holds the captured payload, synchronizes acknowledgement, lowers request, then waits for synchronized acknowledgement return before accepting another word. The input need not be irrevocable. Poisoning/changing input data and withdrawing valid while blocked are exercised.

`FourPhaseToDecoupled` synchronizes request, waits an additional local state interval, then samples the held bundled bus. It keeps output valid/data stable until `fire`, raises input acknowledgement at that commit, and waits for synchronized request return before lowering acknowledgement. It does not synchronize each payload bit independently. The digital contract assumes the held bus has settled before this sample; physical implementation needs a bound on bus propagation relative to the receiving clock and request path, plus proper synchronizer cell placement and reset-release constraints. Flip-flop count and simulation do not establish MTBF.

The general held-bus/control-synchronizer pattern was checked against the author's [CDC Word Synchronizer notes](https://fpgacpu.ca/fpga/CDC_Word_Synchronizer.html); that implementation uses a different two-phase handshake. This library uses a four-phase handshake at that boundary. Chisel's [Decoupled documentation](https://www.chisel-lang.org/docs/explanations/interfaces-and-connections#the-standard-ready-valid-interface-readyvalidio--decoupled) supplies the standard ready/valid boundary convention.

Each individual bridge runs 144 transfers, a blocked-token reset/abort and successful restart. Edge-count checks enforce the declared synchronizer plus controller latency. A one-stage synchronizer mutation in each direction must fail its specific early-response check. Four composed cases run 144 transfers each with source/sink half-periods `(7,11)`, `(11,7)`, `(5,5)` and `(3,19)` ns and declared phase offsets, backpressure and reset. They saturate two unique token slots, block a third pending offer, then abort both held tokens and restart. The receiver's snapshot duplicates the still-reserved long-hold slot until commit, so three storage registers do not mean three independent token slots. These finite schedules test digital transfer behavior; they do not simulate analog metastability or prove all clock relationships safe.

## Export, replay and remaining gate

Exported channels identify their electrical protocol, logical token contract, payload layout, reset domain and relevant endpoints. Dual-rail has two payload rails; Decoupled has valid/ready/data/clock. Corrupting those protocols, control widths or clock bindings must fail. Both pinned compiler routes request `disallowLocalVariables` so Icarus can compile Chisel register logic. Mapping-only probes may force elaborated clocked registers, as earlier probes forced primitive outputs, to exercise every anchor bit. Functional runs never use those forces. The [optimized export](optimized-export-and-simulation.md) resolves read-only probe references through the compiler ABI and tests deduplicated instance identity.

Run **`python tools/qualify.py`** for setup and all campaigns. For a focused replay after emission, use `python verification/run_architecture.py`. Reports include exact commands, source/bench hashes, simulator/platform identity, activity counts, event logs and VCDs. The separate published-JAR consumer runs the same architecture campaign on its own RTL.

This completes the first shared-channel/encoding probe, alongside the bounded timing-policy fix and one-command qualification entry point. Optimized/deduplicated observation, timing-intent markers and a Chisel-native simulation lane are now implemented. The subsequent [frozen campaign and fresh-context agent reviews](l0-acceptance.md) close L0 for Windows/Linux, permitting CA-06 to begin. Full dual-rail converters, CDC qualification and the FIFO/fork/join/select/merge catalog have not been claimed complete.
