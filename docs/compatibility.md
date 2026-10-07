# Compatibility and versioning

The [README matrix](../README.md#compatibility-matrix) is the supported development
tuple. Pin that tuple for reproducible experiments. There is no published stable
release yet; `0.1.0-SNAPSHOT` can change and is intended for local development.

## Tested toolchain

See the [README compatibility matrix](../README.md#compatibility-matrix) for the
full tuple and host status. The website includes that same table below during
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
currently requires the exact tested runtime/compiler tuple and fails on drift.

The library ships one JVM JAR per supported Scala binary line, not Windows/Linux
variants. It packages SV text and schemas, not native simulator or compiler
binaries. Operating-system qualification concerns installation, compiler execution,
resource extraction, paths and simulation. There is no macOS claim until that
route actually runs and is reviewed.

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
new [tagged release workflow](../.github/workflows/release.yml) builds once and calls
that native workflow with the candidate artifact for an additional hash-bound
consumer check. It must run successfully before claiming public release support.

## Evidence

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
