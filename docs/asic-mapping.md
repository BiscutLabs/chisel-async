# ASIC cell-mapping interface

Use `AsicMapping` to connect chisel-async primitives to your technology's cells and
generate a separate set of synthesis inputs. You supply the cell implementations
and verify their physical timing. The optional [GF180 reference](gf180-reference.md)
supplies trial delay/latch/gate adapters and identifies the cells still needed;
it is not a complete PDK backend.
Ordinary `ExportDesign` output uses simulation models whose `#delay` statements
cannot implement the required hardware delays.

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

Replace `MyDesign` and `loadMyTechnologyBindings` with your own design and binding
loader. Use `required-cells.json` to identify the cells you need. Each binding
must use a technology implementation that meets the listed requirements. Each
`Binding` provides the exact `Key`, technology module name, a map from every logical
port to its technology pin, and a provenance
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

The mapping interface checks that bindings are complete; verifying these physical
properties is part of your technology flow. That flow must provide Liberty and
LEF data, synthesis constraints, synthesis and place-and-route, extracted-delay
simulation and physical equivalence checks. These steps are outside `AsicMapping`.

The consumer [mapping test](../examples/quickstart/src/test/scala/AsicMappingSpec.scala)
uses deliberately labeled black-box test cells to check binding completeness,
model exclusion and elaboration under `SYNTHESIS`. Those cells are not usable
technology implementations. The digital test helper remains useful before and
alongside this separate physical flow.

## Check the mapped timing paths

`TimingConstraints` translates supported obligations into SDC path bounds,
preservation rules and executable OpenSTA checks. Prepare it from the ASIC export:

```scala
import chiselasync.metadata.{TimingConstraints, OpenSta}
import java.nio.file.Paths

val timing = TimingConstraints.prepare(Paths.get("build/mapping/asic/timing-intent.json"))
// Review timing.required, timing.rules and timing.orderings.
// Bind every endpoint bit to its exact mapped pin or top-level port.
val constraints = timing.emit(myMappedEndpoints, Paths.get("build/constraints"))
val corner = OpenSta.Corner("ss",
  Seq(Paths.get("technology/ss.lib")), Paths.get("mapped.v"), Paths.get("corner.tcl"),
  spef = Some(Paths.get("routed.spef")))
OpenSta.check(constraints, corner, Paths.get("build/sta-ss"))
```

`myMappedEndpoints` is a `Map[String, Seq[TimingConstraints.ObjectRef]]` keyed by
`timing.required` IDs. For example, a scalar binding can contain
`ObjectRef("pin", "add/request_chain/I")`; a bus has one exact reference per bit.
Bind state-cell arc endpoints to the characterized macro's actual pins, rather
than wrapper ports. Names are checked against the linked netlist. Missing or extra
bindings, absent bus bits, unresolved paths/arcs, unsupported obligation kinds,
changed generated files and incomplete tool results fail.

| Generated file | Use |
| --- | --- |
| `preserve.tcl` | Preserve registered cell boundaries before synthesis optimization; adapt `set_dont_touch` to your implementation tool if needed |
| `constraints.sdc` | Apply minimum/maximum combinational path requirements |
| `check-timing.tcl` | Check measured path/characterized-cell bounds and strict relative ordering |
| `constraints.json` | Retain semantic IDs, exact bindings, obligation inventory and file hashes |

The current lowering covers long-hold control/latch bounds, complete transform and
glue-path budgets, the acknowledgement fork, and phase-conversion guards. QDI
fork obligations and encoding-converter obligations do not yet have a lowering;
they fail with `UNSUPPORTED_TIMING_OBLIGATION`. Functional-only zero-delay policies
are rejected. Four-to-two checks require an explicit `closureMargins` entry for
each adapter ordering, accounting for characterized closure/setup time not already
included in the bound. A zero entry is still an explicit engineering decision.

`corner.tcl` establishes operating assumptions, input slew, loads, case analysis
and any reviewed arc cuts. Run each required PVT corner in a fresh process. The
runner records all supplied input hashes, logs and checked IDs; a successful exit
without the complete evidence inventory fails. Configure another executable with
`command = Seq("/path/to/sta")`. OpenSTA remains optional and external to the JAR.

A result marked `CHECKED_DECLARED_PATHS` covers those supplied paths and that
corner. Without SPEF it is cell-only analysis. It does not establish reset
recovery, pulse widths, latch setup/hold, analog state-cell behavior, hazard
freedom, or arbitrary unrecorded wire constraints. The technology flow must verify
those separately. In particular, a Liberty propagation arc alone does not qualify
a C-element or MUTEX. The checker is tested with OpenSTA 2.7.0 using known-delay
paths and deliberate missing-bit, bound and ordering failures.

Review the parasitic-annotation report when supplying SPEF; the runner does not
certify extraction coverage. Tied-off/disconnected endpoint bits and state paths
without usable characterized arcs are rejected rather than counted as zero delay.
