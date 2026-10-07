# Contributor instructions

- Keep communication succinct and professional. Implement in this repository; the MCU and simulator have separate repositories.
- Read `docs/contracts.md` and the relevant component guide before changing channel or primitive semantics. `docs/index.md` is the active documentation entry point; `docs/archive/` contains historical plans and review evidence, not an active roadmap.
- Preserve modern Chisel APIs: RawModule, ExtModule/addResource and circt.stage.ChiselStage. Avoid legacy Scala FIRRTL transforms and hidden clocks.
- Keep behavioral simulation views clearly identified. Passing functional tests must not be described as physical timing, QDI or metastability qualification.
- Keep Scala payload types intact except at documented external primitive boundaries. Reject implicit resizing and unsupported payload types.
- Use the existing Scala, Python and cocotb tests. Run the README commands relevant to a change; update contracts and negative controls with behavioral changes. Offer tests/docs when a new feature lacks them.
- Tests must check meaningful activity and specific failure reasons. Never turn required missing tools, empty suites or failed negative controls into a pass.
- Use portable Python/JVM tooling and native Windows/Linux/macOS targets. Do not add Yosys, a PDK, Linux-only runtime assumptions or a Chiselator dependency.
- Keep downloaded tools, generated files, virtual environments and simulation evidence out of Git. Pin tool versions and hashes where the bootstrap supports them.
- The GitHub Pages site in `site/` renders `docs/` and generated Scaladoc. Keep one source for guide content. For website changes, run `npm --prefix site run build` and `npm --prefix site run check` after `sbt doc`; verify responsive layouts and interactive controls in a browser. Read `docs/website.md` for deployment details.
- Update the README compatibility matrix and `docs/compatibility.md` when support changes. Keep quickstart snippets synchronized with their executable sources using `python tools/check_docs.py`. Preserve archived evidence and original project provenance; do not copy or rename ASYNC-Chisel implementation code.
