# Building bundled-data pipelines

Bundled-data channels carry an ordinary typed data bus plus request and
acknowledgement. Request timing must account for when the corresponding data is
safe to capture. Use the [quickstart](getting-started.md) for a complete working
type-changing stage and two-stage pipeline.

## Timing policy

Start with `BundledTiming.Simulation` for a digital experiment. It provides
1–10 ns cell bounds, a 10 ns data budget, and derives strictly larger request and
output guards. `BundledTiming.simulation(cellMin, cellMax, dataMax)` adjusts those
three values and recomputes the guards. Neither preset is a physical speed grade.

Every structural stage takes an explicit `BundledTiming`. `FunctionalOnly` names
the zero-delay experiment; it is not an implicit default. For delayed digital
models, construct `BundledTiming.Digital`:

| Field | Meaning |
| --- | --- |
| `dataDelay: DelayBounds` | Entire transform/input-glue path before storage, with min/max/model values |
| `controls: ControlDelays` | Independent `a`, `b`, `acknowledge`, and `longHold` bounds |
| `latchDelay: DelayBounds` | Payload latch propagation envelope |
| `matchedDelay: ModelTime` | Request admission guard |
| `outputDelay: ModelTime` | Output-offer guard |

Each model value lies within its declared bounds. Digital control and latch lower
bounds must be positive. `matchedDelay > dataDelay.max`, and
`outputDelay > 2 * controls.worst + latchDelay.max`; equality is rejected.
`controls.worst` is the largest maximum across the four control cells, not an
assumption that all four delays are equal.

The long-hold topology additionally assumes that rising output acknowledgement
reaches the long-hold OR before falling state A reaches its other input. Ideal
wires provide this ordering only in the modeled experiment. The exporter records
that fork-arrival obligation. A larger data guard cannot repair a violated
control-fork assumption.

Plain Chisel logic inside a transform, select decoder, merge mux or initial-token
mux has no intrinsic delay in RTL simulation. Its mapped delay belongs inside the
declared whole-path data budget. Export records these paths; physical timing tools
must eventually check them against mapped logic. Do not add the same budget twice
or interpret the simulation's ideal glue as zero-delay silicon.

## Type-changing transforms

`FourPhaseStage[A, B](inGen, outGen, transform, timing, domain)` accepts a pure
combinational `A => B`. Output type, shape and width must exactly match `outGen`.
Use explicit widening, truncation or signed conversion when intended. The
quickstart uses `+&` to produce a 9-bit sum from two 8-bit operands.

Avoid state, implicit clocks, and unregistered child hardware inside a transform.
Place stateful operations in separate components with declared contracts. Ordinary
Chisel optimization is appropriate for datapath expressions; controller cell
boundaries carry stronger assumptions and must be preserved.

## Storage and initialization

`LongHoldBuffer` is the identity transform. `FourPhaseFifo` chains such storage
with exactly the requested positive depth. Output backpressure propagates once
all slots are reserved. Count reservation through acknowledgement return, not
just until delivery.

`initial: Seq[T]` contains fully specified, exactly typed literals and cannot
exceed depth. Initialization injects those values before external acceptance;
they consume existing capacity. Each coordinated reset aborts old outstanding
work and reinstalls the initial sequence. A standalone `InitialTokens` exposes
`done`, which asserts after its last handshake returns completely.

An empty feedback cycle needs an initial token before anything can move. A full
cycle may need spare capacity to make progress. Build a ledger for the actual
network; local component correctness does not prove deadlock freedom for an
arbitrary cyclic composition.

## Fork, join, mux, demux, and merge

`FourPhaseFork` broadcasts one token to every output. It adds no storage: the
producer must retain data until every branch has completed. A fast branch may
deliver before the producer sees acknowledgement, so reset must not erase that
branch's completed delivery from the scoreboard.

`FourPhaseJoin` buffers each operand independently and pairs tokens by position.
Its output is `Joined[A, B]` with `left` and `right` fields. Buffer counts are
operand counts, not two independent output-tuple slots.

`FourPhaseRegFork[A,B,C]` captures the two results of `A => (B,C)` in one shared
slot, then broadcasts them on `left` and `right`. Both branches must return before
the slot can be reused. It resets empty and does not support independently
initialized branch tokens.

`FourPhaseMux` has `in: Vec`, `select: FourPhase[UInt]`, and `out`. Each selector
chooses one input; unselected offers remain pending without acknowledgement.
A captured selector and the chosen input rendezvous in C-elements, including
both return transitions. The selector may arrive before or after the data.
There is one selector slot and one output data slot; selector acceptance can
precede data acceptance. This is controlled selection, not arbitration or a join
over every input. See the [GCD example](examples.md#gcd-with-controlled-feedback).

`FourPhaseDemux` takes `Selected[T]` (`index`, `data`) and captures both routing
choice and data. Only the selected output requests; its backpressure holds the
transaction. Every index must satisfy `index < destinations`.
`FourPhaseSelect` remains as a deprecated compatibility name. See the
[terminology and comparison](component-terminology.md) for differences from
components that use a separate selector channel.

`FourPhaseMerge` assumes only one input handshake is active at a time, including
return-to-idle. It does not choose a priority when inputs overlap. Its simulation
guard diagnoses overlap. This is useful for branches already known to be exclusive.

For independent producers, use `FourPhaseArbiter`. Its two-client MUTEX chooses a
winner, return interlocks prevent overlapping merge inputs, and a buffer retains
the chosen payload. Requests must remain asserted with stable data until serviced.
Policies `PreferFirst`, `PreferSecond`, `Alternate` and `SeededRandom` control the
finite simulation model. Seeded mode also samples resolution time between
`resolution` and `resolution + resolutionJitter`. Test both winners and retain
seeds; never depend on tie order. These policies do not guarantee bounded physical
arbitration latency or general starvation freedom.

## Two-phase interfaces

The `TwoPhase*` family composes the same cores with sequential phase adapters.
`TwoPhaseToFourPhase` and `FourPhaseToTwoPhase` provide explicit buffered boundaries.
Their public capacity remains one token; internal protocol state is not extra
advertised queue space.

`PhaseTiming` declares cell bounds, return delay, history-closure bounds and
post-toggle request delay. `returnDelay > cells.max` and
`requestDelay > historyClosure.max`. History closure includes request distribution,
skew and aperture allowance independently of latch data-to-Q delay. A receiver
must not answer a toggled request before that history latch is safely closed.

The two-argument convenience constructor uses the cell envelope for history
closure and the return delay for the request guard. Use all four arguments when
the closure path has a different bound. See [timing and export](timing-and-export.md)
for how these obligations are carried and checked.
