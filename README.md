# chisel-async

A Chisel library for asynchronous hardware, developed independently under Apache 2.0.

**Status: controller redesign required before library expansion.** The custom structural stage is withdrawn. The new [published-controller comparison](docs/controller-comparison.md) passes 300 random-delay cases for each Muller reference depth on Windows and Linux-under-WSL, while rejecting the withdrawn design in 254/300 cases. Muller has different capacity and data-validity semantics; it is not the production replacement. See the [review response and revised priorities](docs/review-response.md). macOS qualification is explicitly deferred.

The product order is chisel-async, RISCay-MCU, Chiselator, then physical chip implementation. This library works with an existing simulator and does not depend on Chiselator, Yosys, a PDK, ACT or a GPU.

## What works now

- `AsyncModule`: `RawModule` with an explicit active-high `AsyncReset`, no implicit clock.
- `FourPhase[T]`: request/data toward the consumer, acknowledgement toward the producer. Supports sized UInt/SInt/Bool and nested Bundle/Vec payloads.
- `FourPhase.connect`: rejects incompatible shapes, implicit resizing and different reset-domain objects. Exported channels must share their owner's `ResetDomain`.
- `FourPhaseBuffer[T]`: one captured token, backpressure, stable output data through return to idle, and coordinated reset flushing.
- `CElement`: unanimity updates the output; disagreement holds state; reset forces zero. An external four-state diagnostic test checks unknown propagation.
- `Latch`, `DelayLine`, `ModelTime`: explicit reset, transparent storage, transport/inertial delay, captured values and reset cancellation, with exact integer femtoseconds.
- `TimedCapture[T]`: pure transform, independent data/control delays and a latch, with transaction identity and observed setup/hold checks.
- `ExportDesign`: versioned manifest, scoped semantic IDs, payload layouts, reset domains, primitive parameters/resources and timing obligations. Actual RTL elaboration and active bit probes validate the retained endpoints.
- Packaged SV behavioral views, executable examples, Scala API tests, passive protocol monitors, independent token accounting and eight deliberately corrupted-model controls.

`FourPhaseBuffer` is a zero-delay **behavioral storage model**, not a hardware controller. The failed structural experiment now lives under `chiselasync.experimental.UnsafeFourPhaseStage` / `UnsafeFourPhaseBuffer` solely for regression. `TimedCapture` separately exercises declared digital delays; it cannot repair controller races. Published-controller comparison and small bundled/QDI/clocked architecture examples precede catalog expansion in the revised [roadmap](docs/roadmap.md).

## Using the library versus qualifying the repository

There is no public release yet. A consumer of a locally published snapshot needs the matching Chisel/compiler-plugin setup and `libraryDependencies += "io.github.biscutlabs" %% "chisel-async" % "0.1.0-SNAPSHOT"`. Python and the qualification harness are not library runtime dependencies. Emission needs the compatible native firtool; simulation needs a backend supporting the chosen behavioral views. The [clean consumer](verification/consumer) is an executable dependency example. Qualified export remains pinned and fail-closed; this is not an optimized production-netlist path.

For parent/child reset wiring, use `asyncChild("buffer")(domain => new FourPhaseBuffer(UInt(8.W), domain))` inside an `AsyncModule`. It passes the parent's domain, wires reset and registers the child contract. Separately constructed roots intentionally have separate domains. The commands below are for contributors running the full qualification campaign; a single-command setup/qualification wrapper remains planned.

## Build and test

Use JDK 21, Python 3.12 and Icarus Verilog 13.0. The library pins Chisel 7.16.0, Scala 2.13.18, sbt 1.12.4 and firtool 1.160.0. These scripts run from PowerShell or a Unix shell; Python must be at least 3.12 for bootstrap extraction. They install checked compiler/build artifacts only into the ignored `.tools` directory. Maven dependencies resolve normally through sbt.

```text
python -m venv .venv
```

Activate with `.venv\Scripts\Activate.ps1` on Windows or `source .venv/bin/activate` on macOS/Linux. Set `JAVA_HOME` to your JDK if it is not the default Java installation.

