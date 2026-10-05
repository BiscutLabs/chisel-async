# Implementation ownership and progress

This repository owns chisel-async implementation. The initial detailed design is recorded in the [versioned implementation plan](https://github.com/crockpotveggies/chiselator/blob/3edf79529ab9909d3039dc33c1274d2fbdc173dd/docs/chisel-async-implementation-plan.md). Track implementation decisions here; Chiselator should consume released artifacts and fixtures rather than duplicate library source.

| Work package | Current status |
| --- | --- |
| CA-01 Build and external-tool probe | Native Windows build/emission/event run works; three-platform CI configured, remote runs pending. |
| CA-02 Protocol and reference contracts | Four-phase transition monitor and independent token ledger, bounded two-token/reset exploration, per-case traces and fault controls implemented; full primitive/reset/public trace schema catalog pending. |
| CA-03 Typed API and export proof | Scoped registry, domain-aware connections, deterministic sidecar/schema and checked RTL endpoint round trip implemented for the pinned debug export. Wider compiler configurations remain unqualified. |
| CA-04 Primitive foundation | C-element, latch and transport/inertial delay views implemented; independent bit, pulse, reset and timing tests execute from a published local artifact. |
| CA-05 First library example | Behavioral buffer and separate structurally composed transform/delay/latch timing fixture pass independent event tests, including clean artifact consumption. Structural handshake controller remains pending. |
| CA-06 Four-phase composition | Two-buffer example exercises composition; FIFO/token initialization, fork/join/select/merge remain pending. |
| CA-07 Arbitration and two-phase | Planned. |
| CA-08 QDI family and converters | Planned. |
| CA-09 Clocked and application boundaries | Planned. |
| CA-10 Packaging and complete functional release | Local artifact/resource consumption works; full catalog and release qualification remain pending. |
| CA-11 RISCay-MCU handoff | Planned after the functional library catalog is qualified. |

The timing/compiler work is implemented for the documented digital-model/debug-export slice. The complete L0 gate is not claimed: native Linux/macOS results, independent contract review and the structural handshake controller remain outstanding. Next replace or supplement abstract buffer storage with structurally composed controllers under the existing transaction tests. Keep the behavioral view as an independent integration target rather than silently changing its contract.

The initial verification review gaps are addressed by the [bounded regression campaign](verification.md): transition observers, per-bit patterns, reset accounting/restart, activated fault controls and retained traces. The [timing/compiler campaign](timing-and-export.md) adds independent inequalities and endpoint corruption controls. Preserve both campaigns when extending the implementation; neither replaces independent review or a frozen release campaign.

Complete the defined two-phase, QDI, arbitration, clocked/CDC and memory/I/O catalog before the MCU implementation gate. Physical cells, synthesis, PDK choice, layout and manufacturing remain step 4, after library, MCU and simulator functional work. Clocked support remains necessary at explicit boundaries.
