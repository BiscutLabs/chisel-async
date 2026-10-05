# Contributor instructions

- Keep communication succinct and professional. Implement in this repository; the MCU and simulator have separate repositories.
- Read `docs/contracts.md` and `docs/roadmap.md` before changing channel or primitive semantics.
- Preserve modern Chisel APIs: RawModule, ExtModule/addResource and circt.stage.ChiselStage. Avoid legacy Scala FIRRTL transforms and hidden clocks.
- Keep behavioral simulation views clearly identified. Passing functional tests must not be described as physical timing, QDI or metastability qualification.
- Keep Scala payload types intact except at documented external primitive boundaries. Reject implicit resizing and unsupported payload types.
- Use the existing Scala, Python and cocotb tests. Run the README commands relevant to a change; update contracts and negative controls with behavioral changes. Offer tests/docs when a new feature lacks them.
- Tests must check meaningful activity and specific failure reasons. Never turn required missing tools, empty suites or failed negative controls into a pass.
- Use portable Python/JVM tooling and native Windows/Linux/macOS targets. Do not add Yosys, a PDK, Linux-only runtime assumptions or a Chiselator dependency.
- Keep downloaded tools, generated files, virtual environments and simulation evidence out of Git. Pin tool versions and hashes where the bootstrap supports them.
- Update README and qualification status when support changes. Preserve the original project provenance; do not copy or rename ASYNC-Chisel implementation code.
