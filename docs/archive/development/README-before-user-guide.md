# chisel-async

> Historical development record. For current usage, read the [user documentation](../../index.md).

A Chisel library for asynchronous hardware, developed independently under Apache 2.0.

**Status: L0 and L1 closed for native Windows/Linux; the bounded CA-08 dual-rail family and CA-09 application boundaries are implemented and independently reviewed with passing native qualification.** `FourPhaseStage[A, B]` now uses the Furber–Day fully decoupled long-hold topology with explicit timing policies. Its [bounded digital campaign](long-hold-controller.md) checks full-handshake data hold, capacity, typed transforms and internal event order. The custom controller remains withdrawn. The [logical-channel layer, dual-rail storage/completion probe and explicit-clock bridges](logical-channels.md) now have executable evidence. The [frozen acceptance and fresh-context agent review](l0-acceptance.md) passed after repairing two export-validation gaps. Complete functional-release acceptance and public publication remain pending. macOS qualification is explicitly deferred.

The product order is chisel-async, RISCay-MCU, Chiselator, then physical chip implementation. This library works with an existing simulator and does not depend on Chiselator, Yosys, a PDK, ACT or a GPU.

The [adapter-closure repair and four-style adder reference](adapter-closure-and-reference.md) add explicit closure timing, seeded variable-resolution arbitration, and behavioral/bundled/DIMS/GALS integration tests to the one-command qualifier. The [frozen L1 candidate 2](l1-acceptance.md) passed native Windows/Linux acceptance and independent artifact review. The [CA-08 family](qdi-family.md) and [CA-09 application boundaries](application-boundaries.md) have separate passing native qualification; CA-10 packaging and complete functional release is next.

## What works now

- `AsyncModule`: `RawModule` with an explicit active-high `AsyncReset`, no implicit clock.
- `AsyncMemoryPort` and `PendingEventBridge`: explicit-clock request/response and event adapters. RAM/ROM examples reuse standard Chisel storage; commit/reset, byte masks and event-coalescing contracts have independent oracles and actual-RTL fault controls.
- `Channel[T]`: shared typed token intent and reset domain, with distinct bundled, dual-rail and standard Decoupled bindings; explicit clocked converters.
- `FourPhase[T]`: request/data toward the consumer, acknowledgement toward the producer. Supports sized UInt/SInt/Bool and nested Bundle/Vec payloads.
- `FourPhase.connect`: rejects incompatible shapes, implicit resizing and different reset-domain objects. Exported channels must share their owner's `ResetDomain`.
- `FourPhaseBuffer[T]`: one captured token, backpressure, stable output data through return to idle, and coordinated reset flushing.
- `FourPhaseStage[A, B]` / `LongHoldBuffer[T]`: published long-hold control through explicit primitive cells; type-changing transforms and required `BundledTiming` policy. Direct N-input/asymmetric C-element models preserve atomic input polarity.
- `FourPhaseFifo`, `InitialTokens`, `FourPhaseFork`, `FourPhaseJoin`, `FourPhaseSelect`, `FourPhaseMerge`: exact-depth storage, reset initialization, broadcast, typed pairing and exclusive routing. See the [composition contracts and executable examples](four-phase-composition.md).
- `DualRailStrongBuffer`, bounded `DualRailFunction[A,B]` tables, Boolean functions, full adder, fork, typed join, demultiplexer and exclusive merge: the [CA-08 RTZ dual-rail family](qdi-family.md), with explicit cell bounds and indication/fork/reset assumptions. Existing converters connect it to bundled and clocked designs.
- `CElement`: unanimity updates the output; disagreement holds state; reset forces zero. An external four-state diagnostic test checks unknown propagation.
- `Latch`, `DelayLine`, `ModelTime`: explicit reset, transparent storage, transport/inertial delay, captured values and reset cancellation, with exact integer femtoseconds.
- `TimedCapture[T]`: pure transform, independent data/control delays and a latch, with transaction identity and observed setup/hold checks.
- `ExportDesign`: versioned manifest, scoped semantic IDs, payload layouts, reset domains, primitive parameters/resources and timing obligations. Release optimization and deduplication are enabled by default. Read probes replace hardware observation ports; passive marker instances carry timing bounds and signal bindings. Actual RTL elaboration and active bit probes validate the endpoints.
- Packaged SV behavioral views, executable examples, Scala API tests, passive protocol monitors, independent token accounting and diagnostic-specific corrupted-model controls.

`FourPhaseBuffer` is a zero-delay **behavioral storage model**, not a hardware controller. The failed structural experiment lives under `chiselasync.experimental.UnsafeFourPhaseStage` / `UnsafeFourPhaseBuffer` solely for regression. The replacement has bounded digital evidence under stated atomic-cell, ideal-wire and bundling assumptions; no physical cell mapping is supplied. The small bundled/dual-rail/clocked examples exercise the shared API. [CA-07](arbitration-and-two-phase.md) adds arbitration, sequential two-phase counterparts and minimal mixed-encoding converters at the user's direction. The [L1 gate](l1-acceptance.md) is closed at its frozen candidate; each later family has separate qualification.

## Using the library versus qualifying the repository

