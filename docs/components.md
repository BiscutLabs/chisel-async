# Component catalog

Chisel-async provides storage, routing, arithmetic and protocol converters for
several channel encodings. Choose your encoding below, then find the operation
you need. Each table shows which components store tokens and which only coordinate
handshakes. All asynchronous blocks require coordinated reset; structural
bundled-data blocks also need a timing policy, and dual-rail blocks need positive
model delays. Follow the linked sources for complete constructors.
The [terminology and chisel-click comparison](component-terminology.md) explains
which operations correspond and where their storage or timing contracts differ.

## Foundation

| API | Purpose | Use it for |
| --- | --- | --- |
| [`AsyncModule`](../src/main/scala/chiselasync/core/AsyncModule.scala) | Clockless `RawModule`, explicit reset, scoped contract, `asyncChild` | A composed asynchronous block |
| [`ResetDomain`](../src/main/scala/chiselasync/core/ResetDomain.scala) | Identity for a coordinated reset network | Share the actual parent's domain, not a fresh object with the same name |
| [`ClockedBridge`](../src/main/scala/chiselasync/clocked/Bridges.scala) | Base class with explicit clock, local reset release and control synchronization | Extend when implementing a registered clocked boundary |
| [`Channel[T]`](../src/main/scala/chiselasync/protocol/Channel.scala) | Typed token intent and encoding factories | Declare compatible payload/reset intent across styles |
| `FourPhase[T]`, `TwoPhase[T]`, `DualRail[T]` | Encoding-specific ports and checked connection helpers | Electrical interfaces; none adds storage |
| [`DesignContract`](../src/main/scala/chiselasync/metadata/DesignContract.scala) | Channels, children, capacities, endpoints, primitives and obligations | Register the composition for strict export |

## Four-phase bundled data

See [composition and timing](bundled-data.md). Control for the structural stage
follows the fully decoupled Furber–Day long-hold topology.

| Component | Ports and behavior | Storage / important condition |
| --- | --- | --- |
| [`FourPhaseStage[A, B]`](../src/main/scala/chiselasync/bundled/FourPhaseStage.scala) | `in: A`, `out: B`, pure typed transform | One slot, reserved through complete output return |
| `LongHoldBuffer[T]` | Identity stage | Same one-slot structural controller |
| [`FourPhaseBuffer[T]`](../src/main/scala/chiselasync/bundled/FourPhaseBuffer.scala) | Behavioral request/data/ack storage | One slot; zero-delay reference model, not structural implementation |
| [`FourPhaseFifo[T]`](../src/main/scala/chiselasync/bundled/FourPhaseComposition.scala) | Ordered pipeline of `depth` stages | Exactly `depth >= 1` slots; optional initial literals occupy that capacity |
| `InitialTokens[T]` | `out`, `done`; emits literals once per reset epoch | Finite source; `done` follows final complete return |
| `FourPhaseFork[T]` | `in`, `out: Vec`; broadcast | Unbuffered; both acknowledgement phases wait for every branch |
| `FourPhaseJoin[A, B]` | `left`, `right`, `out: Joined[A, B]` | One stored operand per input; nth left pairs with nth right |
| [`FourPhaseRegFork[A,B,C]`](../src/main/scala/chiselasync/bundled/FourPhaseRegFork.scala) | `A => (B,C)`, outputs `left`, `right` | One shared slot, waits for both branches; resets empty |
| [`FourPhaseMux[T]`](../src/main/scala/chiselasync/bundled/FourPhaseMux.scala) | `in: Vec`, `select: UInt` channel, `out` | One selector slot plus one output data slot; only selected data is consumed |
| `FourPhaseDemux[T]` | `in: Selected[T]`, `out: Vec` | One captured transaction; only indexed destination is offered |
| `FourPhaseMerge[T]` | `in: Vec`, `out` | One buffered output; caller serializes whole input handshakes |
| [`FourPhaseArbiter[T]`](../src/main/scala/chiselasync/bundled/FourPhaseArbiter.scala) | Two competing inputs, one output | One buffered output with MUTEX and return interlocks |
| `Selected[T]` | `index`, `data` | Routing choice travels with the payload |
| `Joined[A, B]` | `left`, `right` | Typed pair, with independently sized operands |

