# Testing your design

Test your chisel-async design from ScalaTest with `AsyncTest` for four-phase
asynchronous circuits or ChiselSim for clocked harnesses. Use event simulation to exercise
propagation delays and four-state behavior. In either case, check completed token
transfers and expected results as well as successful elaboration.

## Test an asynchronous design from the JAR

`chiselasync.testing.AsyncTest` runs a clockless four-phase design in Icarus from
ScalaTest. It ships inside the library JAR, needs `iverilog` and `vvp` on PATH, and
does not require Python, cocotb, C++ compilation or a repository checkout. The
[quickstart test](../examples/quickstart/src/test/scala/AsyncDesignSpec.scala)
shows how to use it in a standalone project:

```scala
import chiselasync.testing.AsyncTest
import chiselasync.testing.AsyncTest.{Input, Output}

AsyncTest.check(new AddPipeline,
  Seq(Input("in", Seq(Map("in_bits_a" -> BigInt(3), "in_bits_b" -> BigInt(5))))),
  Seq(Output("out", Seq(Map("out_bits" -> BigInt(8))))))
```

Streams run concurrently with seeded source/consumer pauses. Maps name every
flattened payload leaf; values are unsigned bit patterns, with signed leaves
encoded in two's complement. The helper checks channel coverage, leaf widths,
exact output sequences, stable held data, handshake order, and bounded completion.
Empty streams, skipped outputs, simulator errors and missing completion markers fail.

Each seed also selects independent cell delays. Seeds 1/2 exercise the minimum
and maximum corners; other seeds use `java.util.Random`. Long-hold cell and data
delays stay inside their exported bounds; request/output guards remain fixed.
Routing cells use the declared test envelope (default 1–10 ns). Conversion
boundaries retain nominal delays; the separate phase/encoding campaigns exercise
their additional closure guards. This helper currently requires four-phase
top-level channels, not arbitrary two-phase/dual-rail or clocked top-level IO.

Pass `directory` to choose where exported RTL, contract, per-seed `delays.json`,
testbench, compile log, simulation log and transfer-count `result.json` are retained.
Otherwise the helper creates a temporary directory and returns its per-seed paths.
Use a fresh directory for each campaign to preserve earlier evidence. Simulator
failures report the log path; a passing result requires observed output transfers.
The helper elaborates once per call. Custom
concurrent/reset scenarios use `AsyncTest.run` with an SV body; its time unit is
1 fs. Monitors settle for 1 fs, so custom drivers must leave handshake states
observable for longer than that rather than collapsing multiple phases in one
timestamp. It is not a delta-cycle glitch detector.

`AsyncTest` checks behavior with modeled cell delays and ideal wires. Run the
structural export validator separately to check timing metadata and probe bindings.
Physical timing verification also requires the mapped cells and wires.

Run `sbt "testOnly AsyncDesignSpec"` in the standalone quickstart to test the
adder and GCD. `RoutingSpec` adds 300 configurations each for mux and registered
fork, independent payload oracles, unselected-input checks, reset recovery and
required diagnostic failures. Sixteen further configurations exercise the new
two-phase mux/fork through explicit converters. The consumer check includes these suites on both
native CI hosts.

## Clocked ScalaTest with ChiselSim

The standalone [quickstart test](../examples/quickstart/src/test/scala/BridgeSpec.scala)
mixes `AnyFunSuite` with `chisel3.simulator.scalatest.ChiselSim`, calls
`simulate(new BridgeHarness)`, and uses `poke`, `expect`, and `clock.step`.
The harness is a normal Chisel `Module` that wires the bridge's explicit clock/reset.

On a configured Linux host, from the quickstart project:

```text
sbt test
```

The test resets the design with external handshake drivers idle, waits through
local reset release, and transfers four values including duplicates. It holds
acknowledgement low to test output stalls, then checks payload retention through
request return before lowering acknowledgement. Every wait has a deadline and
the test requires actual completed traffic.

Extend this pattern with an independent software function for transformed values,
a FIFO of expected transaction IDs, multiple stalls and reset/restart cases. Do
not compute expected outputs by reading the same internal state or duplicating
the controller's Boolean equations.

