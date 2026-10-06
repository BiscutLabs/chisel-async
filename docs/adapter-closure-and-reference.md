# Adapter closure and four-style reference

The follow-up review identified a real modeling gap: `ClosingLatch.DELAY_FS` delays data-to-Q, while `closed` previously acted immediately. A uniform or independent data-to-Q sweep could not reveal delayed history closure in `ToTwoPhase`.

## Closure repair

`PhaseTiming(cells, returnDelay, historyClosure, requestDelay)` separates the closure path from data-to-Q. The closure bound includes request distribution/skew and an allowance for latch aperture. A buffer models this latency at `history.closed`. The toggle still responds to the original request, but a second buffer delays its **output** before exposing the two-phase request. The strict policy is `requestDelay > historyClosure.max`; it conservatively ignores the additional positive toggle delay and receiver latency. Even an immediate receiver cannot answer before modeled closure.

Return is self-timed: `req4− → closed− → history updated → ack4−`. Delaying the toggle's input instead would be wrong: a legal request-low pulse can be shorter than the guard and disappear through inertial propagation. Coordinated reset must be held until every delayed path is quiescent.

This closure budget applies to the four-to-two history path. Other catalog latches, including those in the separate two-to-four adapter, retain ideal-wire/zero-intrinsic-aperture assumptions unless their own contract declares an additional path bound.

The two-argument constructor remains available and uses `cells` for the independently sweepable closure bound and `returnDelay` for the request guard. Default examples use 1–10 ns bounds and 40 ns guards. `phase-conversion-v2` carries these bounds, the closure endpoint and guard in both the sidecar and KIND 5 marker. Active export checks bind the marker to the actual history, toggle, guard and XOR pins; rehashed rewiring, inadequate guards and non-buffer guard cells are rejected. Regenerate earlier phase exports.

`run_closure.py` instantiates emitted production `ToTwoPhase` RTL. Its 101 positive cases include independent closure/toggle/history/XOR extremes, a one-femtosecond strict margin, the review's four latch/toggle pairs with 0–12 ns closure skew, immediate back-to-back transfers, long holds and six reset windows with restart. These deliberately reparameterized experiments include values beyond the default fixture's bounds; each case records its actual parameters. The regular phase campaign separately checks overrides against the exported bounds. Removing the guard and moving it before the toggle are paired controls with specific failures. This is our reproduction of the mechanism, not an assertion that we ran the reviewer's original harness or replicated its exact failure thresholds.

## Seeded arbitration

`MutexPolicy.SeededRandom`, `seed` and `resolutionJitter` add per-instance random decisions without changing the three existing policies. The model samples a winner and resolution in the inclusive interval `resolution .. resolution + resolutionJitter`. A local xorshift32 stream makes runs reproducible and independent of simulator-global random calls. Nonzero unsigned 32-bit seeds are supported; reset restarts the stream. Generation tags and an NBA ticket cancel stale scheduled decisions, including conventional same-timestamp NBA request/reset updates. Optional logs record scheduled and committed decisions.

Production requests must persist until granted and serviced. Tests also exercise cancellation outside that traffic contract; withdrawing a request in an arbitrarily later delta cycle at the exact decision time has no physical priority guarantee. Random sampling does not establish fairness, a metastability distribution, or a finite physical resolution bound.

The phase integration sweep retains all three fixed policies as corners, then uses seeded random decisions and 1–20 ns resolution sensitivity. The primitive campaign covers 34 seeds, each repeated with unrelated global RNG activity; it requires both winners for simultaneous arrivals and each near-tie arrival order, variable latency, held grants, a positive zero-grant handover interval, cancellation and reset reproducibility. Nine scheduling-boundary cases and actual CIRCT import of the random branch are additional Python tests. Import support is not execution equivalence of the imported IR.

## Same function in four styles

[EmitReference.scala](../examples/src/main/scala/chiselasync/examples/EmitReference.scala) computes `input[1:0] + input[3:2]`, producing an unsigned three-bit result at common four-phase bundled boundaries.

| Version | Implementation | Accepted-token capacity under stalled output |
| --- | --- | --- |
| Behavioral | Zero-delay functional buffer and arithmetic | 1 |
| Bundled | Published long-hold stage with a matched data budget | 1 |
| QDI example | Bundled encoder → DIMS adder/WCHB → bundled decoder | 2 |
| GALS | Clocked arithmetic island → asynchronous two-phase link → second clock island | 5 |

The QDI core follows the C-element-minterm/disjoint-OR construction described in Sparsø and Furber's [tutorial §5.5.1, Figure 5.10](https://www.inf.pucrs.br/~calazans/graduate/SSD/Bibliography/Sparso-Furber-Short.pdf). Sixteen four-input minterms wait for every input rail, retain state during partial spacer return, and feed dual-rail sums with output storage/completion. No binary decode/compute/re-encode shortcut is hidden inside the core. Atomic cells and ideal forks remain assumptions; there is no mapped physical QDI implementation. Its half-buffer is not fully decoupled, so three storage sites in the wrapped chain do not mean capacity three.

The default reference campaign runs 33 configurations per style. Each case sends the same 96 operands twice, including all sixteen input combinations, repeats, carry cases and random traffic. The first epoch waits for every internal async boundary to become idle and every clocked boundary to be empty/ready between transactions, then measures input-offer to output-offer latency. The last epoch stresses backpressure and measures delivery intervals. A middle epoch fills the declared capacity, aborts pending work through reset, then restarts. Independent integer arithmetic checks order, exact results, loss and duplication. Async internal protocols, clocked hold rules, and per-boundary completion witnesses are checked. Four real RTL wrong-result controls must fail.

The standalone DIMS campaign additionally exhausts all 16 inputs × 24 arrival orders × 24 independent spacer orders, at five cell-delay configurations, with partial-valid/spacer reset tests and paired early-valid/stateless-return controls. Rail steps are 200 ns apart so each partial state settles; these are exhaustive permutations, not exhaustive timings. This is 46,110 completed transfers. It checks strong indication directly, rather than relying solely on the wrapped arithmetic result.

Latency measurements include converters, storage, guards and clock/synchronizer costs. Different capacities and arbitrary model delays prevent a silicon speed/area/power ranking. The behavioral zero-delay result is an abstract reference. These examples supply functional integration evidence and a reproducible place to substitute characterized cells later; they do not close L1 acceptance.

The nominal seed-0 experiment uses 1 ns cell/data propagation, 40 ns bundled/phase guards, and GALS clocks of 14 ns and 22 ns with a 3 ns initial sink offset. The same 96 transactions produce these isolated input-offer to output-offer latencies:

| Version | Minimum–maximum | Mean |
| --- | --- | --- |
| Behavioral | 0 ns | 0 ns |
| Bundled | 81 ns | 81 ns |
| Wrapped QDI | 208–216 ns | 211.865 ns |
| GALS | approximately 417–431 ns | 417.146 ns |

These figures are reproducible with `run_reference.py --seeds 0` after emission. The complete 132-case development campaign delivers 25,344 checked results across all four styles; the full-wrapper/native result is recorded separately in qualification.

Run `python tools/qualify.py` for setup and all lanes, including published-JAR replay. Focused commands after emission are `python verification/run_closure.py`, `run_mutex.py`, `run_dims.py` and `run_reference.py` in the same directory. Evidence is retained under `target/verification/{closure,mutex,dims,reference}`; [qualification](qualification.md) records completed runs and revisions.
