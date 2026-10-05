# chisel-async

A Chisel library for asynchronous hardware, developed independently under Apache 2.0.

**Status: functional and digital timing foundation, not the complete library.** Typed four-phase channels, a behavioral buffer, C-element, latch, captured-value delay models, and a checked compiler export run on native Windows. Linux and macOS CI is configured; results on those hosts remain pending.

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
- Packaged SV behavioral views, executable examples, Scala API tests, passive protocol monitors, independent token accounting and six deliberately corrupted-model controls.

The buffer uses a zero-delay **behavioral storage model**. `TimedCapture` separately exercises declared digital delays; it is not a handshake controller. Structural controllers, physical delay matching, independent-reset bridges, two-phase, QDI, arbitration and memories remain in the [roadmap](docs/roadmap.md).

## Build and test

Use JDK 21, Python 3.12 and Icarus Verilog 13.0. The library pins Chisel 7.16.0, Scala 2.13.18, sbt 1.12.4 and firtool 1.160.0. These scripts run from PowerShell or a Unix shell; Python must be at least 3.12 for bootstrap extraction. They install checked compiler/build artifacts only into the ignored `.tools` directory. Maven dependencies resolve normally through sbt.

```text
python -m venv .venv
```

Activate with `.venv\Scripts\Activate.ps1` on Windows or `source .venv/bin/activate` on macOS/Linux. Set `JAVA_HOME` to your JDK if it is not the default Java installation.

```text
python -m pip install --require-hashes -r verification/requirements.txt
python tools/bootstrap.py
python tools/sbt.py --bootstrap test "examples/runMain chiselasync.examples.EmitFixtures target/generated"
python tools/check_export.py
python -m pytest verification/test_runner.py verification/test_reference.py verification/test_timing_reference.py verification/test_timing_runner.py verification/test_export.py -q
python verification/run.py
python verification/run_timing.py
python tools/consumer_smoke.py
```

For native Windows simulation, install `mingw-w64-ucrt-x86_64-iverilog` in an [MSYS2 UCRT64 environment](https://www.msys2.org/) and add its `ucrt64/bin` directory to PATH in the shell running Python. This runs Windows executables and does not require WSL. On Linux/macOS, install the build dependencies listed in the CI workflow, run `python tools/build_iverilog.py`, then add `.tools/iverilog/bin` to PATH. The runner checks the engine version rather than silently using another simulator.

`tools/consumer_smoke.py` publishes to the local Ivy cache, creates a separate consumer project under `target/consumers`, and runs its buffer, latch, delays and timing fixtures through the same export/event checks. The proposed Maven coordinates are `io.github.biscutlabs:chisel-async_2.13:0.1.0-SNAPSHOT`; publication namespace ownership remains to be established.

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

The native Windows functional campaign retains its 24 positive event tests and six fault controls. The timing campaign adds seven passing cases, two intended setup/hold violations and five corrupted-model controls. Scala and Python checks cover API misuse, deterministic export, compiler corruption, exact time, independent reference models and harness failures. An unrelated assertion, crash or timeout cannot count as successful rejection.

Passive observers enforce handshake order and data hold while independent transaction accounting checks capacity, delivery and reset abortion. Tests include walking-one/walking-zero patterns for every payload bit, full-pipeline reset with a pending request, and completed post-reset transfers. Each single-buffer fixture runs 18 legal two-token orders with both equal and distinct payloads, 68 reset prefixes, and six coincident/one-picosecond boundary cases. The C-element checks 1,024 Boolean transitions. These are bounded functional experiments; see the [verification method and acceptance criteria](docs/verification.md).

Reports, source/checker hashes, seeds, simulator identity, XML, logs and per-case traces/counters are retained under `target/verification`; timing traces use exact integer femtoseconds. Replay with `python verification/run.py` and `python verification/run_timing.py`. Select a functional fixture with `--fixture buffer`, or a timing experiment with `--job setup_equal`. The clean consumer gets separate evidence. See [qualification status](docs/qualification.md) for exact versions and limits.

Compiler emission reports remaining `circt.VerbatimBlackBoxAnno` and `firrtl.transforms.DedupGroupAnnotation` warnings with this pinned tuple. They remain visible. The checked sidecar route qualifies explicit retained ports under the documented debug/no-dedup options; it does not rely on those annotations surviving or claim compatibility with arbitrary compiler transformations.

Read the [roadmap](docs/roadmap.md), [contributor instructions](AGENTS.md), and [provenance record](docs/provenance.md). The repository's [Apache-2.0 license](LICENSE) applies to our code; external tools retain their own licenses.
