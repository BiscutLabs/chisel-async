# Implementation ownership and progress

This repository owns chisel-async implementation. The initial detailed design is recorded in the [versioned implementation plan](https://github.com/crockpotveggies/chiselator/blob/3edf79529ab9909d3039dc33c1274d2fbdc173dd/docs/chisel-async-implementation-plan.md). Track implementation decisions here; Chiselator should consume released artifacts and fixtures rather than duplicate library source.

| Work package | Current status |
| --- | --- |
| CA-01 Build and external-tool probe | Windows/Linux native CI foundation checks pass, plus separate WSL Ubuntu evidence. Exact JDK bootstrap and per-platform Python pins work. macOS explicitly deferred. |
| CA-02 Protocol and reference contracts | Four-phase transition monitor and independent token ledger, bounded two-token/reset exploration, per-case traces and fault controls implemented; full primitive/reset/public trace schema catalog pending. |
| CA-03 Typed API and export proof | Scoped registry, domain-aware connections, deterministic sidecar/schema and checked RTL endpoint round trip implemented for the pinned debug export. Wider compiler configurations remain unqualified. |
| CA-04 Primitive foundation | C-element, latch and transport/inertial delay views implemented; independent bit, pulse, reset and timing tests execute from a published local artifact. |
| CA-05 First library example | Behavioral buffer, structural latch-based buffer/pure-transform stage and separate timing fixture pass independent event tests and clean artifact consumption. Structural stage qualification is zero-delay functional only; timed controller qualification remains open. |
| CA-06 Four-phase composition | Two-buffer example exercises composition; FIFO/token initialization, fork/join/select/merge remain pending. |
| CA-07 Arbitration and two-phase | Planned. |
| CA-08 QDI family and converters | Planned. |
| CA-09 Clocked and application boundaries | Planned. |
| CA-10 Packaging and complete functional release | Local artifact/resource consumption works; full catalog and release qualification remain pending. |
| CA-11 RISCay-MCU handoff | Planned after the functional library catalog is qualified. |

The October 5 platform decision scopes the current L0 attempt to Windows and Linux, with macOS deferred for a later qualification campaign. WSL is additional Linux-under-WSL evidence, never native Windows evidence. Build, export, primitives, functional stage/transform and clean consumer checks now have executable evidence. Formal L0 sign-off still requires independent contract review; this development session cannot supply independent reviewer approval. Physical timing remains step 4; timed stage models must be qualified separately before advertising that mode.

The structural controller work is started and its zero-delay functional slice is implemented. Next in CA-06 is a depth-parameterized FIFO composed from qualified stages: reject depth below one, verify exact capacity/order/full-empty behavior and reset at full occupancy before adding initialized tokens, fork/join, select and exclusive merge. Preserve the behavioral buffer as a separate integration target and retain both functional and timing campaigns.

The initial verification review gaps are addressed by the [bounded regression campaign](verification.md): transition observers, per-bit patterns, reset accounting/restart, activated fault controls and retained traces. The [timing/compiler campaign](timing-and-export.md) adds independent inequalities and endpoint corruption controls. Preserve both campaigns when extending the implementation; neither replaces independent review or a frozen release campaign.

Complete the defined two-phase, QDI, arbitration, clocked/CDC and memory/I/O catalog before the MCU implementation gate. Physical cells, synthesis, PDK choice, layout and manufacturing remain step 4, after library, MCU and simulator functional work. Clocked support remains necessary at explicit boundaries.