```text
python -m pip install --require-hashes -r verification/requirements.txt
python tools/bootstrap_jdk.py
python tools/bootstrap.py
python tools/sbt.py --bootstrap test "examples/runMain chiselasync.examples.EmitFixtures target/generated"
python tools/sbt.py "examples/runMain chiselasync.examples.EmitControllerComparison target/generated/comparison_unsafe"
python tools/check_export.py
python -m pytest verification/test_runner.py verification/test_reference.py verification/test_timing_reference.py verification/test_timing_runner.py verification/test_export.py verification/test_controller_comparison.py -q
python verification/run.py
python verification/controller_race.py
python verification/compare_controllers.py
python verification/run_timing.py
python tools/consumer_smoke.py
```

`bootstrap_jdk.py` verifies the exact Temurin 21.0.12.1+1 archive and installs it under `.tools/jdk21`. Outside CI, set `JAVA_HOME` to `.tools/jdk21/jdk-21.0.12.1+1` afterward. It supports Windows/Linux x86-64; macOS setup is deferred. CI pins CPython 3.12.10 on Windows and 3.12.13 on Linux because setup-python has no Windows binary for 3.12.13. Reports retain actual interpreter identities.

For native Windows simulation, install `mingw-w64-ucrt-x86_64-iverilog` in an [MSYS2 UCRT64 environment](https://www.msys2.org/) and add its `ucrt64/bin` directory to PATH in the shell running Python. This runs Windows executables and does not require WSL. On Linux, install the build dependencies listed in the CI workflow, run `python tools/build_iverilog.py`, then add `.tools/iverilog/bin` to PATH. The runner checks the engine version rather than silently using another simulator.

`tools/consumer_smoke.py` publishes to the local Ivy cache, creates a separate consumer project under `target/consumers`, and runs its behavioral buffer, structural buffer/transform, latch, delays and timing fixtures through the same export/event checks. The proposed Maven coordinates are `io.github.biscutlabs:chisel-async_2.13:0.1.0-SNAPSHOT`; publication namespace ownership remains to be established.

## A clockless buffer

```scala
import chisel3._
import chiselasync.bundled.FourPhaseBuffer
import chiselasync.metadata.ExportDesign
import java.nio.file.Paths

class Example extends FourPhaseBuffer(UInt(8.W))

object EmitExample {
  def main(args: Array[String]): Unit =
    ExportDesign.emit(new Example, Paths.get("generated"))
}
```

Run `python tools/check_export.py generated` to resolve and validate the export. The emitted module has reset, input/output request/data/acknowledgement, and retained `ca_*` observation ports. Assert reset with both external handshake drivers idle before transferring anything. Hold each payload through its complete handshake. See the [behavioral contracts](docs/contracts.md), [timing/export contract](docs/timing-and-export.md) and [tested examples](examples/src/main/scala/chiselasync/examples/EmitFixtures.scala).

## Evidence and limits

The expanded functional campaign requires 52 positive event tests and eight fault controls. The timing campaign adds seven passing cases, two intended setup/hold violations and five corrupted-model controls. Scala and Python checks cover API misuse, deterministic export, compiler corruption, exact time, independent reference models and harness failures. An unrelated assertion, crash or timeout cannot count as successful rejection.

Passive observers enforce handshake order and data hold while independent transaction accounting checks capacity, delivery and reset abortion. Tests include walking-one/walking-zero patterns for every payload bit, full-pipeline reset with a pending request, and completed post-reset transfers. Each single-buffer fixture runs 18 legal two-token orders with both equal and distinct payloads, 68 reset prefixes, and six coincident/one-picosecond boundary cases. The C-element checks 1,024 Boolean transitions. These are bounded functional experiments; see the [verification method and acceptance criteria](docs/verification.md).

Reports, source/checker hashes, seeds, simulator identity, XML, logs and per-case traces/counters are retained under `target/verification`; timing traces use exact integer femtoseconds. Replay with `python verification/run.py` and `python verification/run_timing.py`. Select a functional fixture with `--fixture buffer`, or a timing experiment with `--job setup_equal`. The clean consumer gets separate evidence. See [qualification status](docs/qualification.md) for exact versions and limits.

Compiler emission reports remaining `circt.VerbatimBlackBoxAnno` and `firrtl.transforms.DedupGroupAnnotation` warnings with this pinned tuple. They remain visible. The checked sidecar route qualifies explicit retained ports under the documented debug/no-dedup options; it does not rely on those annotations surviving or claim compatibility with arbitrary compiler transformations.

Read the [roadmap](docs/roadmap.md), [contributor instructions](AGENTS.md), and [provenance record](docs/provenance.md). The repository's [Apache-2.0 license](LICENSE) applies to our code; external tools retain their own licenses.
