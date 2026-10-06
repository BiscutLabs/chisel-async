# L1 acceptance: candidate 2 accepted

**L1 is closed for native Windows/Linux at candidate 2, `b430180aefef3c51b755851fd24f28a1127d3aa4`.** Scoped fresh-context review, full same-candidate qualification, frozen acceptance and independent native artifact audits pass. This bounded digital gate covers CA-06 composition, CA-07 phase/arbitration, history closure, the DIMS arithmetic core and the four-style mixed-encoding reference. It does not establish physical timing, QDI implementation, analog metastability behavior, fairness, a reliability probability or macOS qualification. Later CA-08 work has its own qualification and does not expand this historical candidate.

The review starts at `15ca6f004eceab83985fe0ffdbd6043181f92981`; the preceding production implementation is `1116bf211ffd1534eaef06e8250652bf686ae1a4`. The [candidate 2 plan](../verification/l1-plan-2.json) preserves the [original plan's](../verification/l1-plan.json) 140 baseline execution inputs and 34 export semantic/typed-port/probe identities. Later review repairs are bound by a separate committed candidate manifest. Its `source_revision` identifies the committed implementation, checker, acceptance harness and CI inputs immediately before the candidate manifest is committed. The executing report also records the actual candidate commit. Neither development evidence nor machinery tests are an acceptance attempt.

## Final decision, October 6, 2026

[Native run 37521932760](https://github.com/BiscutLabs/chisel-async/actions/runs/37521932760) passes on Windows Server 2025 / Python 3.12.10 and Ubuntu 24.04 / Python 3.12.13. Each host passes the complete qualifier: 44 Scala tests, 400 Python tests, 63 exports, all preceding campaigns, 51 clean-consumer exports and five main plus five consumer ChiselSim tests. The frozen acceptance then passes all **276 positives, 35 exact controls and sixteen additional phase companions**. Fresh arbitration samples exercise 90 distinct latencies, exceeding the planned minimum of 60. Native Windows 11 / Python 3.12.13 also passes the same candidate locally.

Independent artifact audits verify 146 frozen execution inputs, all 34 copied acceptance exports with complete source, deterministic bench/source bindings, raw trace replay and all 4,751 final-inventory hashes per host. All 115 baseline and 34 acceptance semantic/probe/typed-port identities agree across native hosts, as do semantic case records. The repaired upload retains every required baseline source: there are no source-retention gaps in candidate 2. The combined audit is `target/native-l1-candidate2/complete-candidate2-audit.json`, SHA-256 `6a2c57ba5a29127f7ff70698ceb8000da2c6616925893950237770c51d4534dd`.

The [control and export review](l1-review.md), repaired machinery review and complete audited native evidence support accepting candidate 2 for this scope. These are scoped agent reviews, not external human/specialist certification. Candidate 1 remains rejected and its failure is retained below. The next library family may proceed; physical qualification, macOS and the complete functional-release gate remain separate.

## Candidate 1: failed acceptance, retained

Both native attempts in official [run 37516750333](https://github.com/BiscutLabs/chisel-async/actions/runs/37516750333) ended with acceptance **ERROR** at `L1_MUTEX_GLOBAL_RNG_INTERFERENCE`. The noise-independence comparison included Icarus's terminal source-location record. Its per-case paths differed (`41003_0/bench.sv` versus `41003_1/bench.sv`) even though the audited decision and timing records agreed. Both full development qualifiers passed. Candidate 1's [manifest](../qualification/l1-candidate-1.json), original plan and failed evidence remain immutable. This failure is not relabelled as a pass.

The independent cross-host audit confirms 268 completed regular positives, two completed MUTEX positives, 34 exact controls and sixteen phase companions per host. Six MUTEX positives and the constant-resolution control were not reached, and the official final artifact inventory was never written. The 34 copied acceptance exports retain full source evidence; private post-download inventories are explicitly distinguished from official results. The audit is `target/native-l1/complete-candidate1-audit.json`, SHA-256 `8ced719aa380cf115261c750268fbbc8c5b48e61551c3ab922e648c0b8f96b19`. It confirms the narrow harness defect and does not turn incomplete acceptance into a pass.

Candidate 2 repairs that comparison by replacing only the exact known per-case bench path in the terminal `$finish` record. The line number, finish time, units, other terminal content and every preceding log character remain significant. Raw logs and their hashes are unchanged. Downloaded-artifact audits obtain the original host's bench path from the recorded compile command and continue to hash the locally retained bench and log bytes. Synthetic regressions cover Windows/POSIX paths, relocated artifacts, decision/timing changes, changed finish records and raw-log corruption.

The repair passes 64 machinery checks. A separate native Windows 11 / Icarus 13.0 development check uses previously available seeds 1–4, each with and without global RNG noise: eight cases, 384 choices, all 91 latency values, and the exact constant-resolution control pass both execution and raw-evidence audit. Its evidence is retained under `target/l1-acceptance/mutex-path-repair-development-1`. This checks real Windows path formatting without executing candidate 2's held-out inputs.

The replacement plan selected unexecuted seeds and new closure parameters because candidate 1 exposed its acceptance inputs. The repaired execution inputs were committed at `fa8fc4c8b5c25d2f07175bfd4b2d3e21f5c36b0f`; candidate 2 was then frozen and committed at `b430180aefef3c51b755851fd24f28a1127d3aa4` before its first acceptance execution. CI also retains complete generated SystemVerilog and file lists for both the main exports and the clean consumer, alongside their contracts and ABI evidence.

## Frozen inventory

The four candidate 2 seeds are **41411, 41428, 41443 and 41470**. They include both phase-reset warm-up parities and lie outside candidate 1's 41003/41018/41041/41060 and the inspected development ranges: composition/phase 0–302, reference 0–32, DIMS 0/2/3/17/91 and MUTEX 1–32 plus the unsigned boundary seeds. These are fresh configurations of known fixtures, traffic generators and oracles, not independently authored implementations or statistical trials. Existing directed schedules and controls are explicitly replays.

| Lane | Required positive inventory | Required activity and controls |
| --- | --- | --- |
| Composition | All eleven fixtures × four held-out seeds = 44 | Exact per-fixture deliveries; seven or nine resets; raw ledger replay; ten exact controls |
| Phase/mixed encoding | All eighteen fixtures × four seeds = 72; eighteen directed replay cases | Three reset epochs, both completion polarities, per-channel/epoch completion witnesses, exact delivery totals and required reset-state witnesses; sixteen baseline/mutant control pairs |
| Four-style reference | Behavioral, bundled, DIMS pipeline and GALS × four seeds = 16 | 192 arithmetic results per case, internal boundary activity, stalled-capacity/reset abortion and four wrong-result controls |
| History closure | 101 declared regression cases plus eight new parameter cases | 22 transfers and six reset windows per case; guard-removal and pre-toggle controls |
| DIMS core | Five declared regression configurations plus four new seeds | 9,222 deliveries each: exhaustive 16-word × 24-arrival × 24-spacer order coverage plus six reset-restart deliveries; two exact controls |
| Random MUTEX | Four new seeds × two global-RNG-noise variants = eight | 48 tie choices and over 100 committed decisions per variant, exact reset reproducibility/noise independence, both winners in three arrival modes, at least 60 distinct latencies across the campaign; a real constant-resolution mutant must fail latency coverage |

The total is **276 positive cases**, **35 diagnostic-specific controls**, and sixteen additional positive finite-prefix companions for phase controls. The eight new closure cases use 5/11/19/29 ns closure paths, toggle delays of 4/8 ns, history delays of 3/7 ns, XOR delays of 2/9 ns and a strict one-femtosecond guard margin. The exact independently selected combinations are in the new plan; every role's values differ from candidate 1's fresh closure set. These are deliberately reparameterized sensitivity experiments, including closure values beyond the default 1–10 ns fixture bounds. Normal composition/phase delay samples stay within their declared 1–10 ns bounds; phase MUTEX sensitivity uses a maximum resolution of 20 ns. The primitive MUTEX experiment uses integer femtosecond resolution 10–100. Atomic cells, ideal wires and documented reset assumptions still apply.

## Recorded freeze and replay procedure

The repaired implementation, harness, tests, plan and CI integration were committed first. This historical command then froze the candidate without executing it; it deliberately refuses to overwrite the existing manifest:

```text
python verification/l1_acceptance.py --freeze --plan verification/l1-plan-2.json --candidate qualification/l1-candidate-2.json
```

For an exact replay, use an isolated checkout of **`b430180aefef3c51b755851fd24f28a1127d3aa4`**, run `python tools/qualify.py`, then execute with that checkout's qualified virtual-environment Python. Later CA-08 execution inputs intentionally fail this historical candidate's source-identity check; current development uses the full qualifier instead.

```text
.venv/Scripts/python.exe verification/l1_acceptance.py --candidate qualification/l1-candidate-2.json --output target/l1-acceptance/native-windows-candidate-2-replay-1
.venv/bin/python verification/l1_acceptance.py --candidate qualification/l1-candidate-2.json --output target/l1-acceptance/native-linux-candidate-2-replay-1
```

The output directory must not exist. Every failed attempt remains retained; a retry does not erase a failure or turn it into a pass. Candidate execution inputs, including CI and the acceptance plan, must match the committed manifest before and after execution. The manifest itself cannot be overwritten by `--freeze`. Repairs after an acceptance failure require a new named candidate, prospective replacement inputs where the failed run exposed them, and an explicit supersession decision.

The harness copies the 34 frozen exports into each private attempt directory before invoking any checker. This keeps active mapping probes and simulation files away from the shared generated exports. Native Icarus 13.0 is required; missing tools, disabled Python assertions, nonzero exits, stale output, empty/partial/duplicate inventories, missing activity, wrong control diagnostics and changed source/bench/trace/log/XML hashes all fail closed. Aggregate `PASS` strings alone never satisfy acceptance. Composition, phase and reference traces are replayed and compared with exact planned activity; closure, DIMS and primitive arbitration require their explicit completion markers and exact negative diagnostics. The final artifact inventory retains file hashes for subsequent independent audit.

The machinery tests use synthetic reports/logs and corruption cases, without consuming candidate 2's held-out simulations. Full development qualification and clean-JAR replay remain separate required evidence at the same candidate source state. Acceptance does not close L1 automatically: separate scoped review, an audit of both native artifacts, and a recorded decision are required. Replay a historical candidate using its historical source checkout; current defaults select candidate 2.
