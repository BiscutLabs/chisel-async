# Timing intent and compiler export

Chisel-async exports your design's timing assumptions alongside its hardware.
The export validator checks that the supported compiler flow preserved declared
types, resources, endpoint bindings and constraints. Static timing analysis and
verification of mapped hardware are separate steps.

## Time and propagation models

`ModelTime(fs)` uses exact nonnegative signed 64-bit femtoseconds.
`ModelTime.ps(n)` converts picoseconds with overflow checking; `ticks(precision)`
rejects inexact conversion instead of rounding. Exported times use decimal strings
to avoid JSON floating-point precision loss. Event simulation uses 1 fs precision.

`DelayBounds(min, max, model)` separates the tested envelope from the nominal
emitted delay. All three use `ModelTime`; the model must fall within the bounds.
`DelayLine` requires positive delay. Its transport policy delivers each captured
input vector; inertial policy suppresses a candidate if another input arrives
before its deadline. A candidate due exactly when a new input arrives is delivered.
Reset clears output and cancels queued old-epoch deliveries; release schedules
the current input even if it has not changed.

`ClosingLatch` has zero internal model aperture and delayed output propagation.
That propagation value is not a closing-aperture estimate. `TimedCapture` is a
separate timing experiment: independently delayed data/control, a transaction ID,
and observed setup/hold inequalities. It cannot qualify a controller by itself.

## Required bounds and assumptions

| Policy or boundary | Requirement |
| --- | --- |
| Bundled admission | `matchedDelay > dataDelay.max` |
| Bundled output offer | `outputDelay > 2 * controls.worst + latchDelay.max` |
| Phase return | `returnDelay > cells.max` |
| Four-to-two history closure | `requestDelay > historyClosure.max`, including distribution/skew/aperture allowance |
| Dual-rail decode admission | `matchedDelay > phase.cells.max + dataDelay.max` |
| QDI model envelope | Independent positive cell bounds, atomic cells, ideal forks, monotonic RTZ, coordinated reset |

The long-hold output-acknowledgement fork additionally requires acknowledgement to
reach the hold OR before state A falls there. Whole-path records include transform
logic, select decoding, merge selection/payload muxes, and initial-token muxing.
These obligations matter even where RTL glue evaluates with zero simulation delay.

Constructors reject invalid policies. The validator checks consistency between
policies, declared constraints, marker instances and actual primitive parameters.
Supply characterized physical bounds when mapping your design; increasing
guards cannot compensate for every control hazard or incorrect cell decomposition.

## Export workflow

Use ordinary Chisel elaboration for normal hardware workflows. For a registered
`AsyncModule` root and a checked contract, call:

```scala
ExportDesign.emit(new MyDesign, java.nio.file.Paths.get("generated"))
```

`MyDesign` stands for your root class; the runnable
[quickstart](../examples/quickstart/src/main/scala/Quickstart.scala) is a complete
example. The default mode is `ExportDesign.Optimized` (release optimization and
deduplication). `ExportDesign.Debug` is an explicit comparison mode using
debug/no-dedup options. Later compiler or synthesis transformations need their own
checks to ensure they preserve the recorded assumptions.

Register public channels with `contract.channel`, `twoPhaseChannel`,
`dualRailChannel` or `clockedChannel`, as appropriate. Use `asyncChild` for nested
async modules. Custom low-level primitives and timing paths require explicit
registry entries too; unregistered instances are rejected by strict validation.
For exact registration signatures see
[`DesignContract`](../src/main/scala/chiselasync/metadata/DesignContract.scala).

| Output | Purpose |
| --- | --- |
| SystemVerilog and `filelist.f` | Emitted design and packaged model sources |
| `ref_<top>.sv` | Compiler read-probe ABI for observation, without extra `ca_*` hardware ports |
| `ports.json` | Port ABI v2: independently reflected payload types, directions and protocol identity |
| `contract.json` | Contract v3: hierarchy, reset domains, capacities, primitives, timing intent and hashes |
| `design.hw.mlir` | Retained compiler IR for the supported lowering and inspection |
| `resolved.json` | Produced by successful validation, not by emission alone |

With repository Python dependencies and Icarus available, run from the repository:

```text
python tools/check_export.py /absolute/path/to/generated
```

The checker validates schemas and cross-references, then elaborates emitted RTL
to check actual instances, parameters, ports and resource hashes. Active bit probes
compare endpoint bindings and reset wiring, requiring both polarities on each
observed bit. These forced probes test compiler mapping only; functional campaigns
run the original design without mapping forces.

The semantic identity normalizes supported source formatting and excludes absolute
checkout paths. Exact file/checker hashes are separately recorded in evidence.
Do not edit generated files and keep an old success report. Re-emit and revalidate
after a design, model, compiler or schema change.

## Compiler scope

Strict export validation requires Chisel 7.16.0, Scala 2.13.18 and firtool 1.160.0.
Emission itself warns and records actual versions on drift. Use
`ExportDesign.emit(..., qualifiedOnly = true)` to reject drift at emission too.
Use the tested versions when you need a validated export.
The exact options are defined in
[`ExportDesign`](../src/main/scala/chiselasync/metadata/ExportDesign.scala).
Legacy contract/port ABI inventories must be regenerated for the current checker.

Timing markers are passive instances wired to constrained signals with declared
parameters. They preserve intent through the tested optimization/deduplication
route. A downstream synthesis flow must consume or preserve these constraints
before removing marker cells. Sidecar names alone are not a physical constraint flow.

`contract.synchronousMemory` supports the pinned compiler's tested single masked
`SyncReadMem` read/write-port lowering. It checks identity, array/port shape and
metadata, not arbitrary memory equivalence. Other memory lowerings are not covered.

Remaining compiler annotation warnings are visible in test logs. Unsupported
reference forms fail instead of being guessed. No arbitrary CIRCT importer,
downstream synthesis equivalence or physical timing closure is supplied. The
[ASIC mapping interface](asic-mapping.md) emits a separate synthesis file list
once all technology primitives have explicit bindings; it does not supply a PDK.
