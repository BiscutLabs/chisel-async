# Native Click pipelines

Chisel-async provides standard and phase-decoupled Click stages. Both use
`TwoPhase[T]` ports and edge-triggered registers driven by a local handshake
pulse. They capture data directly, without converting to four-phase handshakes.

| Component | Phase state | Initialization |
| --- | --- | --- |
| `ClickStage[A,B]`, `ClickBuffer[T]` | One flip-flop shared by input acknowledgement and output request | Empty |
| `PhaseDecoupledClickStage[A,B]`, `PhaseDecoupledClickBuffer[T]` | Separate input and output phase flip-flops | Empty, or one output-typed literal |
| `ClickFifo[T]` | Chain of standard stages | Empty; `depth` slots |
| `PhaseDecoupledClickFifo[T]` | Chain of phase-decoupled stages | Empty; `depth` slots |

All classes are in `chiselasync.bundled`. Each stage has one payload slot and
accepts a pure combinational transform whose result exactly matches the declared
output type. `ClickBuffer` is the identity transform. The existing `TwoPhase*`
classes retain their four-phase cores and adapters; choosing Click is explicit.

## How a stage fires

The input XOR reports a pending token. The output XOR reports an unacknowledged
output. An AND cell with an inverted output-comparator input generates a pulse
when input is pending and output is empty. Its rising edge captures the payload
and toggles the phase state. Phase feedback then lowers the pulse.

Standard Click uses one phase register for both sides. Phase-decoupled Click
uses two, triggered by the same pulse. Separate state allows the input side to
reset empty while the output side starts with a token. A two-slot ring with one
token needs that phase decoupling; it cannot be initialized using only the shared
phase states of ordinary Click stages.

