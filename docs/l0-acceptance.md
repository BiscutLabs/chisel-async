# L0 acceptance: Windows and Linux

L0 is the CA-01–05 foundation gate: pinned native tools, protocol/reference contracts, typed API and export, primitive views, and a complete one-entry example consumed from the JAR. It does not approve the full library catalog, physical timing, arbitrary synthesis, QDI or metastability behavior. macOS qualification remains explicitly deferred by the October 5 platform decision.

## Candidate and prospective campaign

Before executing acceptance, create and commit `qualification/l0-candidate-1.json` with `python verification/run_l0.py --freeze`. Freezing records normalized-LF SHA-256 hashes of every Git-visible source, resource, example, test, checker, tool, build/project and CI input. It refuses to overwrite an existing candidate. Documentation can record results afterwards without changing the tested source identity.

Run `python verification/run_l0.py` with the README prerequisites, or manually dispatch the Library qualification workflow with `l0=true`. This runs the complete one-command qualification first, including local publication and the unrelated consumer. It then executes the published long-hold stage at depths 1, 2, 3 and 4 with seeds 10000–10063 (256 configurations), two uniform cases per depth and both polarities of six role corners per depth (56 cases). All 312 cases must pass. The three existing faults must fail specifically for payload mismatch, data hold and capacity respectively. Missing cases, duplicate cases, nonprogress, unrelated failures or source drift invalidate acceptance.

The custom deterministic PRNG and parameter mapping are frozen with the checker sources. Each cell role has an independent 1–10 ns digital delay; environment pauses span 1–60 ns. Bounds must satisfy the emitted timing policy. Each case checks 49 deliveries, 47 completed output returns, seven reset scenarios, conservation, capacity, full-handshake data hold and the independent published event graph. The established topology, primitive, typed-payload and fault checks are also repeated.

The seeds and depths are selected before this acceptance run. Existing uniform/corner cases at depths 1 and 3 are deliberate regression replays; depths 2 and 4 extend composition coverage. This is fresh input coverage on a known topology, driver and oracle, not an independent implementation, calibrated physical distribution, statistical reliability bound or proof over arbitrary delays. Retain the original development corpus and withdrawn-controller counterexample.

Each attempt gets a new directory under `target/verification/l0`; failed attempts are retained. A required failure is not cured by retrying until green. Fixes require review, a new named candidate committed before rerunning, and an explicit supersession record. CI uploads the aggregate report, source identities, commands, per-case configuration/logs and selected waveforms.

## Decision

Candidate 1 is frozen at commit `eb814564ff0fadc4ca4320cb2c10f071964ba4a4`, before acceptance execution. It binds 102 execution inputs; the normalized candidate manifest SHA-256 is `13aa8b78d9c31a944c061b478c4804d019d1c71f442e08b5660db7fd942e7833`. Its native Windows/Linux workflow is [run 37418977069](https://github.com/BiscutLabs/chisel-async/actions/runs/37418977069).

| Host | Candidate 1 result |
| --- | --- |
| Local native Windows 11, CPython 3.12.13 | PASS: complete baseline, 312 acceptance cases, three exact fault detections; source identities unchanged. |
| Native Windows Server 2025, CPython 3.12.10 | PASS: complete baseline, 312 cases and three exact fault detections. |
| Native Ubuntu 24.04, CPython 3.12.13 | PASS: complete baseline (including cold builds of both simulators), 312 cases and three exact fault detections. |

Both CI artifacts were downloaded and checked: candidate and campaign digests match, required baseline lanes are complete, and all 312 case summaries (status, token counts and STG event counts) agree with the local run. No acceptance attempt failed or required a retry. Windows evidence is under `20261006T053229Z-nybykl_7`; Linux evidence is under `20261006T053212Z-vkxukna6` within the CI artifacts.

The local attempt is retained at `target/verification/l0/20261006T053140Z-8vl433q0`. The complete baseline includes 174 Python checks, 28 Scala API checks, 29 validated exports, five ChiselSim cases and the published-JAR consumer, alongside the existing functional/timing/controller/architecture campaigns. The 312 acceptance cases add 15,288 checked deliveries per host. The 256 fresh random configurations account for 12,544 of those deliveries; neither count represents independent statistical trials.

**Automated acceptance passed; L0 remains open for independent review.** The tested candidate has not yet received independent sign-off. Required review covers controller/timing assumptions, reset/accounting, compiler/export preservation and oracle provenance. Passing automation alone does not close the review gate. CA-06 remains gated until that decision is recorded. The next implementation item after closure is the four-phase FIFO and initial-token contract.

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
