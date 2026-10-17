# Passive whole-transform allowances

`DataAllowance.Passive` opts a stage into an unmasked, reset-free simulation
allowance. It retains the existing whole-transform inertial delay in simulation;
`AsicMapping` replaces the allowance with `assign q = a`. The physical datapath
contains the real transform and wires, with one matched request delay per stage.
It does not contain a buffer or reset gate for every payload bit.

```scala
import chiselasync.metadata.{BundledTiming, ClickTiming, DataAllowance}
val bd = BundledTiming.Simulation.copy(dataAllowance = DataAllowance.Passive)
val click = ClickTiming.Simulation.copy(dataAllowance = DataAllowance.Passive)
```

Pass these policies to the usual stage constructors. BD stages, buffers, FIFO
storage, Join operand storage, RegFork storage and initial-token data paths inherit
the policy. Native standard and phase-decoupled Click stages and their FIFOs also
inherit it. Reset still initializes controllers, phase and payload storage as
before, including seeded tokens. No control guard, protocol, capacity, clock or
synchronizer changes. The default is `DataAllowance.Resettable`, preserving the
existing `ControlGate` data model.

For a custom data-only path, `chiselasync.primitives.PassiveDataAllowance` has a
public packed external boundary `(width, delay)` with `a` and `q` ports. The typed
helper `PassiveDataAllowance(owner, id, data, delay, resetEndpoint)` preserves
UInt, SInt, Bool, Vec and Bundle types and registers the primitive contract.
The endpoint identifies the enclosing protocol reset domain; the primitive has
no reset pin. Clock, reset and probe values are rejected as payloads. A payload's
bound input/output direction does not alter its type.

## Ownership and timing contract

The payload has **no validity guarantee while its handshake is idle or reset**.
Input changes, X and Z values propagate through the allowance. Consumers may
compute speculatively, but payload-dependent capture, side effects, requests,
acknowledgements and persistent state must be qualified by their owning handshake.
A reset gate is not implicit in this primitive. Audit every fanout before opting
an existing instance into the policy, including initialization muxes and data
that reaches control decode or a clocked domain.

`DELAY_FS` is a **simulation-only whole-transform propagation allowance**, counted
once. It is neither a physical delay-line target nor extra delay to add after the
real transform. Physical adoption must independently check:

- Maximum transform arrival plus setup against the earliest capture leaf.
- Minimum source reuse through the real ACK/return and transform against the
  latest capture leaf plus hold. Zero physical allowance supplies zero hold credit.
- Capture fanout/spread, ACK ordering, pulse widths and ordered reset release.

Perform these checks per corner with the implementation's variation policy and
wire model; retain unresolved full-route obligations explicitly. Add hold repair
only where actual minimum-path checks require it. Never use an allowance as a
request, ACK, pulse, reset or isolation primitive.

## Export and verification

The model identifier is `ChiselAsyncPassiveDataAllowance_v1`, with exact parameters
`WIDTH` and `DELAY_FS` and only `a`/`q` pins. Strict export validates this shape and
the enclosing reset-domain identity. Existing transform, storage and handshake
binding checks remain mandatory. `AsicMapping` emits the alias directly without
a technology-cell binding or `dont_touch`, and retains the timing intent.
`TimingConstraints` does not preserve the alias as a physical cell. Its existing
transform-path max/min queries remain applicable; its current generic lowering
still does not close all native pulse/aperture requirements.

Run:

```
python tools/sbt.py 'testOnly chiselasync.PassiveAllowanceSpec chiselasync.ClickSpec chiselasync.LongHoldSpec'
python verification/run_passive_allowance.py --output build/passive-allowance-events
python -m pytest verification/test_passive_allowance.py verification/test_export_pairing.py verification/test_export_extensions.py -q
```

The output directory must be new. The campaign checks X/Z propagation, inertial
filtering, reset independence, the unchanged legacy reset model, stalled native
outputs, immediate source reuse, coordinated reset, seeded exports, typed payload
bindings and exact-fatal negative controls. It also runs strict export validation
on the emitted fixtures. `tools/qualify.py` includes this campaign after Scala
fixture generation. Digital evidence does not establish physical timing closure.