There is no public release yet. A consumer of a locally published snapshot needs the matching Chisel/compiler-plugin setup and `libraryDependencies += "io.github.biscutlabs" %% "chisel-async" % "0.1.0-SNAPSHOT"`. Python and the qualification harness are not library runtime dependencies. Emission needs the compatible native firtool; simulation needs a backend supporting the chosen behavioral views. The [clean consumer](../../../verification/consumer) is an executable dependency example. Export defaults to the pinned optimized compiler route and remains fail-closed; arbitrary compiler configurations and downstream physical synthesis are unqualified. **Regenerate older exports:** the current resolver requires the v3 sidecar and its separately reflected `ports.json` type inventory. Earlier v3 exports also need regeneration to include the newly required whole-path and long-hold fork constraints.

For parent/child reset wiring, use `asyncChild("buffer")(domain => new FourPhaseBuffer(UInt(8.W), domain))` inside an `AsyncModule`. It passes the parent's domain, wires reset and registers the child contract. Separately constructed roots intentionally have separate domains. The command below is for contributors running the full qualification campaign.

The [CA-07 independent review and repairs](ca07-review.md) add protocol identity to port ABI v2 and require one constraint record per timing marker. Re-emit older `ports.json` inventories. Phase trace v2 checks per-boundary/per-epoch completion counts; the campaign adds eighteen directed source/reset cases and four `done` controls, for sixteen paired controls in total. Native results identify their source revision; [L1 candidate 2](l1-acceptance.md) closes the scoped review and acceptance gate.

## Build and test

Install **Python 3.12** and the platform prerequisites below, then run:

```text
python tools/qualify.py
```

The wrapper creates/reuses `.venv`, installs the hash-locked verification dependencies, installs the pinned JDK/firtool/sbt, configures paths for its child processes, emits every fixture, and runs all API, export, functional, timing, controller, architecture, optimized/debug comparison, composition, arbitration/two-phase/mixed-encoding, dual-rail truth/indication/sequence, ChiselSim and clean-consumer checks. No activation or manual `JAVA_HOME` is needed. It stops on the first failure and writes commands, status and logs to `target/verification/qualification`. A stale successful report cannot survive a failed preflight or run. Native CI uses this same command.

