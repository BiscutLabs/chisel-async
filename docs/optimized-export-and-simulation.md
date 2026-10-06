# Optimized export and Scala-native simulation

The default `ExportDesign.emit` route uses firtool 1.160.0 release optimization with deduplication enabled. `ExportDesign.Debug` explicitly selects the historical debug/no-dedup route. Both use read-only Chisel probes instead of real observation outputs. The public hardware interface contains only functional ports; `check_export.py` rejects residual `ca_*` ports on registered hardware modules.

## Probe identity and deduplication

`contract.endpoint` creates a read probe of the packed value. `contract.child` forwards child references up the hierarchy without forwarding hardware data. Probe names encode the length of each semantic path segment so distinct hierarchies cannot collide through underscore concatenation. The compiler emits `ref_<top>.sv`, whose macros identify the actual optimized references. The v3 manifest records each probe name and the ABI file hash. It retains original elaboration paths only as provenance; those paths are not treated as compiled endpoint locations.

The resolver checks the ABI inventory and supported syntax, compiles the real RTL, resolves each reference and width, and verifies every node, primitive, parameter and resource. It records the actual module definition at each instance path; identical instances may share a definition. Active walking-bit comparisons independently reconstruct public boundary/aggregate sources. Internal timing nodes optimized into aliases are compared against the marker's wired endpoint slice. Every observed bit must reach both polarities. Functional campaigns run the original RTL without mapping forces.

The replication fixture has eight parallel two-stage paths with two distinct transforms. Both modes retain 25 hardware instances and 240 semantic endpoint references. Release emits six hardware definitions; debug emits 25. Each mode passes 207,840 active mapping comparisons and an independent 512-delivery transaction scoreboard. The tests require equivalent instances to share definitions and different transforms to stay distinct. A rehashed probe reference redirected into another equivalent instance must fail: shared module code does not make instance identity interchangeable.

Existing production examples now execute through release export, including typed/nested payloads, delayed long-hold control, dual-rail and clocked bridges. The withdrawn controller's five functional fixtures and published-controller comparison explicitly retain debug decomposition because those delay experiments assign delays to individual Boolean operations. Their original counterexample and random campaign outcomes must remain unchanged. This exception does not affect the production export default.

Read probes can restrict optimization of observed values. This route removes hardware observation ports and demonstrates deduplication; it does not claim zero observation cost or equivalence for arbitrary FIRRTL, synthesis or flattening passes. The current ABI reader deliberately rejects unsupported reference expressions.

## Typed port facts and channel associations

The v3 export also writes and hashes `ports.json`. This inventories every elaborated hardware-port leaf using Chisel reflection, separately from the channel registry and payload-layout writer; probes are excluded. The resolver compares its complete per-module inventory against actual Icarus port widths/directions. Channel leaves must have exactly the declared names, sources, widths and signed flags, and controls must have the correct forward/reverse directions. Factory-defined endpoint IDs and common source-bundle roots prevent borrowing another channel’s otherwise valid request or clock.

CIRCT erases SInt port signedness in SV. Signed metadata is checked against the elaborated Chisel port inventory; packed-bit mapping and typed transform tests then check the lowering behavior. This is not an independent proof of compiler type preservation. Re-emit older v1/v2 exports for this resolver. [The L0 review](l0-review.md) records the original false passes and required corruption controls.

## Timing intent in RTL

Every setup/hold or long-hold obligation instantiates `ChiselAsyncTimingMarker_v1`. It has no outputs, storage or behavior. Its input vector packs the obligation's ordered endpoints from least to most significant. Parameters carry the constraint kind, width, exact setup/hold or guard values and all per-cell min/max/model bounds in femtoseconds. Semantic instance IDs are not encoded into the cell's parameters, so equal definitions remain deduplicable.

The validator independently recomputes the marker parameters from the obligation, then checks them against elaborated parameters. It actively compares the wired endpoint vector with the resolved probe values. Rehashed tests alter a bound, an emitted parameter and a marker connection; all must produce the specified rejection. Primitive propagation parameters remain independently checked as well.

Markers carry intent through this Chisel/CIRCT export. Their empty definitions are removable by downstream synthesis: a physical flow must consume or explicitly preserve their constraints before that step. They enforce no physical timing and supply no technology mapping.

The schema is now `chisel-async-contract-v3`; re-emit v1/v2 exports. Timing observers use `resolved.json`'s checked probe paths. The old v1 schema remains packaged as historical format documentation, but the current resolver accepts v3 only. Absolute paths and timestamps remain outside semantic identity.

## ChiselSim scope and usage

