# Scientific foundations and references

The library uses published asynchronous circuit topologies, with explicit timing,
reset and storage contracts. These references explain the designs behind the
components and the assumptions used in their digital models.

| Area | Source and relationship |
| --- | --- |
| Long-hold controller | Furber–Day, section 7, figures 14–15: explicit asymmetric-cell topology, with separately declared digital guards |
| Muller storage and completion | Sparsø tutorial figures 2.12–2.13: per-rail storage and stateful completion, with atomic inversion and ideal-fork assumptions |
| Rendezvous and arbitration | Sparsø–Furber fork/join/exclusive-merge discussion and figure 5.21 MUTEX/return-interlock topology |
| Dual-rail functions | Strong/weak indication and DIMS construction, including all-input minterms for both data and spacer |
| Sequential phase conversion | ASYNC 2000 tutorial protocol discussion, with buffered conversion and explicit closure guards |
| Chisel integration | Upstream RawModule, ExtModule resources, CIRCT stage, read probes and ChiselSim APIs |

The [source record](archive/development/provenance.md) preserves primary-source
links, paper revisions and model assumptions. The
[long-hold source record](archive/development/long-hold-controller.md#inspected-source-and-preserved-topology)
contains the inspected paper, figure references, hash and topology details.
[Component comparisons](component-terminology.md#how-this-compares-with-chisel-click)
describe differences in interfaces, storage, supported encodings and implementation.
[Verification comparisons](archive/development/verification.md#comparison-with-inspected-upstream-tests)
compare test coverage, independent oracles and deliberately broken controls.

The original custom structural stage failed under internal delay variation and
was withdrawn. Its counterexample remains in regression; the
[review response](archive/development/review-response.md) records why. Keeping that
failure is part of the scientific record, not an endorsement of the withdrawn API.

Digital models use bounded delays, atomic cells and declared wire/reset assumptions.
They do not establish physical QDI behavior, analog metastability resolution or
technology-specific timing closure. Model values in examples are experimental
parameters, not measured silicon performance.

chisel-async is [Apache-2.0 licensed](../LICENSE). Tools and dependencies retain
their respective licenses.
