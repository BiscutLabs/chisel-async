# Standalone chisel-async quickstart

This directory is a separate sbt project that consumes the released
library JAR. It does not depend on the parent source project.

Follow the [getting-started guide](../../docs/getting-started.md) for prerequisites
and RC1 installation from GitHub or local publication. With the downloaded Maven
ZIP, add its `maven` directory as a resolver in this project's `build.sbt`, as
shown in the guide. From this directory, with the compatible toolchain:

```text
sbt "runMain EmitQuickstart"
sbt "testOnly AsyncDesignSpec"
```

Emission builds a two-stage typed adder. `AsyncDesignSpec` tests the adder and
GCD using the JAR helper and Icarus (`iverilog`/`vvp` on PATH), with no Python.
`RoutingSpec` runs 300 configurations per mux/fork; `AsicMappingSpec` checks the
technology binding interface. `sbt test` also runs a ChiselSim bridge test, which
needs Verilator; on native Windows, that bridge test uses the
[documented simulation adapter](../../docs/testing.md#native-windows-chiselsim).
The `0.1.0-RC1` dependency is distributed on GitHub, not Maven Central.

## Native Click example

The [Click adder walkthrough](../../docs/click-example.md) combines a standard
Click transform with a phase-decoupled FIFO. It preserves a transaction tag and
the addition carry, using typed port helpers and named constructor arguments.
From this directory:

```text
sbt "runMain EmitClickAdder"
sbt "testOnly ClickAdderSpec"
```

The test checks 44 jobs under 64 per-cell delay configurations with backpressure.
`ClickTestSpec` provides broader controller, reset and timing-fault coverage.
Both use Icarus directly from ScalaTest; neither needs Python or Verilator.
The simulation timing preset does not represent a characterized hardware target.