These are the XOR/AND form in Sparsø, figure 9.4(b), and its phase-decoupled
extension in figure 9.11(b). The original Click paper describes the common
phase-state design and its equivalent sum-of-products circuit. See
[Peeters et al., ASYNC 2010](https://arc.cecs.pdx.edu/wp-content/uploads/2023/04/Peeters_Click_ASYNC2010.pdf)
and [Sparsø, chapter 9](https://arc.cecs.pdx.edu/wp-content/uploads/2023/04/JSPA_async_book_2020_PDF.pdf).

## Build and connect

Use `ClickTiming.Simulation` for a digital experiment:

```scala
val stage = asyncChild("increment") { domain =>
  new ClickStage(UInt(8.W), UInt(9.W),
    (x: UInt) => x +& 1.U(8.W), ClickTiming.Simulation, domain)
}
TwoPhase.connect(stage.in, in)
TwoPhase.connect(out, stage.out)
```

`asyncChild` supplies the parent's reset domain, connects reset and registers the
child contract. The surrounding ports must have matching payload types and share
that domain. Ordinary Chisel combinational logic implements the transform;
explicit primitive cells implement the controller.

## Initialize a feedback ring

Pass an output-typed literal to a phase-decoupled stage:

```scala
val seed = asyncChild("seed") { domain =>
  new PhaseDecoupledClickBuffer(UInt(8.W), ClickTiming.Simulation,
    initial = Some(7.U(8.W)), domain = domain)
}
seed.start.get := start
```

An initialized stage exposes `start: Option[Bool]`. Keep it low during reset and
until the entire connected reset domain has settled. Raise it once to release
the initial token, then hold it high until the next reset. Empty stages have
`start == None`. This barrier prevents a seeded token from circulating while
other stages are still resetting. Every reset reinstalls the literal and phase
state; it does not resume an interrupted iteration.

The runnable [ClickRing example](../examples/src/main/scala/chiselasync/examples/ClickRing.scala)
connects a seeded phase-decoupled buffer to a standard Click incrementer. One
token circulates through two storage slots. Its observation outputs are not an
additional handshake consumer.

## Primitives and timing

The new `EventRegister` captures a packed payload on a positive local-pulse edge.
`PhaseRegister` toggles its one-bit state on that edge and supports reset parity
zero or one. Both expose explicit reset and trigger pins as versioned `ExtModule`
boundaries. Comparators, the firing AND and delay buffers reuse existing cells.
Neither stage requires a C-element or mutex. Arbitrated routing still needs a
mutex and is a separate component.

`ClickTiming` records independent min/max/model bounds for both comparators,
the firing gate, both phase registers, the payload register and the whole
transform path. Its other fields are:

| Field | Obligation |
| --- | --- |
| `requestDelay` | Input admission follows the entire data path plus setup allowance |
| `acknowledgeDelay` | Upstream reuse waits for feedback to settle and payload hold to finish |
| `outputDelay` | Output request follows payload Q and allows feedback to settle before a fast acknowledgement |
| `setup`, `hold` | Stable-data intervals at the payload register's actual trigger pin |
| `pulseHigh`, `pulseLow` | Strict minimum high and low widths at each local trigger pin |
| `clockSkew` | Maximum additional propagation from firing gate to any register's trigger |

Let `P` be the larger phase-register maximum, `C` the larger comparator maximum,
`F` the firing-gate maximum, and `S = clockSkew + P + C + F`.
The constructor requires:

- `requestDelay > data.max + setup`.
- `min(inputPhase.min, outputPhase.min) + min(inputCompare.min, outputCompare.min) + fire.min > pulseHigh + clockSkew`.
- `acknowledgeDelay > max(S + pulseLow, clockSkew + hold)`.
- `outputDelay > max(S + pulseLow, clockSkew + payload.max)`.

The independent minima cover the standard variant's shared phase register,
which feeds both comparators. Both variants use this conservative policy even
though standard Click instantiates only one phase register. The simulation preset uses independent 1–10 ns
cell delays, an 11 ns request guard and 32 ns acknowledgement/output guards.
Those broad bounds support delay experiments; they are not a performance claim.

## Test and export

Use the published `AsyncTest.check` with `Input.literals` and `Output.literals`,
just as for other two-phase components. It randomizes each Click cell inside its
declared bounds and checks actual register-pin setup, hold, pulse width and clock
distribution. `PinDelay("payload", "trigger", bounds)` adds distribution skew;
`PinDelay("payload", "d", bounds)` exercises late data. Seeded starts and directed
reset scenarios use `AsyncTest.run` to drive the optional start port explicitly.

The [consumer tests](../examples/quickstart/src/test/scala/ClickTestSpec.scala)
exercise 300 per-cell configurations of each three-stage FIFO, typed transforms,
stalls, reset, initial-token order and precise must-fail timing controls. The
[ring campaign](../verification/test_click.py) exercises another 300 configurations,
80 circulations in each of two reset epochs, and missing-token/data-corruption
controls. It checks an independent expected integer sequence.

The [one-command qualification wrapper](contributing.md) runs these suites and
records both consumer FIFO campaigns. To focus on the ring and export checks
after setting up the contributor toolchain:

```text
python tools/sbt.py "examples/runMain chiselasync.examples.EmitClick target/generated"
python -m pytest verification/test_click.py -q
```

`ExportDesign` preserves a `click-bundling-v1` descriptor and a passive netlist
marker. The strict validator checks its parameters and actual cell wiring through
optimized and deduplicated RTL. `AsicMapping` inventories every required cell
specialization for a supplied technology binding.

The current `TimingConstraints` OpenSTA flow handles propagation paths, not
Click's local-clock pulse and aperture analysis. It rejects Click contracts with
`CLICK_REQUIRES_PULSE_AND_APERTURE_ANALYSIS` rather than emitting an incomplete
check. A hardware implementation needs characterized register/gate/delay views,
setup/hold and pulse analysis, reset recovery/removal, and routed skew checks.
The packaged models and simulation preset do not provide physical timing closure.

Native Click routing components—fork, join, mux, demux and arbiter—are not included
in this initial stage/FIFO family. Existing `TwoPhase*` routing remains usable
with its documented adapter overhead and timing policy.
