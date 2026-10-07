# Troubleshooting

| Symptom | Likely cause and action |
| --- | --- |
| Dependency `chisel-async_2.13` cannot be resolved | RC1 is on GitHub, not Maven Central. Add the extracted Maven ZIP as a resolver using the [installation guide](getting-started.md#obtain-the-library), or run `sbt publishLocal` from tag `v0.1.0-RC1` under the same user account. |
| Compiler-plugin or elaboration errors | Match Chisel 7.16.0, compiler plugin 7.16.0 and Scala 2.13.18. Use `CrossVersion.full` for the plugin; inspect dependency eviction. |
| `unqualified runtime` / `unqualified firtool` | Your tool versions differ from the tested configuration. Normal emission warns; `qualifiedOnly = true` and strict validation reject the mismatch. Use the versions in the README compatibility matrix for validated exports. |
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

When reporting an issue, include the source revision, dependency and tool versions,
operating system, a minimal example, and the first error with its logs. Keep the
output from the failed run. See [testing](testing.md) and [contributing](contributing.md)
for commands to reproduce specific tests.