The tests in `verification/chiselsim` use the upstream ScalaTest `ChiselSim` trait and `simulate(...)`, with ordinary `Module` test harnesses supplying explicit clocks/resets to the library's `RawModule` bridges. No Python stimulus or scoreboard is used for this lane. Run `python tools/sbt.py simulation/test`, or `sbt simulation/test` on a configured Linux toolchain. `python tools/qualify.py` runs it with the complete inventory checker and all other required lanes.

The pinned backend is Verilator 5.046. Three positive Scala tests check each bridge direction over all byte values and repeated values, changing/withdrawn unaccepted offers, downstream stalls, synchronizer response lower bounds, one reset abort followed by recovery, and four 1024-bit transfers. Each direction accounts for 265 offers/acceptances = 264 deliveries + one abort. Two harness mutations invert the observed payload and must activate `SOURCE_PAYLOAD` or `SINK_PAYLOAD`; an arbitrary exception cannot satisfy the control.

The runner deletes stale XML before launch and requires exactly five non-skipped ScalaTest cases plus all three activity markers. Empty, skipped, failed and inactive results have rejection tests. It records the backend identity, commands, source/result hashes and logs. The clean consumer repeats the suite using the locally published JAR, without a source-project dependency. GNU make/Verilator build paths must not contain spaces, so this consumer's simulation build directory is separately located under `build/consumer`; its source/JAR/export/Icarus work remains in a directory with spaces.

This lane qualifies clocked digital bridge behavior and simulator command transport. The Icarus campaigns remain responsible for asynchronous cell delays, four-state behavior, event ordering and full two-clock compositions. Neither lane demonstrates analog metastability or physical CDC closure.

## Windows build adapter

Upstream Chisel 7.16.0 svsim generates a Windows cleanup recipe followed by POSIX-shell build commands, uses POSIX `getline` and `/dev/null`, and requests an extensionless simulation executable. Its generated native build needs adaptation for MSYS2 UCRT64. `tools/svsim_windows.py` applies only to recognized fresh `workdir-verilator` directories inside the repository; unknown recipes, existing builds and paths outside the workspace fail before mutation.

The adapter removes the redundant cleanup from an already fresh svsim workspace, normalizes generated paths, supplies independently written `getline`/null-device compatibility, uses static DPI declarations and Verilator's context-based time API, and copies the native PE executable to svsim's requested extensionless name. Build-directory and test names stay short enough for native Windows tools' MAX_PATH limit. Nested compiler make calls pass through unchanged. The original makefile is retained next to the adapted file. No Chisel JAR, RTL, stimulus, simulator message protocol or simulator source is patched. The 1024-bit test exercises command-buffer growth as well as payload transport.

The build requires MSYS2 UCRT64 Verilator 5.046/GCC and MSYS make/Perl; the wrapper does not install system packages. Windows CI installs the official `5.046-1` package archive with SHA-256 `8c11e6057890d67157bf4285211381a2474c0b2172bc10254657d018f9449a2a`; floating MSYS2 installation supplied 5.050 and correctly failed preflight before this pin was added. Linux uses an unmodified native backend, built from a checksum-pinned source archive when needed. A fresh Ubuntu build exposed the missing `libfl-dev` prerequisite; setup now includes it and the bootstrap checks for `FlexLexer.h` before compilation. macOS remains deferred.

## Evidence limits and next gate

Development exposed and retained failures: old mutation targets no longer matched probe-lowered RTL; the comparison instrumenter needed to treat continuous assignments and wire initializers identically; a too-short reset in the new delayed replication bench violated the model's quiescent-reset requirement. The final fixture uses the declared digital timing policy and holds reset long enough to settle all cells. An export-mode initialization cycle also showed that sbt can return zero after an asynchronous generator exception; the wrapper now invalidates old generated contracts before emission so stale files cannot pass. Native consumer simulation exposed Windows path-length limits; shorter build/test names fixed them. Attempting absolute source-list entries instead failed because this backend prepended the file-list directory to Windows drive-letter paths; that attempted workaround is not used.

The documented counts are regression evidence, not a general compiler equivalence proof or complete L0 sign-off. The [frozen L0 acceptance campaign](l0-acceptance.md) now adds passing native Windows/Linux composition evidence at depths 1–4. Independent review still precedes CA-06.

API provenance: upstream [read probes](https://www.chisel-lang.org/docs/explanations/probes), [ChiselSim testing](https://www.chisel-lang.org/docs/explanations/testing), and the Chisel 7.16.0 source artifact were inspected. The adapter and library code are independently written; external tools retain their upstream licenses.
