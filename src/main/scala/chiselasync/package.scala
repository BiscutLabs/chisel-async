// SPDX-License-Identifier: Apache-2.0
/** Typed asynchronous components for Chisel.
  *
  * Start with [[chiselasync.core.AsyncModule]] for explicit reset and child
  * registration, then use [[chiselasync.protocol.Channel]] to choose an electrical
  * encoding. Payloads are ordinary, explicitly sized Chisel types.
  *
  * Common entry points:
  *  - [[chiselasync.bundled.FourPhaseStage]] transforms and stores a token.
  *  - [[chiselasync.bundled.FourPhaseMux]] chooses a data input using a selector token.
  *  - [[chiselasync.bundled.FourPhaseRegFork]] stores two typed results of one input.
  *  - [[chiselasync.metadata.BundledTiming.Simulation]] supplies digital example timings.
  *  - [[chiselasync.testing.AsyncTest]] checks consumer-owned designs from ScalaTest.
  *  - [[chiselasync.metadata.ExportDesign]] emits RTL and timing contracts.
  *  - [[chiselasync.metadata.AsicMapping]] binds primitives to caller-supplied cells.
  *
  * ClickStage and PhaseDecoupledClickStage provide native two-phase storage with
  * local-pulse edge registers. The TwoPhase* composition family retains explicit
  * adapters around four-phase cores. Each controller family has its own timing policy.
  * Packaged behavioral models and randomized-delay tests do not establish physical
  * timing, metastability containment, or QDI layout assumptions. The ASIC interface
  * requires characterized technology implementations and subsequent physical checks.
  *
  * See the [[https://biscutlabs.github.io/chisel-async/ documentation website]] for
  * installation, executable adder/GCD examples, protocol contracts and testing guides.
  */
package object chiselasync
