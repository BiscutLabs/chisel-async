# ASIC cell-mapping interface

`AsicMapping` produces a synthesis input set using **explicit technology bindings**.
It is an interface for integrating your cell library, not a supplied PDK or a
claim of physical closure. Ordinary `ExportDesign` output contains simulation
models; never send that file list to synthesis and rely on `#delay` being ignored.

## Prepare and bind

```scala
import chiselasync.metadata.AsicMapping
import java.nio.file.Paths

val plan = AsicMapping.prepare(new MyDesign, Paths.get("build/mapping"))
// plan.required lists exact model/parameter keys, port widths, and every instance.
// Supply a reviewed technology adapter for EACH listed key.
val bindings: Seq[AsicMapping.Binding] = loadMyTechnologyBindings(plan.required)
val output = plan.emit(bindings, Seq(Paths.get("technology/async_cells.v")))
```

`MyDesign` and `loadMyTechnologyBindings` are project-specific. Inspect
`required-cells.json`; do not fabricate a binding by copying a simulation model
under another module name. Each `Binding` provides the exact `Key`, technology
module name, a map from every logical port to its technology pin, and a provenance
description identifying the implementation and characterization. Technology
adapters have fixed ports for that specialization; they may instantiate the
actual library macro internally. Supply all required RTL/black-box declarations.

Unmapped or extra keys, duplicate keys, incomplete/repeated pin maps, missing
source modules, changed prepared inputs, and file-name collisions fail. Width,
inversion, reset, delay and policy parameters participate in the key. Distinct
delay requirements cannot accidentally share a binding through a model-name-only
lookup. The output directory must be new.

The output `asic/filelist.f` includes ordinary design RTL, generated cell wrappers,
and your technology sources. It excludes the library's behavioral cell bodies
and read-probe modules. Wrappers retain primitive boundaries and request hierarchy
preservation; apply the equivalent preservation constraints in your synthesis tool.
An unsupported parameter specialization instantiates a deliberately unresolved
module instead of falling back to simulation logic.

`mapping.json` records bindings, provenance and file hashes, with status
`mapped-unqualified`. `timing-intent.json` preserves the original contract.
Passive timing/QDI marker instances remain available for extraction before
synthesis removes them. Simulation protocol guards become empty diagnostics in
this separate synthesis view. Do not mix simulation and ASIC file lists.

## Technology responsibilities

| Cell or path | What your implementation must establish |
| --- | --- |
| Symmetric/asymmetric C-element | Atomic state-holding behavior, reset polarity/value, input bubbles and hazard assumptions; arbitrary Boolean decomposition is insufficient |
| Latch | Transparent/closed polarity, reset, setup/hold, closing aperture and propagation across operating corners |
| Matched delay | Minimum control delay exceeds the corresponding maximum mapped data path under process, voltage, temperature and load |
| Data-delay model | Replace the modeling allowance with the actual transform/glue path; do not add the modeled delay again blindly |
| MUTEX | Metastability containment, grant exclusion and supported request protocol; finite randomized simulation is not a macro implementation |
| Toggle and other control cells | Event/reset semantics and propagation assumptions in the selected protocol |
| Wires/forks | Long-hold acknowledgement fork ordering and applicable isochronic-fork assumptions |

The interface cannot infer these properties from Verilog syntax or a provenance
string. No Liberty, LEF, SDC generation, synthesis/P&R run, extracted-delay
simulation, or physical equivalence proof is included. Complete those with the
chosen technology before using the design as hardware.

The consumer [mapping test](../examples/quickstart/src/test/scala/AsicMappingSpec.scala)
uses deliberately labeled black-box test cells to check binding completeness,
model exclusion and elaboration under `SYNTHESIS`. Those cells are not usable
technology implementations. The digital test helper remains useful before and
alongside this separate physical flow.
