# Mutex ownership and physical use

`chiselasync.primitives.Mutex` accepts two independent, persistent request levels
and returns at most one grant. Its public pins remain `reset`, `request[1:0]`
and `grant[1:0]`. It has no clock and does not transport a payload. A native
Click owner can use these control levels without converting its payload channel.
`TwoPhaseArbiter` is a separate component that uses phase conversion internally.

## Owner protocol

1. Establish and retain everything needed to service a request before raising it.
   Keep that request high until its grant has been observed and the associated
   operation has completed. Pending requests cannot be withdrawn in physical use
   unless a particular binding explicitly characterizes that extension.
2. A granted request retains its grant while high. A later competing request
   cannot preempt it. The loser remains pending; either contender may win a tie.
3. Lower the completed request, then **observe its grant low before reasserting
   it**. A short low pulse can leave the old grant asserted. Counting a new
   transaction from that retained grant would reuse an old decision.
4. Handover passes through both grants low. Any minimum quiet interval required
   by the receivers belongs in the loaded physical binding's contract; the
   public interface does not specify a numeric interval.
5. With unresolved contenders, both grants remain inactive and all effects
   controlled by grants remain inactive. A system must tolerate an arbitrarily
   long unresolved interval. Do not use a watchdog timeout to force a winner.

A grant reserves ownership. It is not automatically a payload acknowledgement,
a capture pulse, or proof that downstream work has finished. The enclosing owner
must complete its capture, hold and return obligations before releasing the
request. A stop contender must remain pending through closure/rebase. Capturing
a stop level does not promise detection of an arbitrarily short input pulse.

`FourPhaseArbiter` already enforces rule 3: its input acknowledgement falls only
after the corresponding grant falls, so a conforming four-phase producer cannot
reuse that request before grant release.

## Reset and rearm

Reset aborts the model's current decision; it cannot undo a delivered effect.
For physical use, assert the cell's local electrical reset only during the
declared supply/bootstrap condition or after joined electrical and source/sink
quiescence. An ordinary valid-rail reset request must close admission and drain
or safely park the connected owners before it becomes that electrical reset.
Do not connect an asynchronous stop directly to this reset to truncate a
committed pulse or erase retained payload/protocol history.

The Mutex has **no epoch memory**. The owners must clear/rebase old request
levels and their protocol history before releasing local reset. Start the new
epoch with both requests low and both grants observed low, respecting the
binding's reset recovery/removal and rearm envelope. A request held high across
reset is a live request after release and can be granted again. Quiescence may
include a safely parked, unaccepted offer; requiring that offer to be
acknowledged first can deadlock cancellation. The owner, rather than this
primitive, defines that parking and later rebase protocol.

## Digital model and checks

`RESOLVE_FS`, `RESOLVE_MAX_FS`, `MutexPolicy` and `SEED` describe a finite
simulation. They are not physical minimum/maximum resolution times, priorities,
fairness guarantees or analog filter specifications. The randomized model's
cancellation/re-entry experiments exercise that model; they do not authorize
request withdrawal or grant reuse in an uncharacterized physical circuit.

Run the persistent-request and owner-obligation campaign with:

```text
python verification/run_mutex_contract.py --output target/verification/mutex-contract
python -m unittest discover -s verification -p test_mutex_contract_runner.py
```

The campaign uses the packaged model directly, all four policies, seeded ties,
held winners, zero-grant handover, reset/rearm and a long unresolved interval.
Deliberate owner and output faults must fail at their exact diagnostic IDs.
The unresolved-interval assertion checks the behavioral model's configured delay;
it does not specify a physical resolution bound. The sampled winner-retention
control corrupts the saved reference; separate output-fault controls exercise the
continuous held-grant monitor. Full qualification runs this campaign and the
GF180 waveform-checker unit tests without requiring a PDK or ngspice.
These finite checks establish digital behavior and check the harness. They do
not prove analog exclusion or a maximum resolution time. Existing randomized
model stress remains in `verification/run_mutex.py`.

## Technology binding obligations

A physical implementation needs an arbitration storage core and an analog
metastability containment filter before either grant can drive ordinary logic.
An unfiltered NAND latch, synthesized priority network, or simulation delay is
not a replacement. Preserve the recognized custom cell and its provenance.

Characterization must record input slew, supply/PVT and variation assumptions,
output load and receiver thresholds, grant slew, uncontended propagation,
release/handover, reset assertion and recovery/removal. Contention resolution
must be reported separately from bounded uncontended paths. Check unresolved
analog states, near-coincident contenders, long persistence, slow edges, loaded
release, reset and rearm. Include the schematic and model hashes, then layout,
DRC/LVS and extracted circuit hashes when available.

The [GF180 candidate](../integrations/gf180/mutex/README.md) is optional,
experimental collateral. It does not enable a qualified mapping automatically.
A finite SPICE sweep is evidence within its declared envelope, not proof of zero
metastability risk. Reliability targets and statistical assumptions require a
system-level decision and further characterization.
