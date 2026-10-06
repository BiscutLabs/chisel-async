# Prospective L1 acceptance

L1 remains open until the independent review decision and native Windows/Linux acceptance are complete. This record freezes a bounded digital experiment for CA-06 composition, CA-07 phase/arbitration, history closure, the DIMS arithmetic core and the four-style mixed-encoding reference. It does not establish physical timing, QDI implementation, analog metastability behavior, fairness, a reliability probability or macOS qualification.

The review starts at `15ca6f004eceab83985fe0ffdbd6043181f92981`; the preceding production implementation is `1116bf211ffd1534eaef06e8250652bf686ae1a4`. The [plan](../verification/l1-plan.json) records that baseline's 140 execution inputs and 34 export semantic/typed-port/probe identities. Later review repairs are bound by a separate committed candidate manifest. Its `source_revision` identifies the committed implementation, checker, acceptance harness and CI inputs immediately before the candidate manifest is committed. The executing report also records the actual candidate commit. Neither development evidence nor machinery tests are an acceptance attempt.

## Frozen inventory

The four new seeds are **41003, 41018, 41041 and 41060**. They include both phase-reset warm-up parities and lie outside the inspected development ranges: composition/phase 0–302, reference 0–32, DIMS 0/2/3/17/91 and MUTEX 1–32 plus the unsigned boundary seeds. These are fresh configurations of known fixtures, traffic generators and oracles, not independently authored implementations or statistical trials. Existing directed schedules and controls are explicitly replays.

| Lane | Required positive inventory | Required activity and controls |
| --- | --- | --- |
| Composition | All eleven fixtures × four held-out seeds = 44 | Exact per-fixture deliveries; seven or nine resets; raw ledger replay; ten exact controls |
| Phase/mixed encoding | All eighteen fixtures × four seeds = 72; eighteen directed replay cases | Three reset epochs, both completion polarities, per-channel/epoch completion witnesses, exact delivery totals and required reset-state witnesses; sixteen baseline/mutant control pairs |
| Four-style reference | Behavioral, bundled, DIMS pipeline and GALS × four seeds = 16 | 192 arithmetic results per case, internal boundary activity, stalled-capacity/reset abortion and four wrong-result controls |
| History closure | 101 declared regression cases plus eight new parameter cases | 22 transfers and six reset windows per case; guard-removal and pre-toggle controls |
| DIMS core | Five declared regression configurations plus four new seeds | 9,222 deliveries each: exhaustive 16-word × 24-arrival × 24-spacer order coverage plus six reset-restart deliveries; two exact controls |
| Random MUTEX | Four new seeds × two global-RNG-noise variants = eight | 48 tie choices and over 100 committed decisions per variant, exact reset reproducibility/noise independence, both winners in three arrival modes, at least 60 distinct latencies across the campaign; a real constant-resolution mutant must fail latency coverage |

The total is **276 positive cases**, **35 diagnostic-specific controls**, and sixteen additional positive finite-prefix companions for phase controls. The eight new closure cases use 3/7/17/23 ns closure paths, independently chosen toggle/history/XOR delays and a strict one-femtosecond guard margin. They are deliberately reparameterized sensitivity experiments, including closure values beyond the default 1–10 ns fixture bounds. Normal composition/phase delay samples stay within their declared 1–10 ns bounds; phase MUTEX sensitivity uses a maximum resolution of 20 ns. The primitive MUTEX experiment uses integer femtosecond resolution 10–100. Atomic cells, ideal wires and documented reset assumptions still apply.

## Execution and decision

Commit the repaired implementation, harness, tests, plan and CI integration first. Freeze a new manifest without executing:

```text
python verification/l1_acceptance.py --freeze --candidate qualification/l1-candidate-1.json
```

Commit that manifest, run the complete development qualifier at that candidate revision, then execute with the qualified virtual-environment Python:

```text
.venv/Scripts/python.exe verification/l1_acceptance.py --candidate qualification/l1-candidate-1.json --output target/l1-acceptance/native-windows-attempt-1
.venv/bin/python verification/l1_acceptance.py --candidate qualification/l1-candidate-1.json --output target/l1-acceptance/native-linux-attempt-1
```

The output directory must not exist. Every failed attempt remains retained; a retry does not erase a failure or turn it into a pass. Candidate execution inputs, including CI and the acceptance plan, must match the committed manifest before and after execution. The manifest itself cannot be overwritten by `--freeze`. Repairs after an acceptance failure require a new named candidate, prospective replacement inputs where the failed run exposed them, and an explicit supersession decision.

The harness copies the 34 frozen exports into each private attempt directory before invoking any checker. This keeps active mapping probes and simulation files away from the shared generated exports. Native Icarus 13.0 is required; missing tools, disabled Python assertions, nonzero exits, stale output, empty/partial/duplicate inventories, missing activity, wrong control diagnostics and changed source/bench/trace/log/XML hashes all fail closed. Aggregate `PASS` strings alone never satisfy acceptance. Composition, phase and reference traces are replayed and compared with exact planned activity; closure, DIMS and primitive arbitration require their explicit completion markers and exact negative diagnostics. The final artifact inventory retains file hashes for subsequent independent audit.

The machinery tests use synthetic reports/logs and corruption cases, without consuming held-out simulations. Full development qualification and clean-JAR replay remain separate required evidence at the same candidate source state. Acceptance does not close L1 automatically: separate scoped review, an audit of both native artifacts, and a recorded decision are required. No official candidate has been executed when this prospective plan is first introduced.
