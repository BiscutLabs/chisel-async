# Implementation ownership and progress

This repository owns chisel-async implementation. The initial detailed design is recorded in the [versioned implementation plan](https://github.com/crockpotveggies/chiselator/blob/3edf79529ab9909d3039dc33c1274d2fbdc173dd/docs/chisel-async-implementation-plan.md). Track implementation decisions here; Chiselator should consume released artifacts and fixtures rather than duplicate library source.

| Work package | Current status |
| --- | --- |
| CA-01 Build and external-tool probe | Windows/Linux native CI foundation checks pass, plus separate WSL Ubuntu evidence. Exact JDK bootstrap and per-platform Python pins work. macOS explicitly deferred. |
| CA-02 Protocol and reference contracts | Four-phase transition monitor and independent token ledger, bounded two-token/reset exploration, per-case traces and fault controls implemented; full primitive/reset/public trace schema catalog pending. |
| CA-03 Typed API and export proof | Scoped registry, domain-aware connections, deterministic sidecar/schema and checked RTL endpoint round trip implemented for the pinned debug export. Wider compiler configurations remain unqualified. |
| CA-04 Primitive foundation | C-element, latch and transport/inertial delay views implemented; direct N-input/asymmetric C-elements and explicit control/latch models added for the published controller. Independent state/history, reset and timing checks execute from a published local artifact. |
| CA-05 First library example | Published fully decoupled long-hold stage implemented with distinct input/output types and explicit timing policies. Bounded digital campaign and clean consumer added; initial cross-encoding probes implemented; scalable export and independent review still block completion. |
| CA-06 Four-phase composition | Paused until scalable export, broader qualification and independent review; FIFO/token initialization, fork/join/select/merge remain pending. |
| CA-07 Arbitration and two-phase | Planned. |
| CA-08 QDI family and converters | Minimal dual-rail storage/completion probe implemented using logical payloads and independent RTZ tests. Full QDI family, converters and physical qualification remain planned. |
| CA-09 Clocked and application boundaries | Explicit-clock Decoupled bridge pair and two-clock round trip implemented with synchronized control and coordinated reset. Physical CDC qualification and full application catalog remain planned. |
| CA-10 Packaging and complete functional release | One-command setup/qualification and expanded local JAR consumption work; full catalog, Chisel-native simulation lane and release qualification remain pending. |
| CA-11 RISCay-MCU handoff | Planned after the functional library catalog is qualified. |

The October 5 platform decision scopes the current L0 attempt to Windows and Linux, with macOS deferred. WSL is additional Linux-under-WSL evidence, never native Windows evidence. External review found a structural-controller design flaw, independently reproduced and replaced with the [published long-hold design](long-hold-controller.md). The first logical-channel/encoding probes are implemented. L0 remains open for scalable observation/export, broader qualification and independent review. Physical implementation remains step 4; controller correctness under stated delay assumptions belongs in the current library design gate.

The [published-controller comparison](controller-comparison.md) remains a bounded reference experiment: Muller has a different buffer contract. The replacement long-hold stage now passes the existing stronger contract with published primitive topology and an independent event graph. The [logical-channel probes](logical-channels.md) now bind common payload/reset intent to bundled, dual-rail and Decoupled ports; explicit bridges test conversion and clock boundaries. Next, qualify scalable observation/intent export under optimization/deduplication and add the Chisel-native simulation lane before expanding CA-06. The withdrawn controller lives under `experimental.UnsafeFourPhaseStage` solely for regression. Preserve its counterexample and all existing functional/timing campaigns.

The initial verification review gaps are addressed by the [bounded regression campaign](verification.md): transition observers, per-bit patterns, reset accounting/restart, activated fault controls and retained traces. The [timing/compiler campaign](timing-and-export.md) adds independent inequalities and endpoint corruption controls. Preserve both campaigns when extending the implementation; neither replaces independent review or a frozen release campaign.

Complete the defined two-phase, QDI, arbitration, clocked/CDC and memory/I/O catalog before the MCU implementation gate. Physical cells, synthesis, PDK choice, layout and manufacturing remain step 4, after library, MCU and simulator functional work. Clocked support remains necessary at explicit boundaries.
