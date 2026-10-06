# L1 independent development review

Three fresh-context agent tasks reviewed the source starting at `15ca6f004eceab83985fe0ffdbd6043181f92981`, whose library implementation is unchanged from `1116bf211ffd1534eaef06e8250652bf686ae1a4`. Their scopes were controller/protocol behavior, export obligations, and prospective acceptance machinery. These are scoped agent reviews, not external human certification.

## Findings and repairs before candidate freeze

The export review found four blocking validation gaps. All involved corrupted copies of emitted RTL with refreshed source hashes; the original library circuits were unchanged.

| Gap | Repair and regression evidence |
| --- | --- |
| A select stage's storage latch could bypass the declared delayed data path. | Bind the actual delay output, latch data and closure pins to their declared endpoints; retain a rehashed bypass control. |
| The two-to-four adapter's return guard could take the wrong history signal. | Check the master/history/returned/guard/XOR pin chain against the channel endpoints. A paired behavioral witness detects acknowledgement before return. |
| The return guard could be changed coherently to an inverter. | Require the declared noninverting buffer type, width and reset value. The mutation creates an unsolicited acknowledgement. |
| The long-hold fork constraint could retain its description while its OR became a buffer. | Check the actual OR, the asymmetric A cell's role and parameters, and the Aout-to-A/OR connections. The mutation violates data hold. |

`verification/test_l1_export.py` preserves the corruptions with exact diagnostics. `tools/check_export.py` checks actual elaborated cell parameters and actively exercises the pin bindings. This strengthens the qualified export proof; it is not a general asynchronous-circuit equivalence checker. Free-form descriptive text is not treated as an independently proved physical assumption.

## Control review

The control reviewer found no actionable production defect within the declared bounded digital scope. The final private campaign contains 48 independently written adapter cases with 9,216 completed stream transfers, exact request counts, immediate receivers, payload-hold listeners and reset/restart; 43 integration/reset cases with 9,079 external deliveries; and a passing fork baseline paired with a deliberate skew violation producing exactly `DATA_HOLD`.

The review audited 1,054 retained evidence hashes. Local evidence is under `target/l1-control-review`; the final report SHA-256 is `603e8564f7e6b4fe7003a87901b3c070b04db348325bc95864e7871ce1ad4bcf`. The prospective scope, private scripts, raw logs, intermediate attempts and conclusion remain retained there. The export experiments and paired witnesses are under `target/l1-export-review`.

The integration guard experiment uses margins of one femtosecond above the stated maxima. Its private RTL overrides retain nominal exported markers, so it establishes sensitivity of that RTL, not qualification of a newly emitted timing policy. Integration reuses the existing external ledger; only the standalone adapter stimuli/checks were written independently.

An observation limit was made explicit during review: settled four-phase traces cannot reconstruct request and acknowledgement transitions that occur within the same femtosecond sample. A causally immediate receiver therefore caused `FOUR_PHASE_ORDER` in that observer. Independent adapter benches retain zero-delay responses; the final integration run uses one-femtosecond response separation. Failed harness/preflight attempts and a stimulus replacement that initially matched nothing are documented and retained rather than counted as additional passing coverage.

## Acceptance decision

The original source was not accepted merely because its development CI passed. The validation gaps above were found before the first official L1 candidate was frozen. The repaired checker, its regression tests, the prospective campaign and CI integration must be committed together, then bound by a new immutable candidate manifest.

The [L1 acceptance record](l1-acceptance.md) owns the native execution and final closure decision. Local review, a passing prospective campaign, same-candidate complete qualification and audited native Windows/Linux evidence are all required. macOS and physical timing/QDI/metastability qualification remain outside this gate.
