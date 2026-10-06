# Published long-hold stage: bounded digital evidence

`FourPhaseStage[A, B]` implements a Furber–Day fully decoupled long-hold controller using three asymmetric C-element primitives and one OR primitive. `LongHoldBuffer[T]` supplies the identity transform. The old custom controller remains withdrawn under `experimental`; the behavioral `FourPhaseBuffer` remains a reference. This replacement satisfies the existing full-handshake data-hold and one-entry accounting tests under the models below. It is not a mapped or physically qualified circuit.

## Inspected source and preserved topology

Source: S. B. Furber and P. Day, *Four-Phase Micropipeline Latch Control Circuits*, IEEE Transactions on VLSI Systems 4(2), 1996, DOI [10.1109/92.502196](https://doi.org/10.1109/92.502196). The [eight-page author-paper copy](https://courses.e-ce.uth.gr/CE664/papers/Template-Based/async-latch-control-circuits.pdf) was inspected, including Fig. 10's asymmetric-cell notation and section 7, Figs. 14–15 (PDF pages 4–5). SHA-256: `67ec63bc0cc169cc5c9cfd98a5c68239009ce7ffd5edb5bfa7bb5422c8112934`. Scala, SV and verification code were independently written; no external implementation source was copied.

Our transcription of Fig. 15 is:

| State / signal | Rise condition | Fall condition |
| --- | --- | --- |
| A | B=0 and Rin=1 | B=1 and Aout=1 |
| B | Ain=1 | Ain=0 and Lt=0 |
| Ain | B=0 and Lt=1 | B=1 and Rin=0 |
| Lt | A OR Aout | Both inputs zero |

The latch is transparent at Lt=0. Input inversion bubbles belong inside each atomic asymmetric cell. They are not independently delayed inverter gates. A first transcription that split those bubbles failed a capacity corner; a retained mutation adds a 10 ns delay to A's Aout input and must fail with `CAPACITY_EXCEEDED`. Future cell mapping must preserve this boundary and establish its fork/polarity assumptions separately.

`verification/longhold_topology.py` checks the actual emitted primitive inventory, polarity parameters and connections. A separately transcribed event graph in `longhold_reference.py` follows Fig. 14; it has 42 reachable markings and 72 transitions. Exhaustive traversal checks marking safety, signal consistency, persistence and absence of dead markings in that graph. Simulation traces must obey its event dependencies. These checks cover the transcription and declared abstract model, not arbitrary gate decompositions or physical implementations.

## API and timing assumptions

```scala
class Operands extends Bundle { val left = UInt(8.W); val right = UInt(8.W) }
def bounded(ns: Long) = DelayBounds(ModelTime.ps(1000), ModelTime.ps(10000), ModelTime.ps(ns * 1000))
val model = BundledTiming.Digital(
  matchedDelay = ModelTime.ps(40000), dataDelay = bounded(8),
  controls = ControlDelays(a = bounded(1), b = bounded(2), acknowledge = bounded(3), longHold = bounded(4)),
  latchDelay = bounded(1),
  outputDelay = ModelTime.ps(40000))
class AddStage extends FourPhaseStage(new Operands, UInt(9.W),
  (p: Operands) => p.left +& p.right, model)
```

Imports are in [EmitLongHold.scala](../examples/src/main/scala/chiselasync/examples/EmitLongHold.scala). Output shape must match `B` exactly; ordinary `+` producing eight bits is rejected for a nine-bit output. Compose children with `asyncChild(id)(domain => new LongHoldBuffer(gen, policy, domain))` to share and wire the parent reset domain.

The wrapper adds a matched admission buffer before both uses of Rin, a modeled data-path delay before storage, and an output-request buffer after A. The latter enforces our ledger's acceptance-before-offer ordering and payload settling; these added guards are our wrapper, not a claim that the paper specifies these values. The data delay models the entire pure transform path, whose Chisel logic is otherwise ideal in this simulation.

`DelayBounds(min, max, model)` supplies each of A, B, acknowledgement, long-hold OR, data path and latch separately. The model value must lie within its bounds; `DelayBounds.fixed` expresses an exact value. `Digital` requires positive cell/latch lower bounds, `matchedDelay > dataDelay.max`, and `outputDelay > 2*max(control upper bounds) + latchDelay.max`. The latter is a deliberately conservative guard over all four controls. Exact femtoseconds and checked arithmetic prevent rounding/overflow. The strict guards avoid equality assumptions. They cover the declared atomic digital model with ideal wires/forks and zero latch aperture; physical setup/hold, pulse and routing constraints remain separate. Output propagation is inertial, and input polarity has no independent delay. Binary operation and coordinated reset held until quiescent are required; the campaign holds reset for 1000 ns, beyond its longest bounded path. Reset release starts with both external handshake drivers idle. Arbitrarily short reset pulses and analog uncertainty are not qualified.

`BundledTiming.FunctionalOnly` is the explicitly requested all-zero mode for the existing functional corpus. Neither mode has a default. While idle, a transparent stage's output data may follow input data. Once output request rises, data remains stable through output acknowledgement falling. Reset clears the stored value after modeled propagation; a previously delivered transaction is not retrospectively aborted.

Primitive model values remain in emitted `ExtModule` parameters. The `long-hold-bundling-v2` descriptor records individual bounds/model values, seven semantic endpoints and assumptions. Export validation checks worst-case margins and model/primitive agreement. Every positive sweep override is checked against these declared bounds before compilation; deliberate fault cases explicitly violate the contract. Earlier v1 exports described equal nominal control delays despite independently varied experiments. That mismatch is corrected: re-emit with v2 and the current compiler options. The qualified debug/retained-port route still applies; optimized/deduplicated production export remains unqualified.

## Executable evidence

After emitting the examples, run `python verification/run_longhold.py`. The default campaign requires:

- **628 controller cases:** one- and three-stage depths, each with 300 frozen seeds, uniform 1/10 ns delays, and 12 role corners. Data propagation, OR, three state cells and latch propagation vary independently from 1–10 ns per stage; both request guards stay at 40 ns. Source/sink pauses and returns vary from 1–60 ns. This is a declared bounded distribution, not a manufacturing model.
- Each case completes the 40-token stream, tests saturation with a pending offer, performs reset/restart scenarios and finishes with 49 deliveries, 47 completed returns and seven resets. Passive checks cover every channel's complete data hold, protocol order and token identity; reserved storage remains counted until return completes. Internal transitions must also pass the separate event graph. No observed violations or progress-deadline failures are permitted.
- **Three required faults:** remove admission matching → `PAYLOAD_MISMATCH`; remove Aout from the long-hold OR → `DATA_HOLD`; split the atomic input bubble → `CAPACITY_EXCEEDED`. Crashes, host timeouts and unrelated diagnostics fail qualification.
- **5,184 primitive state/delay checks:** all two-vector histories from reset for six direct symmetric/asymmetric configurations at two propagation delays. This includes the non-monotonic input sequence that distinguishes a three-input element from a binary tree.
- **776 typed transfers:** 260 Bundle-of-operands additions including carry/repeated operands, plus all 512 SInt(9) inputs and four repeats/boundaries through a signed/nested aggregate transform. Independent integer expectations check signed extension, packing and arithmetic while the sink stalls.

The normal `verification/run.py` also applies the existing independent functional corpus to narrow, wide, nested and pipelined long-hold exports: 22 additional positive tests. Scala checks reject invalid types/timing/cell configurations. Python controls corrupt topology, event order and timing declarations. The unrelated published-JAR consumer repeats one functional fixture, all primitive/typed checks, 32 controller cases and all three controller faults from its own generated RTL.

Reports under `target/verification/longhold` retain platform/simulator identity, export resolution, source/checker hashes, explicit delay assignments, generated benches, commands, per-case counters and logs. Uniform slow cases and deliberate failures retain VCDs; unexpected failing cases are replayed with waves. A failed/incomplete run overwrites the report status before execution, so stale success is not reused. See [qualification status](qualification.md) for executed hosts and CI.

The reference graph exploration, bounded simulation and mutation controls are complementary evidence. They are not a physical speed-independence proof, QDI claim, performance benchmark or frozen release campaign. Logical-channel separation, minimal dual-rail and explicit-clock bridges, and scalable observation/export remain the next architecture gate before CA-06 and L0 closure.
