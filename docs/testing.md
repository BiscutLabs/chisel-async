# Testing your design

Choose a simulator for the behavior you intend to test. Use a clocked harness for
ChiselSim and an event simulator for asynchronous propagation and four-state
experiments. A successful elaboration or a test with no transfers is not evidence
of correct protocol behavior.

## First ScalaTest test

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
The adapter is currently repository tooling, so a standalone Windows consumer
needs equivalent integration; a plain `sbt test` is not advertised as qualified
there. Python is an adapter requirement on this route, not a library runtime dependency.

Keep simulator workspaces short and free of spaces. Set `CA_CHISELSIM_DIRECTORY`
for the included tests to a short absolute path if necessary. A consumer project
can have spaces in its path while placing the simulator workspace elsewhere.
Windows generated layer filenames also count toward path-length limits.

## Asynchronous event tests

Use Icarus 13 with 1 fs resolution for the packaged delayed and four-state views.
Emit and validate your design before simulation. Use the generated file inventory
and packaged resources rather than copying or rewriting primitive models. The
repository's runners handle fixtures, compilation, observers, evidence and replay;
they are not yet a general published Scala or Python testkit.

For a custom circuit, adapt a relevant
[executable example and campaign](examples.md). Drive offers legally, keep passive
observers active during stalls/return, and check completed tokens with a separate
oracle. Don't substitute Verilator clock stepping for the asynchronous delay sweep.

Useful test dimensions are genuinely different obligations:

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
