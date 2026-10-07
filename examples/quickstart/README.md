# Standalone chisel-async quickstart

This directory is a separate sbt project that consumes the locally published
library JAR. It does not depend on the parent source project.

Follow the [getting-started guide](../../docs/getting-started.md) for prerequisites
and local publication. From this directory, with the compatible toolchain:

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
The library is not yet publicly released; the snapshot dependency must exist in
your local Ivy cache.

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
