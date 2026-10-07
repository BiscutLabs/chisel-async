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
