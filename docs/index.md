# chisel-async documentation

Start with a working project, then choose components and verification appropriate
to your design. These guides describe the current API and its limits. They do not
require reading the project's development history.

## Learn and build

| Guide | What you will learn |
| --- | --- |
| [Getting started](getting-started.md) | Install the snapshot, emit a typed pipeline, run a first Scala test |
| [Concepts](concepts.md) | Tokens, encodings, backpressure, acceptance, delivery, and reset |
| [Component catalog](components.md) | What each public component does and when to use it |
| [Terminology and chisel-click comparison](component-terminology.md) | Established names, matching operations, and differences in storage and implementation |
| [Bundled-data composition](bundled-data.md) | Timing policy, type-changing stages, FIFO, fork/join, routing and arbitration |
| [Dual-rail logic](dual-rail.md) | Rails, completion, indication, bounded DIMS functions, and conversion |
| [Clocked integration](clocked-integration.md) | Decoupled bridges, memory backends, pending events, and reset release |
| [Examples](examples.md) | Runnable designs and the properties their tests exercise |

## Verify and integrate

| Guide | What you will learn |
| --- | --- |
| [Testing](testing.md) | ScalaTest/ChiselSim, event simulation, independent oracles, reset and negative controls |
| [Protocol contracts](contracts.md) | Exact transfer and hold obligations at each interface |
| [Timing and export](timing-and-export.md) | Delay bounds, strict inequalities, compiler configuration, metadata and validation |
| [ASIC mapping](asic-mapping.md) | Bind every primitive to a technology adapter and emit a separate synthesis input set |
| [Trace formats](trace-format.md) | Interpret retained observations without confusing campaign formats |
| [Compatibility](compatibility.md) | Tested versions/hosts, version policy and known limitations |
| [Troubleshooting](troubleshooting.md) | Resolve dependency, reset, simulation and export failures |

## Maintain and release

[Contributing](contributing.md) covers setup and focused verification.
[Releasing](releasing.md) defines JAR packaging and GitHub Actions/Maven Central
distribution. [Scientific references](provenance.md) explain the circuit topologies
and model assumptions. [The archive](archive/README.md) preserves plans, reviews, counterexamples,
and historical acceptance results for auditing.

For exact constructor signatures, browse the linked Scala sources or generate
Scaladoc with `sbt doc` (`target/scala-2.13/api/index.html`). The sources and API-doc
JARs accompany the binary artifact. Browse the hosted
[Scala API](https://biscutlabs.github.io/chisel-async/api/scala/) alongside these
guides. [Website development](website.md) explains how to build and preview both.
