# Qualification status

Initial local evidence, October 5, 2026. This document records a tested slice, not qualification of the complete planned catalog.

| Item | Local evidence |
| --- | --- |
| Host | Native Windows 11 x86-64, no WSL. |
| JVM | Microsoft JDK 17.0.18 initial build; Eclipse Temurin JDK 21.0.12.1+1 for clean consumer and final checks. |
| Build | sbt 1.12.4, Scala 2.13.18, Chisel/compiler-plugin 7.16.0, ScalaTest 3.2.20. |
| Compiler | Native firtool 1.160.0, checked release archive. |
| Event engine | Native Icarus Verilog 13.0; MSYS2 UCRT64 package `1~13.0-2`. |
| Harness | CPython 3.12.13, cocotb 2.1.0, pytest 8.4.2; dependency lock in verification/requirements.txt. |
| API/export checks | 14 Scala tests, including domain identity, invalid time/primitive parameters, registry failures and deterministic compiler emission across paths/widths. |
| Reference/compiler/harness checks | 70 Python tests cover independent protocol/timing references, actual RTL corruption, endpoint/resource loss, exact fs, unknown contract fields, incomplete inventories, wrong diagnostic reasons, stale reports, inactive observations and inconsistent accounting. |
| Event checks | 24 positive tests across scalar/wide/aggregate buffer, pipeline and C-element fixtures; six deliberately bad models are rejected by the required checkers. |
| Compiler mapping | 11 exports, 73 resolved anchors and 8,958 active RTL mapping comparisons; every anchor bit reaches both polarities. Resources, primitive ports/parameters, hierarchy, packing and reset bindings checked. |
| Timed models | 7 passing cases, 2 intended setup/hold violations and 5 corrupted-model controls. Exact 1 fs precision, independent data/control paths and transaction identity. |
| Packaging | Local publication; unrelated consumer in a path with spaces; buffer passes 6 event tests plus 5 controls, then the complete 14-case timing campaign. Schema and all four SV resources are packaged. |
| Other native hosts | Linux x86-64 and macOS arm64 workflows configured; no local or remote result claimed yet. |

The fixed source/sink randomization seeds are `0xA51` and `0xB82`; cocotb's seed is 8675309. Tests check 40 completed transactions per stream, legal control transitions and held data, required final idle, capacity and pending requests, reset at five selected protocol points, and full storage/pipeline reset with a waiting request. Every reset scenario completes fresh traffic and accounts for aborted tokens. Walking-one and walking-zero patterns exercise all 8, 65 or 22 payload bits (including nested fields). The C-element oracle checks 1,024 Boolean transitions and five four-state/reset observations.

Each single-buffer fixture additionally checks all 18 linear extensions of the declared two-token environment, with both equal and distinct data, all 68 distinct reset prefixes, and six boundary cases at -1/0/+1 ps. This finite corpus does not prove all interleavings correct. The [verification method](verification.md) records the scope, oracle lineage, fault controls, required activity, and remaining qualifications.

The runners retain source/checker hashes, seeds, platform/engine versions, XML, logs, ordered traces with exact integer femtosecond timestamps (plus the existing picosecond display field), reset epochs, coverage and token counters. Positive evidence must satisfy the declared activity inventory; negative evidence must identify the specified checker. Selected and unexecuted runs are explicit. Run commands are in the README. Generated evidence is ignored by Git and uploaded by CI when that workflow runs.

The review deliberately introduced three faults that the earlier suite missed: transient request withdrawal, reset data set to ones, and swapping bits 32/33. All now have permanent controls and are rejected, alongside payload inversion, a data excursion and a low-bit swap. This was an exploratory review followed by regression development, not a preregistered or held-out release evaluation. Freeze a separate release campaign and obtain independent contract review before claiming release qualification.

The pinned debug export emits `circt.VerbatimBlackBoxAnno` and `firrtl.transforms.DedupGroupAnnotation` warnings. None are suppressed. The [checked sidecar route](timing-and-export.md) validates actual emitted instances and anchors independently of annotation preservation. The retained HW snapshot is provenance evidence, not a general MLIR import/equivalence claim.

No physical timing, hazard freedom, QDI implementation, analog metastability, power, area, performance or Chiselator compatibility is claimed. The buffer remains a zero-delay behavioral model; its structural handshake controller and clocked interfaces are future work. Export v1 supports a single coordinated reset domain and the pinned debug compiler configuration. Native packaging results on other operating systems must exist before those platforms are marked qualified.
