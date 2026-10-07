# Scientific sources and design comparisons

> Historical development record. For current usage, read the [user documentation](../../index.md).

This record identifies the published circuit designs, model assumptions and library comparisons used during development.

The comparison with [ASYNC-Chisel revision 1af2cf4](https://github.com/Jilin-Zhang/ASYNC-Chisel/tree/1af2cf4f621aa77657cab25858cc4a038a7291d6) examines handshake organization, configurable controllers and verification coverage. The detailed comparison and proposed improvements are in the [initial implementation plan](https://github.com/crockpotveggies/chiselator/blob/3edf79529ab9909d3039dc33c1274d2fbdc173dd/docs/chisel-async-implementation-plan.md).

Current API usage follows upstream [Chisel external modules](https://www.chisel-lang.org/docs/explanations/blackboxes), [connection operators](https://www.chisel-lang.org/docs/explanations/connectable), and the [7.16.0 compiler stage](https://github.com/chipsalliance/chisel/blob/v7.16.0/src/main/scala/circt/stage/ChiselStage.scala). Native compiler archives come from [CIRCT firtool 1.160.0](https://github.com/llvm/circt/releases/tag/firtool-1.160.0). Event tests use [cocotb](https://docs.cocotb.org/en/stable/) and [Icarus Verilog](https://github.com/steveicarus/iverilog/tree/v13_0).

External dependencies and downloaded tools retain their own licenses. Their binaries are not committed to this repository.

The withdrawn structural stage was our functional decomposition of the channel contract, using explicit resettable latches. It did not reproduce a published controller and failed under internal delays. The independent Muller comparison now explicitly follows a published topology; its [provenance, inspected figures, PDF hash and added timing assumptions](controller-comparison.md#source-and-contract) are recorded separately.

The replacement `FourPhaseStage[A, B]` follows Furber–Day section 7, Figs. 14–15, with a separately implemented event graph and atomic asymmetric cells. The [long-hold provenance record](long-hold-controller.md#inspected-source-and-preserved-topology) identifies the inspected eight-page source, its SHA-256, precise topology and our added timing guards.

The October 5 verification comparison covers chisel-click revision `ae87f671bce101a22ea3ec40ad0e9e18a8cc3a28` and ACT/actsim simlib revision `d92b0d99a0eb214acf3ff03fb484039fb40bf4cb`. [The comparison](verification.md#comparison-with-inspected-upstream-tests) records links and lessons: component-specific schedules, independent algorithm oracles, and deliberate scoreboard mismatches.

The first dual-rail storage/completion probe follows the visually inspected Sparsø tutorial figures 2.12–2.13 (printed page 21), with atomic inversion and ideal-fork assumptions recorded in [logical-channels.md](logical-channels.md). The explicit-clock bridges use the documented held-bus/control-synchronizer method.

The CA-06 rendezvous patterns are informed by chapter 5's fork/join/exclusive-merge discussion in Sparsø's [2020 book](https://orbit.dtu.dk/en/publications/introduction-to-asynchronous-circuit-design/). The primary-source indexed text was checked; its PDF download endpoint returned 404 during this work, so no new visual inspection or PDF hash is claimed. [Composition contracts](four-phase-composition.md) distinguish the published rendezvous concepts from our additions and record exact modeled assumptions.

Optimized export uses the upstream [read-probe ABI](https://www.chisel-lang.org/docs/explanations/probes). The Scala lane uses [ChiselSim](https://www.chisel-lang.org/docs/explanations/testing); Chisel 7.16.0 source artifacts were inspected for its workspace, backend and simulation interfaces. The Windows build adapter supplies POSIX compatibility functions without patching the upstream JAR or simulator source. The Linux backend is built from the official [Verilator v5.046 archive](https://github.com/verilator/verilator/releases/tag/v5.046), with its checksum pinned in `tools/build_verilator.py`. [The implementation record](optimized-export-and-simulation.md) describes the adapter and evidence limits.

CA-07 arbitration follows the MUTEX/return-interlock topology in the cached Sparsø–Furber tutorial, §5.8.1–5.8.2, Figure 5.21. The phase adapters implement the sequential protocol discussed in the primary ASYNC 2000 tutorial, Task 2, with full-return handshakes. [CA-07 contracts](arbitration-and-two-phase.md) distinguish these sources from our buffered adapters, finite digital MUTEX policies and added timing guards.

The CA-08 [bounded dual-rail family](qdi-family.md) uses the same tutorial's strong/weak indication distinction and DIMS construction (§5.3.2 and §5.5.1, Figure 5.10). Complete C-element minterms retain logically redundant inputs because indication concerns both data and spacer phases. The family includes typed strong storage, a table generator, routing, timing markers, independent Boolean/rail accounting and actual-RTL mutation tests. Physical QDI qualification still requires technology and layout validation.
