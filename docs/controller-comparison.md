# Published-controller comparison

Development experiment, October 5, 2026. **Keep the custom controller withdrawn. Keep the Muller implementation as a bounded reference, not a replacement for `FourPhaseBuffer`. Select the Furber–Day fully decoupled, long-hold design as the production design target.** Its separate implementation and evidence are now in [the long-hold record](long-hold-controller.md); this comparison remains a different experiment.

## Source and contract

The independently written reference follows the C-element/inverter/latch connections in Sparsø's tutorial, figures 2.8–2.9: `c = C(in_req, !out_ack)`, with the data latch transparent while `c=0`. We visually inspected printed pages 17–18 (PDF pages 31–32) in the [university-hosted tutorial PDF](https://www.inf.pucrs.br/~calazans/graduate/SSD/Bibliography/Sparso-Furber-Short.pdf). The inspected March 17, 2006 draft has SHA-256 `3838e2815f653c47e3cb2040420b23589b5cc5d3101b06b95d0eaa1459d18dc6`. No source code, diagram or prose was copied.

[Furber and Day, *Four-phase micropipeline latch control circuits*, DOI 10.1109/92.502196](https://research.manchester.ac.uk/en/publications/four-phase-micropipeline-latch-control-circuits/) distinguishes simple, semi-decoupled and fully decoupled controllers. The candidate is the fully decoupled long-hold design in section 7, figures 14–15, preserving the persistent form rather than adopting section 8's dependency-removal optimizations. Its purpose matches our independent input handshake and output-data retention requirements. The [author-uploaded paper](https://www.researchgate.net/publication/3336839_Four-phase_micropipeline_latch_control_circuits) provides the section text. A literature citation is not evidence that an implementation satisfies those requirements.

The comparison uses **early data validity**: establish data before request rises and retain it through acknowledgement rising. The existing library [FourPhase contract](contracts.md) requires retention through acknowledgement falling. We did not weaken that public contract. The reference lives only in `verification/controllers/muller.sv`; it is not exported as a supported Chisel stage.

| Requirement | Withdrawn controller's intended contract | Muller comparison reference |
| --- | --- | --- |
| Stalled capacity, three physical stages | Three tokens | Two tokens, measured |
| Stalled capacity, six physical stages | Not tested | Three tokens, measured |
| Input return independent of stalled output | Required | Not generally provided |
| Output data retained through complete return | Required | Early validity only |
| Control implementation | Emitted Boolean expressions plus state latches | Explicit C-element, inverter and latch boundaries |
| Outcome | Reject for new composition | Retain as an experimental reference |

Adding Muller stages can supply storage capacity; it does not supply the missing handshake independence or longer validity interval. This is why the reference cannot silently take the old stage's API name.

## Frozen digital model

Each stage has identity datapath width 40: a 32-bit monotonically increasing transaction identity and eight payload bits. Repeated payload bytes cannot hide a duplicated, reordered or corrupted identity.

The withdrawn design is freshly emitted from `UnsafeFourPhaseBuffer(UInt(40.W))` and its original export is checked before annotation. The runner expands each emitted scalar `~`, `&` and `|` into a delayed primitive, preserving precedence and left association without factoring. It retains the actual state connections and a cell map. Unsupported syntax fails closed. There are 19 Boolean cells and four latches per stage. This is one explicit mapping of the emitted logic, not a claim about every synthesis mapping.

The Muller stage has two inverters, one C-element and one data latch, plus two fixed delay buffers. C-element and latch boundaries are atomic behavioral cells. Every varied cell gets an independent, fixed-per-run integer delay of 1–10 ns. Boolean/C-element outputs and latch-state propagation use inertial delay. Latch capture is level sensitive; there is no analog aperture or per-bit skew. Wires and forks are ideal. These semantics differ from the captured-value nonblocking latch delay in the separate [directed counterexample](review-response.md#reproduced-failure); both experiments are retained.

The Muller reference includes **40 ns forward request delay and 20 ns upstream acknowledgement delay**, on both transitions. These are declared assumptions, not parameters tuned separately for passing seeds. The acknowledgement guard exceeds the modeled maximum 10 ns latch-closing inverter delay. A conservative closing-plus-data propagation budget is 10 + 10 ns, below the 40 ns forward guard. The cell model has zero additional setup/hold aperture. Arbitrary transforms, routed forks, wire delays or physical cells would require new inequalities and evidence. The withdrawn implementation receives no added guards: we are evaluating that implementation as emitted, not comparing equal area or performance.

The environment changes input data 2 ns before request and obeys each external handshake. Source/sink response, return and pause times range from 1–60 ns. Reset is coordinated: assert reset before withdrawing external drivers, hold it for 1,000 ns, then wait another 1,000 ns before traffic. Reset tests require quiescent outputs and no stale token. Independent endpoint reset is outside scope.

Two cell checks, at 1 ns and 10 ns, measure actual output propagation and verify C-element unanimity/hold, inertial pulse rejection, latch storage and reset. They prevent accidentally running another zero-delay experiment.

## Campaign and oracle

`compare_controllers.py` freezes xorshift32-v1, seeded with `seed+1`, for seeds 0–299. Environment timings are drawn first and shared across controllers; subsequent draws assign cell delays in stage/cell order. Different cell inventories are not electrically identical random samples. Every assignment is retained in `case.json`.

Each successful case must execute:

- Forty ordered transfers, including adjacent equal payload bytes, with exactly forty accepted, offered, delivered and returned transactions in the stream.
- Reset at idle, just after an input offer, after input acceptance with a stalled sink, during an output offer, after output acceptance, and during return. Every scenario completes fresh traffic afterward.
- A 5,000 ns sink stall that reaches the controller's declared capacity; reset aborts exactly those queued tokens, followed by a fresh transfer. The source may be waiting to offer another token or waiting for input-handshake return, depending on the controller and depth.
- Final accounting of 49 deliveries and 47 completed output returns. The two additional deliveries have their return phases interrupted by reset; delivery is not undone by reset.

Passive monitors check all pipeline links, including request/acknowledgement order and early data hold. An independent FIFO of accepted identities checks delivery, ordering and conservation. It also rejects capacity overflow during traffic, rather than waiting for a later timeout. None of these checks uses controller state equations.

In addition to the random cases, each controller has all-1 ns and all-10 ns baselines. Each Muller depth has sixteen extreme-delay cases: all combinations of 1/10 ns for its four cell roles, with that combination repeated across stages. This is not exhaustive enumeration of independent stage delays.

Two deliberately broken references must fail for specific reasons: removing the forward delay gives `DATA_HOLD`; clearing the transaction identity in the datapath gives `PAYLOAD_MISMATCH`. Unrelated assertions, compiler errors, simulator crashes and host timeouts invalidate the campaign. A simulated 200,000 ns deadline is reported separately as **bounded nonprogress**, not proof of permanent deadlock. Multiple monitors may report the same violating simulation instant; a case is counted once, by its first diagnostic.

## Executed results

Native Windows 11 / Icarus 13.0 / Python 3.12.13 and a separate Ubuntu-under-WSL checkout / native Linux Icarus 13.0 / Python 3.12.3 produced the same results:

| Controller | Random cases passed | Detected violations | Bounded nonprogress | Other cases |
| --- | ---: | ---: | ---: | --- |
| Withdrawn, three stages | 46 / 300 | 252 | 2 | Both uniform baselines pass |
| Muller, three stages | 300 / 300 | 0 | 0 | Both uniform baselines and all 16 corners pass |
| Muller, six stages | 300 / 300 | 0 | 0 | Both uniform baselines and all 16 corners pass |

The withdrawn failures include data-hold, payload, protocol-order, unexpected-token and capacity violations. Seed 1 retains a data-hold counterexample; seeds 184 and 206 reach the progress deadline. Both deliberate fault controls and both cell checks behave as required on both hosts. Fifteen Python harness tests additionally reject false passes, unsupported compiler syntax, wrong activity counts and infrastructure failures.

[Native CI run 37400947157](https://github.com/BiscutLabs/chisel-async/actions/runs/37400947157), at implementation commit `40f3b7c`, passes on Windows Server 2025 and Ubuntu 24.04 with the same comparison counts. Both lanes also pass 17 Scala tests, all 85 Python tests, the existing functional/timing campaigns, the original directed race and the clean-consumer checks. This is executed native Linux evidence in addition to WSL.

These are **our experiment's numbers**, not a reproduction of the external reviewer's 165/300 result. The reviewer identifies `chisel-async-delay-harness.zip` as the source artifact. Reproducing it requires a separate record of its archive hash, seed mapping, latch model and schedules; this comparison does not claim that reproduction. Finite passing samples do not prove delay independence, hazard freedom, QDI correctness or physical timing closure. This was development testing, not an independently held-out release campaign.

## Replay and evidence

With the README's pinned tools installed:

```text
python tools/sbt.py "examples/runMain chiselasync.examples.EmitControllerComparison target/generated/comparison_unsafe"
python -m pytest verification/test_controller_comparison.py -q
python verification/compare_controllers.py
```

`--seeds 2` is a short smoke run and explicitly records its smaller inventory. `--output <directory>` selects a separate evidence directory. A single case can be rerun with the exact argument array in its `case.json`, from that file's parent directory.

`target/verification/controller-comparison/report.json` records outcomes, activity, original export hashes, annotated-source/checker hashes and engine identities. `build` contains the annotated DUT, source snapshots, cell map, compile commands and cell tests. Every case retains all handshake-edge/reset events and its delay assignments. VCDs are retained for each uniform-10 case, the first failure of each diagnostic kind, and both deliberate faults. Only the current report's case inventory describes the current run; files from a previous longer run may remain in the output directory. CI runs the full sweep on Windows and Linux and uploads the evidence. macOS remains deferred.

## Next implementation gate

The [fully decoupled long-hold implementation](long-hold-controller.md) now checks its published event graph, emitted cell connections, typed transforms and explicit timing policy against the stronger buffer oracle and a separate delay campaign. The first [logical-channel/encoding probes](logical-channels.md) and optimized observation/export are implemented. The separate [frozen L0 campaign and fresh-context agent reviews](l0-acceptance.md) now pass for Windows/Linux, permitting CA-06 to begin. This Muller reference still has its own distinct contract; its passing random sweep alone does not close L0.
