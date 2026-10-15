# Experimental GF180 Mutex

This directory provides a **schematic candidate**, not a qualified ASIC cell.
`mutex.spice` has a reset-qualified cross-coupled NAND core, a differential
metastability filter, and a loaded-output interlock. The filter topology
follows [Zhang et al., ASYNC 2015, figure 3](https://www.inf.pucrs.br/~calazans/publications/2015-ASYNC-Mutex.pdf).
Reset gating, transistor dimensions and the output interlock are trial adaptations;
the paper does not qualify those choices for GF180.

The PMOS source of each filter branch connects to the opposite decision node.
When the two decision voltages are close, the PMOS devices do not supply a high
grant and the NMOS devices discharge the filter nodes. This is a transistor-level
analog containment structure, not synthesized priority logic. Its behavior still
depends on device, load, voltage, temperature and mismatch. Internal nodes cannot
be used as grants or clocks.

The 46-transistor revision 3 senses each actual loaded grant through a
low-threshold tied-input NOR4 and permits the opposite filtered winner only
after that sense reports low. A simple buffered revision failed handover with
50 fF on the old grant and 5 fF on the new grant. The interlock addresses that
measured failure; its own analog threshold and delay also need characterization.
The runner checks both symmetric and asymmetric endpoint loads without relaxing
the receiver's 0.3 VDD low and 0.7 VDD high thresholds.

The candidate has the existing logical `reset`, `request[1:0]` and `grant[1:0]`
interface plus explicit physical VDD/VSS pins. It has no physical policy, seed or
resolution-delay parameters. Follow [the owner contract](../../../docs/mutex.md):
valid-rail reset waits for joined quiescence, old contenders are cleared before
reset release, and each requester observes grant low before reuse. Asserting
reset during an active grant intentionally aborts the circuit; it cannot preserve
a downstream committed pulse. Do not use that as a stop implementation.

## Reproduce schematic samples

Supply a GF180 model installation containing `design.ngspice` and
`sm141064.ngspice`, and an ngspice executable. Neither is installed by this tool.
Run from any native Python environment supported by those tools:

```text
python integrations/gf180/mutex/characterize.py --model-dir /path/to/models --output target/gf180-mutex-r1
python integrations/gf180/mutex/check_samples.py target/gf180-mutex-r1/report.json --output target/gf180-mutex-r1/hold-audit.json
python integrations/gf180/mutex/replay_samples.py target/gf180-mutex-r1/report.json --output target/gf180-mutex-r1/replay.json
python integrations/gf180/mutex/reset_samples.py --model-dir /path/to/models --output target/gf180-mutex-reset-r1
python integrations/gf180/mutex/clear_samples.py --model-dir /path/to/models --output target/gf180-mutex-clear-r1
python integrations/gf180/mutex/handover_controls.py --model-dir /path/to/models --output target/gf180-mutex-handover-r1
python -m unittest discover -s integrations/gf180/mutex -p "test_*.py"
```

The runner uses five explicit PVT corners, loaded grants, contender skew,
independently varied input slew, held-winner/release/reset sequences and direct
analog filter probes. The report records circuit, checker, models, executable,
deck and log hashes, and sampled waveforms. It separates uncontended/release
measurements from contention observations. No contention sample becomes a
maximum resolution bound. Fresh output directories preserve failed experiments.

The main campaign requires retained valid-high grants, request-qualified grant
onset, exclusion, complete waveform identity/time coverage and bounded sampling
gaps. `check_samples.py` replays those hold checks and partial/runt-grant checks
from the recorded waveform. `replay_samples.py` requires the exact 455-case
inventory and rechecks the unchanged circuit, decks, logs and waveforms with all
current mandatory oracles, including persistent contenders and invalid partial
grants. It is a checker replay and records zero new SPICE simulations.
`reset_samples.py` measures reset
clearance and deliberately keeps an old request high across reset to demonstrate
that it is granted again. That destructive stimulus characterizes the cell; it
does not authorize an owner to reset active work or retain stale requests.
`clear_samples.py` samples the interlock's DC low-sense transfer curve.
`handover_controls.py` compares the actual interlock with a deliberate bypass
under the known asymmetric load at all five corners. The bypass must trigger
the exact grant-overlap diagnostic; a missing-quiet-interval diagnostic can also
result from the same fault.

## Binding and qualification status

The generic GF180 preparer continues to list Mutex as missing. This candidate is
not yet available as a supported binding and must not be silently selected by a
mapper. There is no layout, LEF, GDS, extraction or Liberty deliverable; therefore
there are no layout hashes to report. The SPICE subcircuit is the authoritative
schematic connectivity. All transistor sizing is experimental.

Before a physical binding is accepted, review the circuit, complete load/slew,
release/handover and reset characterization with receiver thresholds, establish
the system reliability target and variation methodology, implement matching and
well/layout constraints, run DRC/LVS, and repeat checks on the extracted netlist.
The five-corner schematic sweep deliberately does not claim Monte Carlo, aging,
noise, supply-collapse behavior or post-layout qualification. A finite successful
sweep cannot prove zero metastability risk.
