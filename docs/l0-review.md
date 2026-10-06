# L0 delegated review and remediation

On October 5, 2026, the user authorized three fresh-context reviewer agents. They received the repository, candidate identity, review scope and evidence locations, without the implementation conversation. This is separate agent review, not external human or asynchronous-circuit specialist certification. Shared model/tool assumptions can still produce correlated errors.

## Decisions and findings

| Review | Candidate 1 judgment | Evidence and resolution |
| --- | --- | --- |
| `/root/controller_review` | Scoped PASS | Inspected Furber–Day Figs. 10/14/15 and the recorded PDF hash; compared 210 control excitations across all 42 graph markings. Ran 134 additional cases / 6,566 deliveries with guards 1 fs above strict bounds, 1 fs environment responses, mixed depth-four corners and 500 ns legal holds. No blocking controller, primitive, reset or accounting defect found. |
| `/root/verification_review` | Scoped PASS for the recorded campaigns | Replayed all 624 native-host acceptance logs/configurations with a newly written external-edge queue/reservation ledger, STG and exact diagnostic checks. Revalidated baseline/consumer functional traces and timing evidence. Ran 89 reference/checker tests and 15 fresh controller configurations, plus primitive/typed checks and required faults. No acceptance-affecting defect found in this scope. |
| `/root/export_review` | BLOCK CA-03; two P2 findings | Rehashed sidecar-only corruptions passed against unchanged RTL. Candidate 1 is superseded, despite its passing automated campaign. Both findings are repaired and closed by candidate 2 review and frozen native acceptance. |

**P2: payload leaf metadata was not fully checked.** Changing packet leaf widths from `[5,5,9,3]` to `[4,6,9,3]` retained total width and contiguous offsets but changed decoding boundaries. The old checker still passed 686 mapping comparisons because it concatenated whole source signals. Incorrect field names and signed flags also passed. The repair checks every leaf against a separately inventoried elaborated Chisel port, including exact source membership, name, width and signedness; actual Icarus port widths/directions and active packed-bit mapping remain independent checks.

**P2: channel direction and endpoint associations were not fully checked.** An input channel relabelled as output still passed. A bridge input clock redirected to the output clock passed 4,420 comparisons; a replicated request redirected to another lane passed 207,840. Individually valid endpoints did not establish a valid channel. The repair requires the factory-defined endpoint IDs, common hardware-bundle source roots, actual forward/reverse port directions and a typed input clock.

The new v3 sidecar hashes `ports.json`, a complete inventory obtained from `DataMirror.modulePorts` on each registered module, independently of channel records. Read probes are excluded. The resolver verifies exact module/port inventories and unique source targets, then checks channel metadata against those ports and real elaborated RTL. CIRCT erases signedness at the SV boundary: signed flags are checked against elaborated Chisel types, not misrepresented as recovered SV types. This remains bounded evidence, not a proof against coherently corrupted compiler, ABI and sidecar outputs.

Fourteen new Python corruption cases cover these holes and port-inventory corruption. A Scala test checks hand-derived nested UInt/SInt/Vec port facts and absence of hardware probe ports. All 29 exports, 188 Python checks and 29 Scala checks pass locally. The export reviewer independently reproduced all original mutations against the repair and obtained the exact intended rejections; 43 isolated export/architecture checks passed. The export reviewer approved the final repair scope, and the verification reviewer separately approved the prospective candidate 2 inventory/source freeze after 46 focused checks. Candidate 2 subsequently passed local Windows and native Windows/Linux acceptance at `c85f97b`; the verification reviewer audited all three artifacts and issued a scoped PASS with no unresolved verification blockers. [L0 is closed](l0-acceptance.md#closure-decision) for the stated foundation scope.

## Final candidate 2 audit

The verification reviewer checked all 103 frozen inputs, exact campaign configurations/bench hashes/raw logs, baseline and consumer traces, timing evidence and five-case ChiselSim XML for each run. Each native host independently replays 312 cases, 222,258 external channel edges and 15,288 deliveries, with all three exact fault detections. Native semantic and typed-port ABI hashes agree for all 29 qualification exports and the additional withdrawn-controller comparison export. A one-bit payload corruption in an in-memory log activates the reviewer's separate queue mismatch; original evidence is unchanged.

The final read-only decision is `target/review-verification/candidate2-final-review.json`, SHA-256 `4620cfe0974228ffcd1f6176f3e5c90bb5a7616d236a7a0a8401cc9d9492f1c2`. It records exact script/result hashes, including:

| Audit artifact | SHA-256 |
| --- | --- |
| `audit_candidate2_acceptance.py` | `da150de66753ea8791e1c7258c2af0b07c9e0b1ba2633c351b25d0a8eb6f175f` |
| `audit_candidate2_baseline.py` | `b0bc1a5460f2dd2fc54c19db1124fe6be25a3d6b086c46c6a5f1eb4f2f06531d` |
| `candidate2-all-hosts-acceptance.json` | `82f6d556733633cab35ac37dd389e16c2c6148ea95531792f7bd13144aae3b9d` |
| `candidate2-windows-baseline.json` | `5dc004b658f74c3218af7a5e5a970c34f1304908e2b4862170646f2253a3f21b` |
| `candidate2-linux-baseline.json` | `920fa33cb1cb8636d3941c8f0743ac0756bf065b92512668c596b2b51db418d2` |

These local review experiments stay under ignored `target` per repository policy. The separate native acceptance artifacts are retained by [CI run 37421591012](https://github.com/BiscutLabs/chisel-async/actions/runs/37421591012).

## Evidence and retained limits

Scratch review evidence is retained under `target/review-controller`, `target/review-verification` and `target/review-export`. The controller scripts are `graph_cells.py` and `adversarial.py`; verification's `review.json` records commands and hashes for `audit_artifacts.py`, `audit_baseline.py`, raw-log accounting and fresh runs. Export's `repair-review.json` records exact reviewed source hashes and diagnostics; original false-pass exports/checker are retained separately. These are review experiments, not retrospectively added held-out acceptance cases.

The nonblocking verification recommendation to retain consumer ChiselSim XML is incorporated in candidate 2 and independently verified on both native hosts. The controller's guard-edge/long-hold cases inform CA-06 regression expansion. Optimized internal endpoint checks still share timing-marker provenance; behavioral campaigns provide a distinct check. None of this approves arbitrary synthesis, cell decomposition, physical timing, analog metastability, independent endpoint reset, full QDI/arbitration/catalog coverage or macOS.