The repository's larger
[BridgeSimulationSpec](../verification/chiselsim/src/test/scala/chiselasync/BridgeSimulationSpec.scala)
adds both bridge directions, wide payloads, memory transactions, events and two
deliberately corrupted payload observations. It runs both against source and a
locally published JAR. ChiselSim is included with Chisel; no chiseltest dependency
is needed. Upstream documents `simulate` and `simulateRaw` in its
[testing guide](https://www.chisel-lang.org/docs/explanations/testing).

## Native Windows ChiselSim

The tested Chisel 7.16.0/Verilator 5.046 combination needs the repository's
[`svsim_windows.py`](../tools/svsim_windows.py) adapter for MSYS2 build paths and a
small POSIX compatibility header. It does not patch the Chisel JAR or HDL behavior.
`python tools/sbt.py simulation/test` configures it for the repository suite;
`python tools/check_quickstart.py` configures it for the standalone example check.

Use the [contributor environment](contributing.md#prerequisites) for these commands.
The adapter is currently repository tooling. To run ChiselSim in a standalone
Windows project, you need the same build integration; `sbt test` alone is not
enough. Python runs the adapter and is not a library runtime dependency.

Keep simulator workspaces short and free of spaces. Set `CA_CHISELSIM_DIRECTORY`
for the included tests to a short absolute path if necessary. A consumer project
can have spaces in its path while placing the simulator workspace elsewhere.
Windows generated layer filenames also count toward path-length limits.

## Asynchronous event tests

Use Icarus 13 with 1 fs resolution for the packaged delayed and four-state views.
Emit and validate your design before simulation. Use the generated file inventory
and packaged resources rather than copying or rewriting primitive models. The
repository's runners handle more extensive fixtures, observers, raw traces and
independent replay. Use the JAR's `AsyncTest` for a consumer-owned four-phase
design; use these campaigns to test additional encodings and timing assumptions.

For a custom circuit, adapt a relevant
[executable example and campaign](examples.md). Drive offers legally, keep passive
observers active during stalls/return, and check completed tokens with a separate
oracle. Don't substitute Verilator clock stepping for the asynchronous delay sweep.

Test each of these properties separately; passing one does not establish the others:

| Property | Exercise | Check independently |
| --- | --- | --- |
| Payload function | All small values, walking bits, signed/nested/wide types | Software arithmetic/table and exact widths |
| Token identity | Equal consecutive payloads | Count/ID queue, no duplicate or lost transfers |
| Backpressure | Stall each consumer; fill/drain storage | Stable data, reservation, no early reuse |
| Handshake order | Delayed source return and delayed acknowledgement return | Encoding-specific legal event transitions |
| Reset | Partial offer, stalled full token, return phase, then restart | Abort only undelivered work; demonstrate new post-reset deliveries |
| Timing | Independent per-cell delays and targeted skew/aperture bounds | Recorded inequalities and event-order constraints |
| Dual-rail indication | Partial valid and partial spacer waves | No early word completion/withdrawal, no illegal rail codes |
| Arbitration | Simultaneous/pending requests, several policies and seeds | One winner at a time; no dependence on a particular tie result |
| Memory/event effects | Stalls, reset after commit, snapshot/clear coincidences | Byte-array or event-set oracle and effect counts |

## Negative controls and evidence

A useful negative control first passes an active baseline, changes one behavior,
and then fails the intended assertion. Examples include corrupting payload,
dropping a completion input, losing an event when clearing, or acknowledging before
history closure. A timeout, compiler crash or unrelated assertion cannot stand in
for the expected diagnostic.

Retain tool versions, source/checker hashes, test inventory, seeds, time units,
logs, traces, transfer/abort counts and actual failures. Check that expected tests
really ran; fail on empty suites, missing witnesses or inactive observers.
[Trace formats](trace-format.md) explain the evidence conventions. These are
bounded experiments, not a formal proof of every schedule or a physical sign-off.

## Test the repository

For the complete campaign, use `python tools/qualify.py` after
[platform setup](contributing.md). For focused edits:

```text
python tools/check_docs.py
python tools/sbt.py test
python tools/sbt.py simulation/test
```

These commands have different scopes. Running only API tests does not qualify
protocol, delay, export, or packaging changes. The contributor guide maps each
change to the corresponding runner and explains how to keep evidence from failures.
