# Troubleshooting

| Symptom | Likely cause and action |
| --- | --- |
| Dependency `chisel-async_2.13` cannot be resolved | There is no public release yet. Run `sbt publishLocal` in the library checkout, then build the standalone consumer under the same user account. |
| Compiler-plugin or elaboration errors | Match Chisel 7.16.0, compiler plugin 7.16.0 and Scala 2.13.18. Use `CrossVersion.full` for the plugin; inspect dependency eviction. |
| `unqualified runtime` / `unqualified firtool` | Normal emission warns on drift; `qualifiedOnly = true` and strict validation reject it. Use the README tuple for qualified exports; never disguise the compiler in the manifest. |
| Payload shape/width error | Specify positive widths and preserve Bundle/Vec field shapes and signedness. Implement explicit conversion in a typed stage. |
| Reset domains differ despite equal names | Domains compare by object identity. Use `asyncChild` or explicitly pass the actual shared parent domain and wire/register reset. |
| No token after reset | Check idle external drivers, enough time for delayed cells to quiesce, and running clocks through bridge reset release. Check that a feedback cycle has an initial token. |
| One token works, later tokens stall | Complete request and acknowledgement return. For dual rail, return every bit to spacer; for two-phase count both completion polarities. |
| Merge overlap diagnostic | Exclusive merge does not arbitrate. Serialize entire input handshakes or replace the boundary with a two-client arbiter. |
| Digital timing constructor rejects a value | Guards use strict inequalities and worst-case bounds. Check the whole transform/mux path, output guard and phase history-closure bound. |
| SV model cannot be found | Consume the packaged JAR resources and generated file inventory. Check extraction/output paths rather than copying model text by hand. |
| ChiselSim fails on Windows before simulation | Use the documented adapter and MSYS2 toolchain. Keep build paths short and free of spaces, including generated layer filenames. |
| Export emitted but tests refuse it | Run `check_export.py`, regenerate obsolete ABI/schema output, and inspect the first mapping/resource/constraint diagnostic. Emission alone is not validation. |
| `ASYNC_NO_ACTIVITY` / `ASYNC_DEADLINE` | An event test completed no output or stalled. Check selector tokens, handshake return and backpressure; inspect the retained testbench and simulation log. |
| `INCOMPLETE_OR_EXTRA_CELL_BINDINGS` | Compare bindings with `required-cells.json`, including parameter specializations. A simulation delay is not a technology-cell mapping. |
| Lost events from narrow pulses | Both high and low must span `stages + 1` destination edges. Use a different capture protocol for shorter or clockless events. |
| Write happened but response disappeared on reset | Reset aborts transport, not committed backend effects. Define recovery at the application level; do not blindly retry writes. |

For a report, include the source revision, full dependency/tool tuple, host,
smallest reproducer, first failure and relevant retained logs. Keep failed-run
evidence. Follow [testing](testing.md) and [contributing](contributing.md) for
focused replay; a missing tool or unrelated crash is not a passing negative test.