Fork/mux/demux/merge counts must be at least two. A routing index must be within the
declared destination count; invalid codes and merge overlap are diagnosed by
simulation guards, not made into defined routing behavior.

## Two-phase bundled data

[`TwoPhaseStage`, `TwoPhaseBuffer`, `TwoPhaseFifo`, `TwoPhaseInitialTokens`,
`TwoPhaseFork`, `TwoPhaseRegFork`, `TwoPhaseJoin`, `TwoPhaseMux`, `TwoPhaseDemux`, `TwoPhaseMerge`, and
`TwoPhaseArbiter`](../src/main/scala/chiselasync/bundled/TwoPhaseComposition.scala)
present equivalent typed operations through transition-signalling ports.

They wrap the four-phase cores with sequential phase adapters. They require
`PhaseTiming` as well as the core's applicable timing parameters. They are not
independently synthesized two-phase pipeline topologies, and fewer external edges
do not by themselves imply lower latency. The core's capacity, routing, and
exclusivity obligations still apply.
`FourPhaseSelect` / `TwoPhaseSelect` are deprecated aliases of the demultiplexers.

## Dual-rail family

See [dual-rail logic](dual-rail.md) for packing, indication and assumptions.

| Component | Operation | Important condition |
| --- | --- | --- |
| [`DualRailStrongBuffer[T]`](../src/main/scala/chiselasync/qdi/DualRailStrongBuffer.scala) | Strongly indicating typed half-buffer | Holds output until source spacer and downstream acknowledgement |
| [`DualRailBuffer[T]`](../src/main/scala/chiselasync/qdi/DualRailBuffer.scala) | Original Muller half-buffer/completion probe | Weaker word indication; not interchangeable with strong storage |
| [`DualRailFunction[A, B]`](../src/main/scala/chiselasync/qdi/DualRailFunctions.scala) | Complete DIMS truth table with stored output | One to four total input bits; every input code must be defined |
| `DualRailNot`, `DualRailAnd`, `DualRailOr`, `DualRailXor` | Standard Boolean functions | Binary operators pack operands in bits 0 and 1 |
| `DualRailSelect` | Select between two Boolean values | Three-bit input: bit 2 chooses bit 0 or 1; both are indicated |
| `DualRailFullAdder` | One-bit addition with carry | Inputs bits 0/1/2 are a/b/carry; output bits 0/1 are sum/carry |
| [`DualRailAdder2`](../src/main/scala/chiselasync/qdi/DualRailAdder2.scala) | Small two-bit arithmetic reference | Four input bits encode two operands; three-bit result |
| [`DualRailFork[T]`](../src/main/scala/chiselasync/qdi/DualRailRouting.scala) | Broadcast rails, aggregate acknowledgements | Unbuffered, adds no word-level strong indication |
| `DualRailJoin[A, B]` | Store operands and present a typed pair | Strong input storage and rendezvous |
| `DualRailDemux[T]` | Captured two-destination routing | `Selected[T]` input; strong selected output, other output stays spacer |
| `DualRailMerge[T]` | Buffered exclusive merge | Serialize complete valid/spacer handshakes; no arbitration |

## Encoding and clock boundaries

| Component | Direction | Responsibility |
| --- | --- | --- |
| [`FourPhaseToTwoPhase`, `TwoPhaseToFourPhase`](../src/main/scala/chiselasync/interop/PhaseAdapters.scala) | Between bundled protocols | Buffered conversion; phase state, return guards and history closure |
| [`FourPhaseToDualRail`, `DualRailToFourPhase`](../src/main/scala/chiselasync/interop/DualRailConverters.scala) | Bundled ↔ RTZ rails | One buffered token; valid/spacer completion and held decode |
| [`DecoupledToFourPhase`, `FourPhaseToDecoupled`](../src/main/scala/chiselasync/clocked/Bridges.scala) | Clocked ↔ four-phase | Explicit clock, held data bus, synchronized controls, local reset release |
| [`AsyncMemoryPort`](../src/main/scala/chiselasync/clocked/MemoryPort.scala) | Async request/response ↔ Decoupled backend | One outstanding transaction through full response return; no storage or rollback |
| `MemoryShape`, `MemoryRequest`, `MemoryResponse` | Typed memory interface | Byte addresses, little-endian byte enables, response data/error |
| [`PendingEventBridge`](../src/main/scala/chiselasync/clocked/PendingEventBridge.scala) | Clock-sampled external levels → four-phase bit sets | Rising-edge capture and coalescing; not an arbitrary pulse catcher |

