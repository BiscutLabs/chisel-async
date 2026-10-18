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
| Native Click | Independent cell bounds, setup/hold, pulse widths and trigger distribution; see [Click timing](click.md#primitives-and-timing) |

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
The `AsyncModule` four-phase and two-phase port helpers register their channels
automatically; do not register those same ports a second time.
For exact registration signatures see
[`DesignContract`](../src/main/scala/chiselasync/metadata/DesignContract.scala).

| Output | Purpose |
| --- | --- |
| SystemVerilog and `filelist.f` | Emitted design and packaged model sources |
| `ref_<top>.sv` | Compiler read-probe ABI for observation, without extra `ca_*` hardware ports |
| `ports.json` | Port ABI v2: independently reflected payload types, directions and protocol identity |
| `contract.json` | Contract v3: hierarchy, reset domains, capacities, primitives, timing intent and hashes |
| `design.hw.mlir` | Retained compiler IR for the supported lowering and inspection |
| `structure.json` | Generation audit: primitive inventory, driven values and periodic-clock reachability |
| `resolved.json` | Produced by successful validation, not by emission alone |

`ExportDesign.emit` runs `StructureAudit` on the typed HW IR before publishing
the contract. It checks the registered native primitive paths, models, parameters
and ports; rejects missing drivers and unknown value-producing operations; and
rejects a combinational path from a top-level `Clock` input to any native storage
input, including transparent-latch data. Clock-free registered owners cannot
contain ordinary clocked registers. Clocked crossings are explicit modules with
clock inputs; their sequential Q outputs end combinational propagation.

Clock roots propagate through hierarchy and gates. A child's `Clock` type alone
does not reclassify a native event as periodic. The audit does not infer periodic
behavior from a divider's Q or a Boolean input: clock generators must remain
explicit integration boundaries, with their periodic outputs exposed as clock
inputs to the audited design. Opaque external modules conservatively connect all
inputs to all outputs for reachability. Their internals remain an integration
obligation. Output-free compiler assertion observers are accepted only through a
closed diagnostic vocabulary; arbitrary Verilog text and functional side effects
are rejected.

These checks use the pinned CIRCT HW/Comb/Seq vocabulary. An unsupported producer
fails generation and needs a reviewed extension, rather than a guessed driver.
They do not replace the dynamic checker below, protocol simulations, reset-domain
crossing analysis or physical timing. Protected mapped cells, reviewed keeper-arc
cuts and unused added cells are checked after technology mapping; generation
cannot claim results for transformations that have not happened.

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

## Additive export validators

Python extension API **v1** supports resolved endpoint/slice references and extra
validators. This is a supported **source-distributed Python API**, separate from
the Scala JAR. Obtain the complete repository at a pinned Git commit (or a release
tag containing the API), and put that checkout's `tools` directory on `PYTHONPATH`.
Keep its `tools`, `verification` and resources together; copying just two Python
files is not a supported distribution. It is not currently a PyPI package or part
of the Maven artifact. Record the source commit and checker hashes with results.

Import `check_export` and `export_extensions`, then pass validators and an explicit
`extension_api_version=1` to `validate_export`. A nonempty validator list without
that version is rejected. This API version is independent of contract v3 and port
ABI v2; no emitted schema migration is required. Incompatible API changes require
a new API version and migration notes; the version does not pin implementation
bytes, so consumers still pin the repository revision.

Without validators, the checker retains its existing validation path and result
fields. It does not resolve extension references or compute extension coverage.
Existing core rejection rules also remain: an empty probe ABI fails with
`EMPTY_PROBE_ABI`, even though the manifest schema permits no endpoints. Schema
acceptance alone is not full export validation. With validators, the additional
required-inventory calculation rejects empty coverage explicitly; extra checks
cannot turn it into coverage of a design.

For the exported `PipelineExample` fixture, this checks the lower four input bits
against the first child's input and inspects the compiled child's input-port shape:

```python
from pathlib import Path
from check_export import validate_export
from export_extensions import EndpointEquality, EndpointSelector, ExportValidator

def first_input_port(context):
    endpoint = context.endpoint(("first",), "in_data")
    port = context.scope(("first",))["ports"]["in_bits"]
    return endpoint.width == 8 and port == {
        "name": "in_bits", "direction": "input", "width": 8
    }

result = validate_export(
    Path("target/generated/pipeline"),
    extension_api_version=1,
    validators=[
        EndpointEquality(
            "FIRST_INPUT_BINDING",
            EndpointSelector((), "in_data", lsb=0, width=4),
            EndpointSelector(("first",), "in_data", lsb=0, width=4),
        ),
        ExportValidator("FIRST_INPUT_PORT", first_input_port),
    ],
)
```

An instance selector is a tuple of registered **child IDs**, not generated module
names; `()` selects the root. Compiler deduplication may share module definitions
without merging these identities. `context.endpoint(instance, id)` returns the
resolved RTL path, endpoint width, instance path and actual compiled module name.
Its `slice(lsb, width)` method returns a checked packed slice. Omitting a selector's
width selects the remainder of the endpoint starting at `lsb`.
`context.scope(instance)` exposes a read-only compiled scope with port, net,
register, parameter and memory inventories. `context.contracts[instance]` exposes
the read-only registered contract. These observations do not infer arbitrary RTL
connectivity or prove physical timing.

`EndpointEquality` adds a read-only comparison at every existing mapping-probe
sample. The references must resolve, slices must fit, widths must match, and an
equality comparing the same resolved slice to itself is rejected. No raw Verilog,
additional forcing, stimulus backgrounds or clock/reset scenarios are accepted.
An equality failure reports `EXPORT_EXTENSION_FAILED:<diagnostic_id>` in both the
checker error and the simulator's precise fatal location. This checks the sampled
mapping relation, not functional equivalence over all circuit states.

`ExportValidator` runs after all mandatory mapping probes and equality checks pass.
It must return exactly `True` or `False`; truthy non-booleans are rejected. False
reports `EXPORT_EXTENSION_FAILED:<diagnostic_id>`; an exception reports
`EXPORT_EXTENSION_ERROR:<diagnostic_id>` with its cause retained. Diagnostic IDs
must be unique uppercase identifiers of at most 96 characters. Unknown API
versions, references and validator types fail closed.

When validators are supplied, the library computes the required endpoint and
both-polarity inventory independently of their declarations. `resolved.json` reports it under
`required_coverage`; `extension_validation` separately records API version,
validator IDs, comparison expressions and check counts. Extra successes cannot
replace a missing mandatory check or inactive endpoint bit. The existing
`mapping_checks` field remains the mandatory count. The required bit-polarity
count is an obligation discharged by the mandatory probe's success; it is not
reported as a separately measured observed count. Callback results cannot edit
the probe plan or coverage, and callbacks receive a fresh, detached read-only
snapshot. Input and probe evidence hashes are checked again after callbacks.

Callbacks execute trusted local Python; the API is not a security sandbox. Record
the downstream validation script and its hash alongside a project's evidence.
Do not mutate or monkey-patch the checker from callbacks. Structural reset-crossing
and valid-qualified-use audits, new probe backgrounds and clock/reset scenarios
are outside v1. They require separate contracts and tests before becoming public
extension points.

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
before removing marker cells. Use [mapped timing checks](asic-mapping.md#check-the-mapped-timing-paths)
to bind supported obligations to actual pins, generate SDC and test strict relative
ordering with OpenSTA. Sidecar names alone are not a physical constraint flow.

`contract.synchronousMemory` supports the pinned compiler's tested single masked
`SyncReadMem` read/write-port lowering. It checks identity, array/port shape and
metadata, not arbitrary memory equivalence. Other memory lowerings are not covered.

Remaining compiler annotation warnings are visible in test logs. Unsupported
reference forms fail instead of being guessed. No arbitrary CIRCT importer,
downstream synthesis equivalence or physical timing closure is supplied. The
[ASIC mapping interface](asic-mapping.md) emits a separate synthesis file list
once all technology primitives have explicit bindings; it does not supply a PDK.
