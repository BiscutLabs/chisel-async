# Standalone chisel-async quickstart

This directory is a separate sbt project that consumes the locally published
library JAR. It does not depend on the parent source project.

Follow the [getting-started guide](../../docs/getting-started.md) for prerequisites
and local publication. From this directory, with the compatible toolchain:

```text
sbt "runMain EmitQuickstart"
sbt test
```

Emission builds a two-stage typed adder. The ScalaTest test exercises a clocked
bridge with stalls and repeated payloads. On native Windows, use the
[documented simulation adapter](../../docs/testing.md#native-windows-chiselsim).
The library is not yet publicly released; the snapshot dependency must exist in
your local Ivy cache.