- **Windows:** install native MSYS2 UCRT64 Icarus 13, Verilator **5.046** ([pinned UCRT64 package](https://repo.msys2.org/mingw/ucrt64/mingw-w64-ucrt-x86_64-verilator-5.046-1-any.pkg.tar.zst)), and GCC (`mingw-w64-ucrt-x86_64-iverilog`, `mingw-w64-ucrt-x86_64-verilator`, `mingw-w64-ucrt-x86_64-gcc`), plus MSYS `make`. The wrapper finds `C:/msys64/ucrt64/bin`; use `--simulator-dir <directory>` for another installation. WSL is unnecessary for native Windows testing.
- **Linux:** install `autoconf gperf bison flex libfl-dev g++ make perl` (Debian/Ubuntu package names) if a pinned simulator build is needed. Verilator also needs Flex's development headers. The wrapper builds checksum-pinned Icarus 13 and Verilator 5.046 sources under `.tools` when no qualified simulator is available. It does not install system packages or invoke sudo.
- **macOS:** qualification remains explicitly deferred; the wrapper reports this rather than silently skipping a lane.

The tuple is JDK 21.0.12.1+1, Chisel 7.16.0, Scala 2.13.18, sbt 1.12.4, firtool 1.160.0, Icarus 13.0 and Verilator 5.046. CI pins CPython 3.12.10 on Windows and 3.12.13 on Linux; actual identities remain in reports. Tools install into ignored `.tools`, and the clean consumer publishes only to the local Ivy cache. Python and the verification harness are not library runtime dependencies.

`--no-setup` runs the same complete campaign using already installed dependencies and the calling Python interpreter. Individual runners remain available for focused debugging; see [timing/export](timing-and-export.md), [long-hold replay](long-hold-controller.md) [architecture replay](logical-channels.md) [composition replay](four-phase-composition.md) and [CA-07 replay](arbitration-and-two-phase.md). Missing tools, partial suites and unexpected fault diagnostics fail the run.

`tools/consumer_smoke.py` publishes to the local Ivy cache and creates a separate consumer project under `target/consumers`. It checks behavioral/withdrawn regression fixtures, long-hold buffering and type-changing transforms, packaged primitive models, timing tests and a short long-hold delay sweep with all fault controls. The proposed Maven coordinates are `io.github.biscutlabs:chisel-async_2.13:0.1.0-SNAPSHOT`; publication namespace ownership remains to be established.

## Scala-native simulation

Tests can use ScalaTest with `chisel3.simulator.scalatest.ChiselSim` and `simulate(...)`. See the [executable bridge tests](../../../verification/chiselsim/src/test/scala/chiselasync/BridgeSimulationSpec.scala). With a configured JDK/backend environment, run `python tools/sbt.py simulation/test`; on Linux with a configured toolchain, ordinary `sbt simulation/test` also works. The full wrapper additionally enforces the exact test inventory and activity markers.

Three positive tests cover both clocked bridge directions, 264 deliveries per direction with backpressure and a reset abort/restart, plus four 1024-bit transfers. Two actual harness payload corruptions must trigger the specified Scala oracle. The same tests run against the published JAR in the clean consumer. These are clocked digital tests; Icarus retains the asynchronous delay, four-state and independent protocol campaigns.

The pinned upstream svsim build needs a [small Windows build adapter](optimized-export-and-simulation.md#windows-build-adapter). It is applied automatically by `tools/sbt.py` for this lane. Simulator build paths must be free of spaces; clean-consumer ChiselSim outputs are deliberately placed outside the consumer's path with spaces, while its JAR compilation, exports and Icarus tests still run there.

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

Run `python tools/check_export.py generated` to resolve and validate the export. The emitted module has reset and input/output request/data/acknowledgement ports. Observation references are in `ref_<top>.sv`; they add no `ca_*` hardware ports. Assert reset with both external handshake drivers idle before transferring anything. Hold each payload through its complete handshake. See the [behavioral contracts](contracts.md), [timing/export contract](timing-and-export.md) and [tested examples](../../../examples/src/main/scala/chiselasync/examples/EmitFixtures.scala).

## Evidence and limits

The [CA-08 native qualification](qdi-family.md) passes 51 Scala tests, 487 Python tests and 77 default exports. Its 210-case rail campaign checks 117,930 deliveries and seven paired controls; 37 additional sequence cases check source return, pending offers, measured half-buffer chain capacity and reset accounting, with an actual-RTL reservation control. Both native artifacts and the clean-JAR replay pass independent review. This is bounded atomic-cell/ideal-wire evidence; physical QDI and the complete release remain separate.

The functional campaign requires 74 positive event tests and eight fault controls, including 22 new long-hold cases. The separate long-hold campaign requires 628 delayed cases, three activated faults, 5,184 primitive state/delay checks and 776 typed transfers. The architecture campaign adds 14 positive cases and four precise fault controls for completion and synchronizer latency. The expanded composition campaign requires 3,333 cases with 348,753 deliveries and ten exact negative controls (300 sampled per-cell configurations plus nominal and uniform cases per fixture); the published-JAR consumer repeats eleven nominal cases and all ten controls. The repaired CA-07 campaign passes 5,454 sweep cases / 908,080 deliveries plus eighteen directed cases / 4,210 deliveries and sixteen paired controls on native Windows/Linux. It checks per-epoch internal completion counts, partial-handshake resets, immediate source response and mixed-encoding round trips. Its JAR consumer repeats 54 sweep cases, all eighteen directed cases and all sixteen controls. See the [review and repair record](ca07-review.md). The timing campaign adds seven passing cases, two intended setup/hold violations and five corrupted-model controls. The compiler replication fixture checks eight parallel two-stage paths and 512 deliveries in both optimized and debug exports; 25 module definitions deduplicate to six with 256 independent endpoint references preserved. [CIRCT import tests](circt-import.md) cover the packaged scalar-delay syntax. Scala and Python checks cover API misuse, deterministic export, compiler corruption, exact time, independent reference models and harness failures. An unrelated assertion, crash or timeout cannot count as successful rejection.

Passive observers enforce handshake order and data hold while independent transaction accounting checks capacity, delivery and reset abortion. Tests include walking-one/walking-zero patterns for every payload bit, full-pipeline reset with a pending request, and completed post-reset transfers. Each single-buffer fixture runs 18 legal two-token orders with both equal and distinct payloads, 68 reset prefixes, and six coincident/one-picosecond boundary cases. The C-element checks 1,024 Boolean transitions. These are bounded functional experiments; see the [verification method and acceptance criteria](verification.md).

Reports, source/checker hashes, seeds, simulator identity, XML, logs and per-case traces/counters are retained under `target/verification`; timing traces use exact integer femtoseconds. Replay with `python verification/run.py` and `python verification/run_timing.py`. Select a functional fixture with `--fixture buffer`, or a timing experiment with `--job setup_equal`. The clean consumer gets separate evidence. See [qualification status](qualification.md) for exact versions and limits.

Compiler emission reports remaining `circt.VerbatimBlackBoxAnno` and `firrtl.transforms.DedupGroupAnnotation` warnings with this pinned tuple. They remain visible. The checked v3 route resolves read probes through the compiler ABI under release optimization/deduplication. Debug/no-dedup is a comparison mode and preserves the withdrawn controller’s historical delay experiments. This does not claim compatibility with arbitrary compiler transformations.

Read the [roadmap](roadmap.md), [contributor instructions](../../../AGENTS.md), and [provenance record](provenance.md). The repository's [Apache-2.0 license](../../../LICENSE) applies to our code; external tools retain their own licenses.

The [L0 acceptance record](l0-acceptance.md) closes the foundation gate at candidate 2 (`c85f97b`), with passing native Windows/Linux CI and three scoped fresh-context agent reviews. To replay `python verification/run_l0.py`, check out that frozen commit first. It intentionally rejects later execution-input changes, including CA-06. Current development uses `python tools/qualify.py`; a new acceptance gate needs its own frozen candidate.
