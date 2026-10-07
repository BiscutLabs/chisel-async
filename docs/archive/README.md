# Development archive

These records preserve the reasoning, failed experiments, review findings and
qualification evidence behind chisel-async. They were retired from the active
documentation when the user guides were introduced. They are historical records,
not current installation instructions or an active backlog.

Use the [current documentation](../index.md) for the API and supported workflow.
Historical acceptance applies only to the revisions, toolchains and scopes named
in each record. Moving the documents does not rerun or extend those results.

| Record | Purpose |
| --- | --- |
| [Previous README](development/README-before-user-guide.md) | State of the project before the user-guide rewrite |
| [Roadmap](development/roadmap.md) | Historical work packages and implementation sequence |
| [Qualification](development/qualification.md) | Native runs, revisions, evidence and limitations |
| [L0 acceptance](development/l0-acceptance.md), [L1 acceptance](development/l1-acceptance.md) | Frozen acceptance scopes |
| [Controller review](development/review-response.md), [comparison](development/controller-comparison.md), [long-hold replacement](development/long-hold-controller.md) | Counterexample, source inspection and replacement evidence |
| [Verification comparison](development/verification.md) | Independent oracles and comparisons with other libraries |
| [Phase review](development/ca07-review.md), [closure repair](development/adapter-closure-and-reference.md) | Adapter races, arbitration models and integration evidence |
| [Dual-rail family](development/qdi-family.md), [application boundaries](development/application-boundaries.md) | Later family-specific qualification |

The remaining documents in `development/` retain the detailed investigations and
original contracts. Relative links were adjusted for this location. Ignored raw
logs, downloaded papers, waveforms and local evidence were not moved or deleted;
retrieve published CI artifacts or the recorded source revision when replaying.
