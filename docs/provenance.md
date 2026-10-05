# Provenance

The chisel-async implementation is independently written under Apache 2.0. It does not copy or rename ASYNC-Chisel source and does not promise API compatibility with it.

Design research inspected [ASYNC-Chisel revision 1af2cf4](https://github.com/Jilin-Zhang/ASYNC-Chisel/tree/1af2cf4f621aa77657cab25858cc4a038a7291d6), which is MIT licensed. Its handshake organization and configurable controller approach are prior art; the source audit and planned improvements are in the [initial implementation plan](https://github.com/crockpotveggies/chiselator/blob/3edf79529ab9909d3039dc33c1274d2fbdc173dd/docs/chisel-async-implementation-plan.md).

Current API usage follows upstream [Chisel external modules](https://www.chisel-lang.org/docs/explanations/blackboxes), [connection operators](https://www.chisel-lang.org/docs/explanations/connectable), and the [7.16.0 compiler stage](https://github.com/chipsalliance/chisel/blob/v7.16.0/src/main/scala/circt/stage/ChiselStage.scala). Native compiler archives come from [CIRCT firtool 1.160.0](https://github.com/llvm/circt/releases/tag/firtool-1.160.0). Event tests use [cocotb](https://docs.cocotb.org/en/stable/) and [Icarus Verilog](https://github.com/steveicarus/iverilog/tree/v13_0).

External dependencies and downloaded tools retain their own licenses. Their binaries are not committed to this repository. Any future source reuse must record its exact source, license and retained notices here.

The structural stage is our functional decomposition of the published channel contract, using explicit resettable latches. It does not copy a controller topology or claim the physical properties of a published circuit. Sparsø's [Introduction to Asynchronous Circuit Design](https://backend.orbit.dtu.dk/ws/portalfiles/portal/215895041/JSPA_async_book_2020_PDF.pdf), §2.4.1, distinguishes bundled-data functional structure from the matching delays needed for physical operation; our contracts preserve that distinction. No text, diagram or implementation from the book was incorporated.

The October 5 verification review also inspected chisel-click revision `ae87f671bce101a22ea3ec40ad0e9e18a8cc3a28` and ACT/actsim simlib revision `d92b0d99a0eb214acf3ff03fb484039fb40bf4cb`. [The comparison](verification.md#comparison-with-inspected-upstream-tests) records links and lessons: component-specific schedules, independent algorithm oracles, and deliberate scoreboard mismatches. Our reference models, observers and regressions were independently written; no upstream test or implementation source was incorporated.
