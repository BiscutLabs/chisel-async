# Compatibility and versioning

Use the versions in the [compatibility matrix](../README.md#compatibility-matrix)
to build and test chisel-async with the supported toolchain. Pin those versions
to make your results reproducible. The current `0.1.0-RC1` is a GitHub prerelease;
a stable release and Maven Central publication are still deferred.

## Tested toolchain

See the [README compatibility matrix](../README.md#compatibility-matrix) for the
tested versions and host status. The website includes that same table below during
its build; the README remains its single source.

<!-- compatibility-matrix -->

## Different kinds of compatibility

| Layer | What compatibility means |
| --- | --- |
| Scala/JAR | Classes link with the selected Scala binary version and dependencies |
| Chisel/compiler plugin | Hardware elaborates with the matching plugin and full Scala version |
| firtool/export | The emitted ABI, model resources, timing markers and reflected types validate |
| Simulator | The required timing, scheduling, four-state or clocked behavior executes correctly |
| Physical implementation | Cells, wires, forks, CDC and reset constraints are characterized and closed; not supplied here |

Chisel's [versioning policy](https://www.chisel-lang.org/docs/appendix/versioning)
describes its compatibility guarantees. Those guarantees do not automatically
qualify this library's emitted artifacts on a different compiler. `ExportDesign`
warns on runtime/compiler drift and records the actual versions. Set
`qualifiedOnly = true` to reject drift at emission; strict `check_export.py`
validation still requires the exact tested versions.

Chisel-async uses the same JVM JAR on Windows and Linux for each supported Scala
binary version. The JAR contains SystemVerilog sources and schemas; you install
native simulators and compilers separately. Host tests cover installation,
compiler execution, resource extraction, paths and simulation. macOS testing
is deferred.

The optional OpenSTA checker was exercised with version 2.7.0 on Linux, including
19 known-path and required-failure cases. This is separate from Windows/Linux
library qualification; no native Windows OpenSTA support is claimed. GF180 trial
adapters have [limited functional/Liberty evidence](gf180-reference.md#what-the-current-experiments-establish),
not complete hardware qualification. An Icarus 12.0 consumer replay encountered
runtime failures in history-closure cases, so Icarus 13 remains the tested choice.

## Versioning

Use independent library versions under `io.github.biscutlabs:chisel-async_2.13`.
The version does not mirror the full Chisel version. Every release states its
tested Chisel, compiler plugin, Scala, firtool, Java, simulator and host matrix.

The build declares sbt's `early-semver` scheme:

- Before 1.0, patch releases preserve the documented API and compatible contracts;
  breaking changes require a new minor version and migration notes.
- From 1.0, incompatible public changes require a major version. Compatible new
  functionality uses a minor version; compatible fixes use a patch version.
- `-RC1`, `-RC2`, etc. identify release candidates. `-SNAPSHOT` is mutable development
  output and does not carry stable-release guarantees.

Protocol/reset meanings, timing obligations, and exported schema semantics are
part of compatibility, not merely Scala method signatures. A fix that invalidates
an old timing policy must be described and versioned accordingly. Cell model IDs
and export schemas have their own versions; changing the library version does
not silently reinterpret an old export.

For a new Chisel version, first run elaboration, strict export, representative
simulation and clean-consumer checks. Expand the matrix only after evidence
supports it. When supporting it needs library changes, publish an appropriate
library version and keep the previously supported release identifiable.

## Host testing policy

For releases, build the distributable once on Linux and test consumption of the
same artifact on each supported host. Run complete native qualification for a
release candidate and when models, compiler integration or host-sensitive tools
change. Focus ordinary consumer checks on dependency resolution, resources,
elaboration/export, a representative simulation and path handling.

The existing [native workflow](../.github/workflows/ci.yml) still runs complete
Windows/Linux campaigns, each with local publication and a clean consumer. The
[tagged release workflow](../.github/workflows/release.yml) builds once and calls
that native workflow with the candidate artifact for an additional hash-bound
consumer check. Both hosts must pass before the release can be published.

## Evidence

The [RC1 release page](https://github.com/BiscutLabs/chisel-async/releases/tag/v0.1.0-RC1)
includes the source commit, artifact hashes and Windows/Linux consumer reports.
Publication requires the complete native campaigns and consumption of the same
Linux-built JAR to pass on both hosts. The records below describe earlier work.

The existing implementation passed the complete native Ubuntu 24.04 and Windows
2025 campaign in [GitHub Actions run 37541425995](https://github.com/BiscutLabs/chisel-async/actions/runs/37541425995)
at `64fd3931c7c242f3bf8a4ad9ef682e6729b72bdd`. The subsequent
`37265e2d6908621edb318b6958c40875cfae6300` records its independent review and evidence;
execution inputs were unchanged in that documentation-only commit.

That evidence includes 54 Scala API tests, 518 Python tests, 81 exports, seven
ChiselSim tests and the event campaigns, including a clean-JAR consumer. It does
not automatically certify later edits to documentation, examples or packaging.
The [archived qualification record](archive/development/qualification.md) preserves
exact source versions, counts, hashes, initial failures and repaired runs.

Native Windows ChiselSim requires the [documented adapter](testing.md#native-windows-chiselsim)
and short space-free simulation paths. macOS remains deferred. Complete public
release acceptance, namespace ownership, signing and Central publication remain
separate from the historical library campaigns.
