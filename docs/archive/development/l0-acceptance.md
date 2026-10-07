# L0 acceptance: Windows and Linux

> Historical development record. For current usage, read the [user documentation](../../index.md).

L0 is the CA-01–05 foundation gate: pinned native tools, protocol/reference contracts, typed API and export, primitive views, and a complete one-entry example consumed from the JAR. It does not approve the full library catalog, physical timing, arbitrary synthesis, QDI or metastability behavior. macOS qualification remains explicitly deferred by the October 5 platform decision.

## Candidate and prospective campaign

Before executing this acceptance, `qualification/l0-candidate-2.json` was created with `python verification/run_l0.py --freeze` and committed. It now exists for replay; a future changed candidate needs a new manifest name and prospectively declared campaign. Freezing records normalized-LF SHA-256 hashes of every Git-visible source, resource, example, test, checker, tool, build/project and CI input. It refuses to overwrite an existing candidate. Documentation can record results afterwards without changing the tested source identity.

Run `python verification/run_l0.py` with the README prerequisites, or manually dispatch the Library qualification workflow with `l0=true`. This runs the complete one-command qualification first, including local publication and the unrelated consumer. It then executes the published long-hold stage at depths 1, 2, 3 and 4 with seeds 10064–10127 (256 configurations), two uniform cases per depth and both polarities of six role corners per depth (56 cases). All 312 cases must pass. The three existing faults must fail specifically for payload mismatch, data hold and capacity respectively. Missing cases, duplicate cases, nonprogress, unrelated failures or source drift invalidate acceptance.

The custom deterministic PRNG and parameter mapping are frozen with the checker sources. Each cell role has an independent 1–10 ns digital delay; environment pauses span 1–60 ns. Bounds must satisfy the emitted timing policy. Each case checks 49 deliveries, 47 completed output returns, seven reset scenarios, conservation, capacity, full-handshake data hold and the independent published event graph. The established topology, primitive, typed-payload and fault checks are also repeated.

The seeds and depths are selected before this acceptance run. For candidate 2, all 56 uniform/corner cases at depths 1–4 are deliberate regression replays from candidate 1; only the 256 new seed/depth configurations are fresh. This is fresh input coverage on a known topology, driver and oracle, not an independent implementation, calibrated physical distribution, statistical reliability bound or proof over arbitrary delays. Retain the original development corpus and withdrawn-controller counterexample.

Each attempt gets a new directory under `target/verification/l0`; failed attempts are retained. A required failure is not cured by retrying until green. Fixes require review, a new named candidate committed before rerunning, and an explicit supersession record. CI uploads the aggregate report, source identities, commands, per-case configuration/logs and selected waveforms.

## Candidate 1: automated pass, superseded by review

