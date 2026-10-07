# chisel-async

Typed asynchronous hardware components for Chisel: pipelines, routing, arbitration,
dual-rail logic, and explicit bridges to clocked designs. Apache-2.0 licensed and
independently implemented.

Use ordinary Chisel payloads, `IO`, `Flipped`, and `Module`. Asynchronous components
extend `RawModule` with explicit reset; clocked boundaries expose their clocks.
Select an electrical encoding with `Channel[T]`, then compose components using its
checked connection helpers.

**Pre-release:** the current version is `0.1.0-SNAPSHOT`, available through local
publication. There is no public Maven Central release yet. The library includes
digital simulation models and tested compiler exports; it does not supply mapped
physical cells or establish physical timing, QDI, or metastability closure.

## Start here

1. [Install and run the quickstart](docs/getting-started.md).
2. Learn [channels, handshakes, and reset](docs/concepts.md).
3. Choose from the [component catalog](docs/components.md).
4. [Test your design](docs/testing.md) and [export timing contracts](docs/timing-and-export.md).

The [documentation website](https://biscutlabs.github.io/chisel-async/) includes
integration guides, examples, troubleshooting, and the generated
[Scala API reference](https://biscutlabs.github.io/chisel-async/api/scala/).
The same guides remain available in the repository's [documentation index](docs/index.md).

Once a release is published, consumption will use a normal Maven Central dependency
without GitHub credentials or a custom resolver. For the locally published snapshot:

```scala
libraryDependencies += "io.github.biscutlabs" %% "chisel-async" % "0.1.0-SNAPSHOT"
```

Keep the matching Chisel compiler plugin in your project. The
[complete build and runnable project](examples/quickstart) show the required setup.
The library JAR packages its SystemVerilog models and schemas. Python, repository
scripts, and simulators are not JVM runtime dependencies; native tools are needed
for emission and simulation.

## Compatibility matrix

This is the **tested development configuration**, not a claim that unlisted
versions work. Strict validation enforces the listed Chisel/Scala/firtool tuple;
emission warns on drift and records the actual versions.

| Library | Scala | Chisel | Chisel compiler plugin | firtool | Java |
| --- | --- | --- | --- | --- | --- |
| `0.1.0-SNAPSHOT` | `2.13.18` | `7.16.0` | `7.16.0`, full Scala cross-version | `1.160.0` | JDK `21.0.12.1+1` tested |

| Tool or host | Tested configuration | Scope |
| --- | --- | --- |
| sbt | `1.12.4` | Build, local publication, consumer |
| Icarus Verilog | `13.0` | Event simulation, delays, four-state checks, export validation |
| Verilator | `5.046` | Clocked ChiselSim tests |
| Native Linux | Ubuntu `24.04`, Python `3.12.13` | Complete existing library campaign and clean-JAR consumer passed |
| Native Windows | Windows `2025`, Python `3.12.10`, MSYS2 UCRT64 | Same campaign; ChiselSim requires the documented build adapter |
| macOS | Deferred | No qualification claim |

The native rows refer to [recorded implementation evidence](docs/compatibility.md#evidence),
not an unexecuted run of every later documentation or packaging revision. See
[compatibility and versioning](docs/compatibility.md) for tool roles, Windows path
limits, release policy, and the distinction between JAR and compiler compatibility.

## What fits where

| Need | Components |
| --- | --- |
| Typed transform or pipeline storage | `FourPhaseStage[A, B]`, `LongHoldBuffer`, `FourPhaseFifo` |
| Broadcast, pairing, routing | `FourPhaseFork`, `FourPhaseRegFork`, `FourPhaseJoin`, controlled `FourPhaseMux`, `FourPhaseDemux`, exclusive `FourPhaseMerge` |
| Competing producers | `FourPhaseArbiter` and its finite digital MUTEX model |
| Transition-signalling interfaces | `TwoPhase` components and explicit phase converters |
| Return-to-zero dual-rail logic | Strong storage, bounded DIMS functions, fork/join, demux, exclusive merge |
| Clocked Chisel integration | `DecoupledToFourPhase`, `FourPhaseToDecoupled` |
| Memory transactions and events | `AsyncMemoryPort`, `PendingEventBridge` |
| Consumer async tests | `AsyncTest` in the JAR; ScalaTest plus Icarus, no Python |
| Digital timing and compiler inspection | `BundledTiming.Simulation`, primitive models, `ExportDesign` |
| ASIC integration | `AsicMapping`: explicit technology bindings; no supplied PDK or physical qualification |

`FourPhaseBuffer` is a behavioral reference model. New structural designs use the
long-hold family. See the [terminology and chisel-click comparison](docs/component-terminology.md)
for operation, storage, and implementation differences. Classes under `experimental` retain a known failing controller
for regression and must not be used in designs.

## Contributing

After installing the [platform prerequisites](docs/contributing.md#prerequisites),
run the complete repository campaign with:

```text
python tools/qualify.py
```

For normal library use, start with the quickstart instead. Contributor instructions
cover focused tests, failure diagnostics, and retained evidence. Historical plans,
reviews, and acceptance records are preserved in the [development archive](docs/archive/README.md)
and are no longer the user manual or an active roadmap.

Public releases will use **GitHub Actions → Maven Central**. GitHub Releases will
carry release notes and qualification bundles; GitHub Packages is optional for
authenticated previews. See [release and packaging policy](docs/releasing.md).

[License](LICENSE) · [Scientific and implementation provenance](docs/provenance.md)
