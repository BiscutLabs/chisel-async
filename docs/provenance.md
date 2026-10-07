# Scientific foundations and references

Chisel-async builds on published designs for asynchronous pipelines, storage,
arbitration and dual-rail logic. The references below explain how those circuits
work and which timing, reset and storage assumptions each component relies on.

| Area | Source and relationship |
| --- | --- |
| Long-hold controller | Furber–Day, section 7, figures 14–15: explicit asymmetric-cell topology, with separately declared digital guards |
| Muller storage and completion | Sparsø tutorial figures 2.12–2.13: per-rail storage and stateful completion, with atomic inversion and ideal-fork assumptions |
| Rendezvous and arbitration | Sparsø–Furber fork/join/exclusive-merge discussion and figure 5.21 MUTEX/return-interlock topology |
| Dual-rail functions | Strong/weak indication and DIMS construction, including all-input minterms for both data and spacer |
| Sequential phase conversion | ASYNC 2000 tutorial protocol discussion, with buffered conversion and explicit closure guards |
| Native Click storage | Peeters et al. (2010); Sparsø figures 9.4(b) and 9.11(b): shared or separate phase flip-flops, XOR/AND local firing, edge-triggered payload storage |
| Chisel integration | Upstream RawModule, ExtModule resources, CIRCT stage, read probes and ChiselSim APIs |

For links to the papers and the revisions used, see the
[source notes](archive/development/provenance.md). The
[long-hold controller notes](archive/development/long-hold-controller.md#inspected-source-and-preserved-topology)
also identify the figures and circuit topology used in the implementation.
The [Click guide](click.md#how-a-stage-fires) links the original paper and the
phase-decoupled template, and describes the added explicit timing guards.
To compare chisel-async with other libraries, see the
[component comparison](component-terminology.md#how-this-compares-with-chisel-click)
for interfaces, storage and encodings, and the
[test comparison](archive/development/verification.md#comparison-with-inspected-upstream-tests)
for coverage, reference models and tests that deliberately introduce faults.

An earlier custom controller failed when its internal delays varied and was
withdrawn. The regression suite still reproduces that race and checks that the
tests detect it. The [review response](archive/development/review-response.md)
explains the failure and the decision to replace it.

The digital models assume bounded delays, atomic cells and the documented wire
and reset behavior. Their tests check behavior under those assumptions. Physical
QDI behavior, analog metastability resolution and timing closure still need to be
verified for the chosen technology. Example delay values are simulation settings,
not silicon measurements.

Chisel-async is [Apache-2.0 licensed](../LICENSE). Tools and dependencies retain
their respective licenses.
