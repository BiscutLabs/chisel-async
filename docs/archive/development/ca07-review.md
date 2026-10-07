# CA-07 review and repairs

> Historical development record. For current usage, read the [user documentation](../../index.md).

On October 6, 2026, three fresh-context agents independently reviewed `fc8dbf4c495cea5cc45db0d598709120bd6f6a8c`, without the implementation conversation. They reviewed controllers/scientific assumptions, export/API bindings, and verification/evidence. This is separate agent review, not external human or asynchronous-circuit specialist certification. Shared model and tool assumptions can produce correlated errors.

## Findings and repair

| Finding | Repair and regression |
| --- | --- |
| P2: a two-phase port could be relabelled four-phase in a rehashed contract against unchanged RTL and compiler metadata. | Port ABI v2 reflects protocol identity from actual hardware bundle types, independently of the channel registry. The resolver binds each declared protocol to the common source-bundle root. Tests cover both relabelling directions, vector channels, absent/duplicate bindings and old ABI rejection. A Scala test reflects all four encodings without registering any channels. |
| P2: deleting timing records and renaming semantic primitive IDs bypassed required-obligation checks. | Every inventoried constraint marker must correspond to exactly one timing record. Existing RTL instance/parameter checks prevent deleting the marker declaration or changing its kind while retaining the actual cell. Tests remove obligations and rename cells in both phase and both encoding converter directions. |
| P2: the settled two-phase observer rejected a causal idle-data update in the acknowledgement completion sample. | The observer retains the offered payload for completion but permits new idle data when request and acknowledgement match. Both completion polarities and changes while pending are tested. An actual emitted buffer receives immediate post-acknowledgement data updates in two directed cases. Delta-cycle causality and physical hold time remain outside the settled observation model. |

Controller RTL and primitive models are unchanged by these repairs. Older exports must be regenerated for port ABI v2; older phase traces require their recorded checker revision.

## Verification improvements

- Phase trace v2 records separate HDL acknowledgement-edge counters for every channel in every reset epoch. The replay requires exact agreement with protocol-decoded completions, including zeros. A selective-omission test leaves one valid internal transaction but removes a later epoch; it now fails. This establishes completion-count coverage, not retention of every intermediate data observation or protection against coherently corrupted instrumentation.
- `TwoPhaseInitialTokens.done` must follow the final internal return, eventually assert, remain high until reset, and clear during reset. Four actual RTL mutations must activate `DONE_EARLY`, `DONE_NOT_ASSERTED`, `DONE_WITHDRAWN` and `DONE_RESET` respectively.
- Eighteen mandatory directed cases supplement the 5,454-case sweep: nine scenarios at nominal and uniform 10 ns. They cover immediate source response, a 500 ns source return hold, partial-valid and partial-spacer reset, partial fork delivery, both adapter return phases, and arbitration resolution/handover. Reset requires a witnessed state; handover specifically requires zero grants while the previous acknowledgement remains high. Fresh traffic, exact delivery totals, per-epoch counts and final drain follow every reset.
- The two timing controls now share their companion cell skew between baseline and mutant. Only the targeted guard differs.
- Exhaustive 36-pair rail permutations are correctly attributed to the decoder input. Encoder rail order is produced by the cell delays and is not an independently permuted stimulus.
- CI retains consumer contract, port/probe ABI, resolved mappings and HW snapshots alongside traces and test reports, allowing replay without borrowing the main project's metadata.

The consumer repeats all eighteen directed cases and all sixteen controls, alongside its 54 sweep cases. These are development regressions informed by review, not retrospectively designated held-out acceptance cases. Representative near-limit guard experiments remain additional review evidence; the permanent sweep and directed cases retain the declared fixed guards.

## Independent checks and limits

The initial controller reviewer found no production failure in 120 additional cases / 26,328 deliveries, including near-limit guards and long source/sink holds. The verification reviewer audited both native inventories, replayed 288 positive traces and all 96 baseline/mutant control traces, and checked independent acknowledgement-edge counts. Those results remain evidence for the frozen pre-repair revision, with the three findings above recorded.

On the repaired export, the same export reviewer independently rejected the original mutations plus related cases. Thirty copied baseline exports passed 1,186,348 mapping checks; one valid marker rename passed and twelve corruptions produced their intended rejections. The control reviewer audited the eighteen directed cases and independently replayed the four strengthened arbitration-reset cases, finding no remaining blocking scientific/contract issue in that scope.

The verification reviewer separately audited fourteen standard and eighteen directed smoke cases, independently counted per-epoch acknowledgement edges, reproduced the selective-omission rejection, and freshly compiled the immediate-source case, four `done` fault pairs and four strengthened arbitration cases. Twenty-six focused oracle tests pass. All three reviewers report no remaining actionable issue within their repair scopes. The reviewer explicitly distinguished older smoke hashes from the subsequent arbitration-trigger change and verified the updated benches against the current source.

The complete qualifier passes locally on native Windows and on both native CI hosts at repair commit `03d3633e7f3a7067fa61223e9abdc23a02cb5a5b`: 42 Scala tests, 292 Python tests, 58 exports, all earlier campaigns, 5,454 CA-07 sweep cases / 908,080 deliveries, eighteen directed cases / 4,210 deliveries, all sixteen diagnostic-specific controls, five ChiselSim tests and the published-JAR consumer. The consumer repeats 54 sweep cases plus the eighteen directed cases and all sixteen controls. [Native CI run 37499939891](https://github.com/BiscutLabs/chisel-async/actions/runs/37499939891) passes on Windows Server 2025 and Ubuntu 24.04. Both retained artifacts pass inventory and source/bench/trace/log/XML hash audits, including the consumer metadata. CA-06 and CA-07 summaries and checker identities agree across hosts, as do CA-07 delay overrides. [Qualification status](qualification.md) retains exact revision scope; historical run `37487912661` does not qualify these repairs.

Reproductions and source/result hashes stay under ignored `target/review-ca07-{control,export,verification}` and the corresponding `*-repair` directories. The consolidated initial review is `target/review-ca07-root/review.json`. Repair audit scripts/results are `target/audit_ca07_repair.py`, `target/ca07-repair-native-audit.log`, `target/ca07-repair-local-audit.json` and `target/ca07-repair-complete-local-audit.json`. Current campaign evidence is under `target/verification/phase` and the clean-consumer verification directories; CI retains its own artifacts.

At this repair revision, L1 remained open: repair review and a passing development campaign did not replace a frozen held-out decision. The later [L1 candidate 2](l1-acceptance.md) now passes independent review and audited native Windows/Linux acceptance. No physical timing, QDI, analog metastability, exhaustive reset/delay correctness or macOS qualification is claimed.
