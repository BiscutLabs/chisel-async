# Experimental GF180 Mutex

This directory provides an **experimental schematic and layout**, not a qualified ASIC cell.
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
mapper. The optional layout flow below generates GDS and distributed RC, with hashes in
its run receipt. LEF and conditional Liberty characterization remain open. The
SPICE subcircuit is the authoritative schematic connectivity. All transistor
sizing is experimental.

Before a physical binding is accepted, review the circuit, complete load/slew,
release/handover and reset characterization with receiver thresholds, establish
the system reliability target and variation methodology, implement matching and
well/layout constraints, run DRC/LVS, and repeat checks on the extracted netlist.
The five-corner schematic sweep deliberately does not claim Monte Carlo, aging,
noise, supply-collapse behavior or post-layout qualification. A finite successful
sweep cannot prove zero metastability risk.


## Exploratory layout

`layout.py` places the unchanged 46-transistor circuit with shared well contacts
and routes it on Metal2–4. Its 28 × 35.28 µm integration outline costs
**987.84 µm² (0.00098784 mm²)**. Device halves are mirrored; routes are not
assumed electrically matched. Internal net labels make extraction auditable.
No generated binary or PDK is shipped, and no mapping binding is enabled.

The external-tool flow uses GF180D (5LM, 11K top metal). Reproduced inputs:

| Input | Revision |
|---|---|
| [open_pdks](https://github.com/fossi-foundation/open-pdks) | `a7f707ac58e5c55cf8d6f461aea63449c20a4f06` |
| [GF180 physical-verification decks](https://github.com/efabless/globalfoundries-pdk-libs-gf180mcu_fd_pv) | `05e7b6adf19edf942969c1c9625f02fd87874f06` |
| Magic / Netgen / KLayout | 8.3.623 / 1.5.316 / 0.30.7 |

Prepare `gf180mcuD.tech`, `gf180mcuD.tcl`, `common.tcl` and the Netgen setup
from that open_pdks revision. Preprocessor definitions: `TECHNAME=gf180mcuD`,
`METALS5`, `MIM`, `THICKMET1P1`, `HRPOLY1K`; use the installation's actual
`STAGING_PATH`. Run in the native environment containing the external tools:

```text
python integrations/gf180/mutex/check_layout.py --magic-pdk /path/to/prepared/magic --pv-pdk /path/to/gf180-pv --netgen-setup /path/to/gf180mcu_setup.tcl --magic /path/to/magic --klayout /path/to/klayout --netgen /path/to/netgen --output build/mutex-layout
python integrations/gf180/mutex/layout_samples.py --model-dir /path/to/models --circuit build/mutex-layout/extracted-rc.spice --lvs-circuit build/mutex-layout/ca_mutex_gf180_candidate.spice --output build/mutex-rc --jobs 8
```

`check_layout.py` checks exported GDS with the foundry FEOL, BEOL, off-grid and
connectivity rules, and uses both KLayout and Netgen LVS. KLayout receives an
equivalent MOS-element schematic view and simplifies parallel devices on both
sides for LVS only. The analog view retains every transistor. A thin wire and a
wrong transistor gate must fail their respective checks. RC collapse must preserve
device terminals, dimensions and diffusion geometry. One receipt hashes the run's
inputs, tools and outputs.

The foundry check reports 649 rule categories with zero violations. It caught
20 implant-width errors at the initial well edges that Magic missed; expanding
the well within the existing outline fixes them. Extraction contains 46 MOS,
303 resistors and 451 capacitors. The largest 1.93 Mohm branch belongs to the
substrate network and remains in simulation. RC values are nominal, not corner
bounds; density/fill, antenna and latch-up signoff are still excluded.

`layout_samples.py` uses the existing grant-safety and sequence oracles on the
external pins with 5/50 fF loads and 50 ps/5 ns input slews. It tests both
handover directions, contention, reset/rearm, and a half-timestep repeat.
Asserting reset on a live grant is a destructive POR test, never a legal way
to stop an operational handshake. Finite samples do not establish reliability,
a maximum arbitration time, mismatch tolerance or immunity to coupled noise.
LEF, conditional uncontended/reset/release Liberty arcs, min/max RC, variation,
noise and the system reliability target remain required before adoption.


The first reviewed run passed 462 extracted-RC samples across the five PVT
corners, including two half-timestep repeats. Sampled uncontended propagation
was 0.334–1.325 ns, handover quiet time was at least 0.891 ns, and active-reset
clearance was at most 2.094 ns. The half-step timing changes were below 0.041 ps.
These are sample ranges with nominal RC, not guaranteed timing bounds.
All 20 simultaneous-request reset cases had resolved before reset assertion;
reset from an unresolved metastable state therefore remains untested.

After changing a checker, `layout_samples.py --replay /path/to/report.json
--output /path/to/fresh-output` rechecks the saved waves without new SPICE runs.
It verifies the complete case inventory, original execution, source/deck/log/wave
hashes and reconstructed stimulus, then recomputes the half-step comparison.
