# Contributing and repository qualification

Normal consumers need the JAR, matching Chisel build, and the tools required by
their task. Contributors need the additional independent verification harness.
Read [AGENTS.md](../AGENTS.md), [protocol contracts](contracts.md) and the relevant
component guide before changing behavior.

## Prerequisites

Install Python 3.12 and the platform prerequisites below, then run from the
repository root:

```text
python tools/qualify.py
```

On **Windows**, use native MSYS2 UCRT64 Icarus 13, Verilator 5.046, GCC and MSYS
`make`. Package names are `mingw-w64-ucrt-x86_64-iverilog`,
`mingw-w64-ucrt-x86_64-verilator`, `mingw-w64-ucrt-x86_64-gcc`, and `make`.
The workflow pins the
[Verilator package](https://repo.msys2.org/mingw/ucrt64/mingw-w64-ucrt-x86_64-verilator-5.046-1-any.pkg.tar.zst)
and checksum; a rolling package install may select a different version. The wrapper
finds `C:/msys64/ucrt64/bin`; pass `--simulator-dir <directory>` for another Icarus
installation. WSL is not required and is not native Windows evidence.

On **Linux**, install `autoconf gperf bison flex libfl-dev g++ make perl`
(Debian/Ubuntu names). The wrapper builds checksum-pinned Icarus 13 and Verilator
5.046 when qualified versions are not found. It never installs system packages
or invokes sudo itself.

**macOS qualification is deferred.** The wrapper reports unsupported qualification
instead of silently skipping tests.

The wrapper creates/reuses `.venv`, installs hash-locked Python dependencies and
the pinned JDK/firtool/sbt, configures child-process paths, emits fixtures, and runs
API, export, event, timing, composition, encoding, clocked and clean-consumer checks.
No environment activation or manual `JAVA_HOME` is needed for this full command.
Use `--no-setup` only with dependencies already installed; it still runs the entire
campaign and uses the calling Python interpreter.

## Focused checks

Focused commands require the configured JDK and simulator environment. For manual
work, set `JAVA_HOME` to the installed JDK and add native simulators to `PATH`.
Use `.venv/Scripts/python.exe` on Windows or `.venv/bin/python` on Linux for commands
requiring the repository Python dependencies. The `python` below means that interpreter.

| Change | Useful checks |
| --- | --- |
| Documentation links/snippets | `python tools/check_docs.py` |
| Quickstart or packaging | `python tools/check_quickstart.py` (local publish, independent consumer, export and test) |
| Scala API, payload types, elaboration | `python tools/sbt.py test` |
| Clocked harnesses | `python tools/sbt.py simulation/test` |
| Python oracles/checkers | `python -m pytest verification --ignore=verification/cocotb -q` |
| Packaged artifacts | `python tools/sbt.py package packageSrc packageDoc makePom` |
| Complete clean-JAR replay | `python tools/consumer_smoke.py` |

Event runners expect fresh, already emitted fixtures. The
[examples index](examples.md) maps emitter names to runners. Supply a new `--output`
directory where required; do not overwrite a failing attempt to make its report
look successful. Use each runner's `--help` for its supported fixture/seed options.

For semantic changes, update the relevant contracts and meaningful negative
controls, then run affected campaigns and the complete qualifier as required by
the scope. Do not rerun every historical campaign merely to validate prose.

## Evidence and failures

The wrapper writes command/status/log records under
`target/verification/qualification`. Campaigns retain source/checker identities,
seeds, trace files, XML and counters. Missing tools, empty tests, incomplete case
inventories, inactive observers and wrong fault diagnostics must fail.

Generated output, downloads, `.venv`, `.tools`, simulator builds and raw evidence
remain ignored by Git. Preserve failure evidence when repairing a test. A new
run does not rewrite the scope of a previously accepted candidate.

## Documentation maintenance

The README answers what the library does and which versions were tested.
`docs/index.md` routes readers to tutorials, reference contracts and task guides.
Keep current user instructions free of roadmap status and review chronology.
Update the relevant guide when a public API or assumption changes.

Quickstart code is a standalone dependency consumer under `examples/quickstart`.
Fenced snippets marked `source:` must match their checked-in files; the docs checker
also validates local links and heading anchors. Compile/run the example after
code changes. Preserve old plans and acceptance records under `docs/archive/` for
audit; do not update a retired roadmap as the active source of truth.

The future website should render these versioned guides and link the matching API
docs. Avoid a second manually maintained copy of installation instructions.