Candidate 1 is frozen at commit `eb814564ff0fadc4ca4320cb2c10f071964ba4a4`, before acceptance execution. It binds 102 execution inputs; the normalized candidate manifest SHA-256 is `13aa8b78d9c31a944c061b478c4804d019d1c71f442e08b5660db7fd942e7833`. Its native Windows/Linux workflow is [run 37418977069](https://github.com/BiscutLabs/chisel-async/actions/runs/37418977069).

| Host | Candidate 1 result |
| --- | --- |
| Local native Windows 11, CPython 3.12.13 | PASS: complete baseline, 312 acceptance cases, three exact fault detections; source identities unchanged. |
| Native Windows Server 2025, CPython 3.12.10 | PASS: complete baseline, 312 cases and three exact fault detections. |
| Native Ubuntu 24.04, CPython 3.12.13 | PASS: complete baseline (including cold builds of both simulators), 312 cases and three exact fault detections. |

Both CI artifacts were downloaded and checked: candidate and campaign digests match, required baseline lanes are complete, and all 312 case summaries (status, token counts and STG event counts) agree with the local run. No acceptance attempt failed or required a retry. Windows evidence is under `20261006T053229Z-nybykl_7`; Linux evidence is under `20261006T053212Z-vkxukna6` within the CI artifacts.

The local attempt is retained at `target/verification/l0/20261006T053140Z-8vl433q0`. The complete baseline includes 174 Python checks, 28 Scala API checks, 29 validated exports, five ChiselSim cases and the published-JAR consumer, alongside the existing functional/timing/controller/architecture campaigns. The 312 acceptance cases add 15,288 checked deliveries per host. The 256 fresh random configurations account for 12,544 of those deliveries; neither count represents independent statistical trials.

**Candidate 1 did not close L0.** The [fresh-context agent reviews](l0-review.md) passed the controller and recorded verification evidence but found two blocking export-validation gaps. Its original automated results and manifest remain retained; they are not retroactively relabelled as a successful review.

## Candidate 2: repaired native acceptance

The v3 typed-port export and channel-association fixes, their corruption tests, and improved consumer XML retention require a new candidate. The prospective campaign uses fresh seeds 10064–10127 at depths 1–4, with the same declared uniform/corner inventory, activity and fault criteria. Candidate 2 was frozen and committed before execution at `c85f97b731b782a0f5c5d5ac4f1b81e99a4a505d`. Its manifest binds 103 execution inputs with normalized SHA-256 `c41289da1ff1c5a0e1016f115ef8bdfd7a64b85d317835d3a4aed44f1f6b2d83`. [Native run 37421591012](https://github.com/BiscutLabs/chisel-async/actions/runs/37421591012) passes both platforms at that exact commit.

| Host | Candidate 2 result and retained attempt |
| --- | --- |
| Local native Windows 11, CPython 3.12.13 | PASS: `20261006T060230Z-o6zsy_mw`. |
| Native Windows Server 2025, CPython 3.12.10 | PASS: `20261006T060318Z-roh8ao0m`, artifact `evidence-windows-2025`. |
| Native Ubuntu 24.04, CPython 3.12.13 | PASS: `20261006T060311Z-v9rd0i6z`, artifact `evidence-ubuntu-24.04`. |

Each run includes 188 Python checks, 29 Scala checks, all 29 exports, the complete functional/timing/controller/architecture baseline, five ChiselSim cases and the published-JAR consumer. Each additional acceptance campaign passes all 312 cases / 15,288 deliveries, three exact fault detections, 5,184 primitive checks and 776 typed transfers. The clean consumer's five-case ChiselSim XML is now retained and hash-checked too. No candidate 2 acceptance attempt failed or required a retry.

Both downloaded CI artifacts match the frozen candidate and all 312 local case summaries; the source inventory is unchanged. The normalized campaign-report digests are `c00e648bc41c60e031565d2ede452dd816691f86c17cfa11cd895bd06e166275` (Windows) and `20d1d6a397648575cce8e4402a248af330cc362c81a849d120eb94435fd330ac` (Linux). Host paths and provenance differ, so aggregate report hashes need not match.

## Closure decision

**L0 / CA-01–05 is closed for native Windows and Linux on October 5, 2026 (Pacific).** Candidate 2 passes the prospective campaign and the three scoped fresh-context agent reviews. The controller review remains applicable because the controller, driver and reference behavior did not change; the export reviewer independently confirmed the repairs; the verification reviewer approved the repaired candidate after auditing both native artifacts. Candidate 1 remains superseded.

The final audit replayed 222,258 external channel edges and 15,288 deliveries per host with a separate queue/reservation ledger, checked published-graph transitions, and revalidated baseline/consumer traces, timing evidence and ChiselSim XML. It also rejected a one-bit payload mutation in a copy of a raw log while the original summaries stayed unchanged. All 29 qualification exports have identical semantic and typed-port ABI hashes across native hosts. The [review record](l0-review.md) preserves scope, findings and audit identities.

This historical closure permits starting CA-06; it does not qualify the full catalog or a public release. Begin with the four-phase FIFO capacity and initial-token/reset contract, then implementation and independent occupancy/order/backpressure tests. Preserve the existing campaigns and add compact guard-edge/long-held-request regressions when composition grows. macOS, physical timing, arbitrary downstream synthesis, full QDI/arbitration and analog metastability qualification remain outside this closure.

## Review map

| Criterion | Implementation and independent evidence | Review question |
| --- | --- | --- |
| CA-01 native foundation | Pinned build/bootstrap, `tools/qualify.py`, CI host reports, native Icarus and ChiselSim | Do required tools, empty suites, setup failures and stale output fail closed? |
| CA-02 contracts | `contracts.md`, `trace-format.md`, `reference.py`, `timing_reference.py`, published graph in `longhold_reference.py` | Do state tables, repeated values, reset abortion and delivery points agree without copying DUT equations? |
| CA-03 API/export | `protocol/Payload.scala`, `core/AsyncModule.scala`, `metadata/ExportDesign.scala`, `tools/check_export.py`, optimized replication/corruption tests | Are nested layouts, instance identity, reset bindings and timing intent still checked after deduplication? |
| CA-04 primitives | Packaged versioned SV models, `longhold_primitives.py`, timing queue oracle and boundary/fault tests | Are state history, reset, inertial/transport policy, atomic input polarity and exact time explicit? |
| CA-05 complete example | `bundled/FourPhaseStage.scala`, external passive ledger/STG observers, typed transforms, `tools/consumer_smoke.py` | Does the one-entry full-handshake contract hold under stalls, reset, bounded delays and publication? |

The implementation-side audit checked the added guard against the published topology: after A rises, latch closure and input acknowledgement traverse the long-hold OR and acknowledgement cell. The output guard exceeds twice the largest control bound plus latch propagation, conservatively covering both acceptance and payload settling under ideal wires and zero latch aperture. The matched admission guard exceeds the maximum modeled transform/data delay. This reasoning depends on the documented atomic-cell and coordinated-reset assumptions; it is not a substitute for independent review or physical characterization.

Oracle provenance is linked in [provenance.md](provenance.md), [verification.md](verification.md) and [long-hold-controller.md](long-hold-controller.md). Functional token accounting, timing inequalities/queue behavior and the published event graph use distinct behavioral code from the DUT. Driver, checker and DUT still share authorship, assumptions and schema, so correlated mistakes remain possible. Any delegated agent review must be identified as such; no external human or specialist certification has been obtained in this closeout attempt.

CA-06 is now implemented in a later revision. Replay this L0 campaign by checking out its frozen candidate commit before running `python verification/run_l0.py`; current development inputs correctly fail its source-identity check. Use `python tools/qualify.py` for current regression evidence. A new L1 acceptance must freeze its own candidate and cases.
