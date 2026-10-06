# External review: controller withdrawal and revised priorities

October 5, 2026. The external review identifies an architectural blocker, not merely missing timing coverage. CA-06 must not build on the custom structural controller. L0 remains open for controller replacement and architectural validation as well as independent review.

## Reproduced failure

The reviewer reports 165 failing seeds out of 300 in a three-stage random-delay experiment, including 23 deadlocks. Those statistics are externally reported; we do not have that harness or its seed definitions and have not reproduced that campaign.

Our independent directed experiment uses the emitted `StructuralBufferExample` RTL. It adds a 10 ns inertial delay to the `full & release` branch of the occupied-latch enable and 1 ns captured-value nonblocking delays to all four latches. Other logic remains ideal. The paired baseline uses the same delayed latches and a zero-delay release branch. This is an explicit digital counterexample, not a characterized gate model or a manufacturing distribution.

One input is accepted and delivered. During output return, occupied clears, returning clears, and occupied captures one again before its delayed enable closes. The output offers a second token without another accepted input. The baseline completes with exactly one acceptance, delivery and offer; the delayed case fails specifically with `RACE_DUPLICATE_OFFER accepted=1 delivered=1 offered=2`. Crashes, timeouts and unrelated failures do not count as reproductions.

Replay after emitting the fixtures: `python verification/controller_race.py`. The runner validates the original export, retains annotated sources and their hashes, simulator identity, logs, VCD and `report.json` in `target/verification/controller-race`. It does not change the packaged latch resource. CI retains this counterexample alongside the zero-delay regression corpus.

The former public classes have moved to `chiselasync.experimental.UnsafeFourPhaseStage` and `UnsafeFourPhaseBuffer`. They are retained solely for regression. Their old `chiselasync.bundled` names are removed. Passing historical zero-delay tests or successfully consuming these fixtures from a JAR does not approve them for new designs.

## Review decisions

| Topic | Decision and next acceptance evidence |
| --- | --- |
| Published controller | Accepted. Select a specific published topology and preserve its event graph, capacity, data-validity interval, reset, fork and relative-delay assumptions. Start with a Muller reference comparison, then choose the controller required by our contract. Do not silently substitute a half-buffer for a fully decoupled one-entry buffer. |
| Primitive control cells | Accepted for hazard-sensitive control. Keep required gate/C-element topology at explicit primitive boundaries and verify emitted connectivity. An `ExtModule` alone does not constrain downstream synthesis or establish isochronic forks; future cell mappings need their own preservation and timing constraints. Ordinary Chisel combinational datapaths remain appropriate. |
| Logical channels and encodings | Accepted as an architecture requirement before CA-06. Separate typed token-flow intent from concrete electrical interfaces. Retain encoding-specific wire types and explicit, buffered converters; a shared `Channel[T]` superclass or renamed bundle alone would not provide interchangeability. Validate semantics using bundled, dual-rail and clocked examples first. |
| Type-changing stages | Accepted for the replacement: distinct input/output generators and `A => B`, with output shape checked against `B`. Include a Bundle-of-operands to wider UInt sum and signed/aggregate cases. Do not expand the withdrawn controller API. |
| Matched delay | Accepted as an explicit timing policy, including units, provenance, minimum/maximum assumptions, pulse policy and setup/hold. Positive delay must be implemented and observed, not merely carried as an unused parameter. Functional-only mode must be explicit; zero cannot imply successful bundling. |
| Reset domains | Preserve identity checks. New `asyncChild(id)(domain => ...)` constructs, registers and wires a child with the parent's reset domain; examples use it and misuse is rejected. Roots remain independent. Do not equate equal labels or infer reset-driver identity from incomplete elaboration wiring. Automatic ambient inheritance is not implemented. |
| Observation/export | Accept the scalability concern. Current `ca_*` ports are a qualification interface, not a production netlist interface. Prototype read-only probes/layers and in-IR timing markers under optimization/deduplication; require actual mapping/corruption tests before replacing the checked route. Markers also need preservation guarantees and a mapped-cell stripping policy. |
| Version checks | Keep fail-closed checks for qualified export. A future explicitly exploratory mode may warn and record actual versions, but must not produce a qualified result. `--no-dedup` increases module definitions, not necessarily instantiated hardware area; measure optimized output rather than assuming a chip-size multiplier. |
| Breadth before catalog | Accepted. Move a small dual-rail completion/storage example and clocked `Decoupled` bridges ahead of FIFO/fork/join expansion. Specify synchronizer latency, bundled data holding, reset restart and commit boundaries. Digital tests cannot establish MTBF. |
| Consumer setup and Scala testing | Separate consumer instructions from repository qualification. A one-command qualification wrapper and a ScalaTest/ChiselSim lane remain implementation work. Use `simulateRaw` for RawModule with explicit reset; qualify its backend/time advancement rather than replacing the existing independent event oracle. |
| C-element families | Add direct N-input semantics and separately specified asymmetric variants with independent state/input tests. A binary C-element tree is not generally equivalent to an N-input C-element for arbitrary non-monotonic inputs; any restricted completion-tree use must state its monotonic phase assumptions. |

The immediate sequence is: preserve this counterexample; compare published controllers under explicit assumptions; validate logical-channel/type-changing/timing APIs using the three small encoding examples; qualify optimized observation/intent export; then resume CA-06. The timing/compiler foundation remains useful, but it cannot compensate for an unsafe controller.

## Sources checked

Furber and Day's [Four-Phase Micropipeline Latch Control Circuits](https://apt.cs.manchester.ac.uk/ftp/pub/apt/papers/4phCtl.pdf), especially the conclusions, distinguishes the simple controller's 50% pipeline occupancy from the decoupled alternatives and discusses a long-hold variant. A comparison must respect those differences; random-delay success alone is not a proof.

Chisel's [probe documentation](https://www.chisel-lang.org/docs/explanations/probes) describes verification references without physical ports, their naming/optimization constraints and generated reference ABI. Its [layer documentation](https://www.chisel-lang.org/docs/explanations/layers) covers optional verification logic. The [testing APIs](https://www.chisel-lang.org/docs/explanations/testing) distinguish `simulate` initialization from `simulateRaw`'s explicitly driven reset. These capabilities are directions for a qualified implementation, not results already obtained here.
