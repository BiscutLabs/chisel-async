# Implementation ownership and progress

This repository owns chisel-async implementation. The initial detailed design is recorded in the [versioned implementation plan](https://github.com/crockpotveggies/chiselator/blob/3edf79529ab9909d3039dc33c1274d2fbdc173dd/docs/chisel-async-implementation-plan.md). Track implementation decisions here; Chiselator should consume released artifacts and fixtures rather than duplicate library source.

| Work package | Current status |
| --- | --- |
| CA-01 Build and external-tool probe | Windows/Linux native CI foundation checks pass, plus separate WSL Ubuntu evidence. Exact JDK bootstrap and per-platform Python pins work. macOS explicitly deferred. |
| CA-02 Protocol and reference contracts | Four-phase transition monitor and independent token ledger, bounded two-token/reset exploration, per-case traces and fault controls implemented; full primitive/reset/public trace schema catalog pending. |
| CA-03 Typed API and export proof | Scoped registry, domain-aware connections, deterministic sidecar/schema and checked RTL endpoint round trip implemented for the pinned debug export. Wider compiler configurations remain unqualified. |
| CA-04 Primitive foundation | C-element, latch and transport/inertial delay views implemented; independent bit, pulse, reset and timing tests execute from a published local artifact. |
| CA-05 First library example | Behavioral buffer and separate timing fixture remain useful reference targets. Custom structural controller withdrawn after a reproduced internal delay race; published-controller replacement and architecture validation now block completion. |
| CA-06 Four-phase composition | Paused at the design gate until controller and cross-encoding API validation; FIFO/token initialization, fork/join/select/merge remain pending. |
| CA-07 Arbitration and two-phase | Planned. |
| CA-08 QDI family and converters | Pull a minimal dual-rail completion/storage example ahead of CA-06 to validate the shared architecture. Full family remains planned. |
| CA-09 Clocked and application boundaries | Pull a minimal explicit-clock Decoupled bridge pair ahead of CA-06. Full CDC and application catalog remains planned. |
| CA-10 Packaging and complete functional release | Local artifact/resource consumption works; full catalog and release qualification remain pending. |
| CA-11 RISCay-MCU handoff | Planned after the functional library catalog is qualified. |

The October 5 platform decision scopes the current L0 attempt to Windows and Linux, with macOS deferred. WSL is additional Linux-under-WSL evidence, never native Windows evidence. Baseline build, export, primitives and clean consumer checks have executable evidence. External review found a structural-controller design flaw, now independently reproduced. L0 is blocked by controller replacement and architecture validation, not just missing sign-off. Physical implementation remains step 4; controller correctness under stated delay assumptions belongs in the current library design gate.

Follow the [external review response](review-response.md): compare a published controller with explicit capacity/handshake/timing assumptions; validate logical channels, distinct input/output types and timing policies using bundled, dual-rail and clocked examples; qualify scalable observation/intent export; only then expand CA-06. The withdrawn controller lives under `experimental.UnsafeFourPhaseStage` solely for regression. Preserve the behavioral buffer and existing functional/timing campaigns without treating them as delay-robust controller evidence.

The initial verification review gaps are addressed by the [bounded regression campaign](verification.md): transition observers, per-bit patterns, reset accounting/restart, activated fault controls and retained traces. The [timing/compiler campaign](timing-and-export.md) adds independent inequalities and endpoint corruption controls. Preserve both campaigns when extending the implementation; neither replaces independent review or a frozen release campaign.

Complete the defined two-phase, QDI, arbitration, clocked/CDC and memory/I/O catalog before the MCU implementation gate. Physical cells, synthesis, PDK choice, layout and manufacturing remain step 4, after library, MCU and simulator functional work. Clocked support remains necessary at explicit boundaries.
