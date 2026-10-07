# Scientific and implementation provenance

chisel-async is independently developed under Apache-2.0. It does not copy or
rename ASYNC-Chisel implementation code. Prior libraries, tutorials and published
controllers inform its interfaces and experiments; conceptual provenance is
separate from a claim of implementation equivalence or physical qualification.

| Area | Source and relationship |
| --- | --- |
| Long-hold controller | Furber–Day, section 7, figures 14–15: explicit asymmetric-cell topology, with separately declared digital guards |
| Muller storage and completion | Sparsø tutorial figures 2.12–2.13: per-rail storage and stateful completion, with atomic inversion and ideal-fork assumptions |
| Rendezvous and arbitration | Sparsø–Furber fork/join/exclusive-merge discussion and figure 5.21 MUTEX/return-interlock topology |
| Dual-rail functions | Strong/weak indication and DIMS construction, including all-input minterms for both data and spacer |
| Sequential phase conversion | ASYNC 2000 tutorial protocol discussion, with our own buffered implementation and explicit closure guards |
| Chisel integration | Upstream RawModule, ExtModule resources, CIRCT stage, read probes and ChiselSim APIs |

The [original provenance record](archive/development/provenance.md) preserves
primary-source links and the exact revisions inspected for ASYNC-Chisel,
chisel-click and ACT/actsim. The
[long-hold source record](archive/development/long-hold-controller.md#inspected-source-and-preserved-topology)
contains the inspected paper, figure references, hash and topology details.
[Verification comparisons](archive/development/verification.md#comparison-with-inspected-upstream-tests)
explain the independent oracles and deliberately broken controls.

The original custom structural stage failed under internal delay variation and
was withdrawn. Its counterexample remains in regression; the
[review response](archive/development/review-response.md) records why. Keeping that
failure is part of the scientific record, not an endorsement of the withdrawn API.

Digital models use bounded delays, atomic cells and declared wire/reset assumptions.
They do not establish physical QDI behavior, analog metastability resolution or
technology-specific timing closure. Model values in examples are experimental
parameters, not measured silicon performance.

Downloaded tools and dependencies retain their own licenses and are not bundled
as native executables. Future source reuse must record the source revision,
license and required notices. See the repository [LICENSE](../LICENSE).
