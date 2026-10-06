# L0 acceptance: Windows and Linux

L0 is the CA-01–05 foundation gate: pinned native tools, protocol/reference contracts, typed API and export, primitive views, and a complete one-entry example consumed from the JAR. It does not approve the full library catalog, physical timing, arbitrary synthesis, QDI or metastability behavior. macOS qualification remains explicitly deferred by the October 5 platform decision.

## Candidate and prospective campaign

Before executing acceptance, create and commit `qualification/l0-candidate-1.json` with `python verification/run_l0.py --freeze`. Freezing records normalized-LF SHA-256 hashes of every Git-visible source, resource, example, test, checker, tool, build/project and CI input. It refuses to overwrite an existing candidate. Documentation can record results afterwards without changing the tested source identity.

Run `python verification/run_l0.py` with the README prerequisites, or manually dispatch the Library qualification workflow with `l0=true`. This runs the complete one-command qualification first, including local publication and the unrelated consumer. It then executes the published long-hold stage at depths 1, 2, 3 and 4 with seeds 10000–10063 (256 configurations), two uniform cases per depth and both polarities of six role corners per depth (56 cases). All 312 cases must pass. The three existing faults must fail specifically for payload mismatch, data hold and capacity respectively. Missing cases, duplicate cases, nonprogress, unrelated failures or source drift invalidate acceptance.

The custom deterministic PRNG and parameter mapping are frozen with the checker sources. Each cell role has an independent 1–10 ns digital delay; environment pauses span 1–60 ns. Bounds must satisfy the emitted timing policy. Each case checks 49 deliveries, 47 completed output returns, seven reset scenarios, conservation, capacity, full-handshake data hold and the independent published event graph. The established topology, primitive, typed-payload and fault checks are also repeated.

The seeds and depths are selected before this acceptance run. Existing uniform/corner cases at depths 1 and 3 are deliberate regression replays; depths 2 and 4 extend composition coverage. This is fresh input coverage on a known topology, driver and oracle, not an independent implementation, calibrated physical distribution, statistical reliability bound or proof over arbitrary delays. Retain the original development corpus and withdrawn-controller counterexample.

Each attempt gets a new directory under `target/verification/l0`; failed attempts are retained. A required failure is not cured by retrying until green. Fixes require review, a new named candidate committed before rerunning, and an explicit supersession record. CI uploads the aggregate report, source identities, commands, per-case configuration/logs and selected waveforms.

## Decision

**Pending:** freeze and execute the candidate, and record independent review of controller/timing assumptions, reset/accounting, compiler/export preservation and oracle provenance. Passing automation alone does not close the review gate. CA-06 remains gated until that decision is recorded. The next implementation item after closure is the four-phase FIFO and initial-token contract.
