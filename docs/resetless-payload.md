# Resetless four-phase payload storage

`FourPhaseStage` and `LongHoldBuffer` accept the optional named argument
`payloadStorage = PayloadStorage.Resetless` from `chiselasync.bundled`.
The default remains `PayloadStorage.Resettable`. Only payload storage changes;
the request, capture, acknowledge and full-return controller still resets.
FIFO seeds, Join operands and Click storage keep their existing defaults.

The new `ResetlessClosingLatch` primitive has only `closed`, `d` and `q` pins.
It tracks `d` while `closed` is low and holds while high. It has no initial value,
reset pin or reset mask. At startup, while invalid and during reset, its output
may be unknown, stale or changing. An unknown enable retains a known value only
when open and closed interpretations agree; otherwise the model produces X.
The digital model retains the existing zero-aperture/inertial-propagation limits.

Every consumer must qualify payload capture and side effects with the owning
handshake. Audit combinational fanout too: invalid payload must not reach an
unqualified pin, reset/enable cone, arbitration decision or periodic reader.
Reset aborts transport through the controller; it does not erase payload bits.
Use this option for transient, unseeded data whose value is defined before every
valid offer. Keep resettable storage for initialized state, architectural outputs
and crossings whose independently reset participants require stronger containment.
`DataAllowance.Passive` is a separate selection; it does not choose storage.

`ChiselAsyncResetlessClosingLatch_v1` is a distinct behavioral/export identity.
ASIC integration must bind it explicitly to a resetless latch and characterize
data max/min, enable aperture, capture distribution, source hold and ACK ordering
at actual loads. Removing reset loads changes the physical circuit; existing
resettable-latch measurements do not qualify the new binding. The generation
audit treats its enable as native storage and rejects periodic-clock reachability.

Run `testOnly chiselasync.ResetlessPayloadSpec` for primitive four-state behavior,
a hold-fault control, resettable/resetless token-oracle comparisons with randomized
delays and stalls, occupied reset/reuse, export binding and the clock-reachability
negative control. These are digital and structural checks, not physical signoff.