For two-phase or dual-rail clocked integration, compose the explicit encoding
converter with a four-phase clock bridge. There is no automatic CDC insertion.

## Primitives and timing support

These `ExtModule` cells package versioned SV digital models. They are building
blocks with explicit atomic-cell assumptions, not a technology cell library.

| API | Meaning |
| --- | --- |
| [`CElement`](../src/main/scala/chiselasync/primitives/CElement.scala) | Two-input unanimity changes output; disagreement holds it; reset clears |
| [`AsymmetricCElement`](../src/main/scala/chiselasync/primitives/ControlCells.scala) | N common inputs plus rise-only/fall-only groups; inversion masks remain inside the atomic boundary |
| `ControlGate`, `GateOperation` | Resettable delayed buffer, invert, or OR view |
| `ClosingLatch` | Transparent when `closed = 0`; inertial output propagation; internal model aperture is zero |
| [`Latch`](../src/main/scala/chiselasync/primitives/Latch.scala) | Transparent when `enable = 1`; explicit reset value and four-state diagnostic behavior |
| [`DelayLine`](../src/main/scala/chiselasync/primitives/DelayLine.scala) | Captured-vector transport or inertial delay; reset cancels queued deliveries |
| [`XorGate`, `Toggle`](../src/main/scala/chiselasync/primitives/PhaseCells.scala) | Phase comparison and request-event toggle state |
| `Mutex`, `MutexPolicy` | Finite digital arbitration choices and resolution delays; no analog metastability model |
| [`ModelTime`, `DelayPolicy`](../src/main/scala/chiselasync/metadata/ModelTime.scala) | Exact integer femtoseconds and delay scheduling policy |
| `DelayBounds`, `ControlDelays`, `BundledTiming`, `PhaseTiming`, `QdiTiming` | Declared model envelopes and guards, described in the timing guide |
| [`TimedCapture[T]`](../src/main/scala/chiselasync/bundled/TimedCapture.scala) | Independent data/control-delay experiment with transaction identity and setup/hold observation; not a handshake stage |
| [`ExportDesign`](../src/main/scala/chiselasync/metadata/ExportDesign.scala) | Optimized or debug RTL plus typed metadata/probes; validate before consuming as a checked export |
| [`AsicMapping`](../src/main/scala/chiselasync/metadata/AsicMapping.scala) | Exhaustive technology-cell binding and a separate synthesis file list; no supplied PDK or physical closure |
| [`TimingConstraints`](../src/main/scala/chiselasync/metadata/TimingConstraints.scala), [`OpenSta`](../src/main/scala/chiselasync/metadata/OpenSta.scala) | Bind supported obligations to mapped pins; generate SDC and check declared paths/arcs and strict relative timing |
| [`AsyncTest`](../src/main/scala/chiselasync/testing/AsyncTest.scala) | Typed four-phase, two-phase and dual-rail event tests, seeded cell variation and optional pin skew |
| [`Simulator`](../src/main/scala/chiselasync/testing/Simulator.scala) | Explicit simulator paths, installation probe and retained tool versions |

N-input symmetric C behavior uses `AsymmetricCElement` with only common inputs.
It is a direct N-input primitive, not an implicitly equivalent tree of two-input
cells. `CompositionCells` and package-private phase helpers are internal utilities;
use the public components above to build designs with the documented contracts.
Timing and QDI marker cells carry constraints for export tooling, not token data.

`experimental.UnsafeFourPhaseStage` and `UnsafeFourPhaseBuffer` preserve a known
race for regression. They are withdrawn and excluded from supported design choices.
