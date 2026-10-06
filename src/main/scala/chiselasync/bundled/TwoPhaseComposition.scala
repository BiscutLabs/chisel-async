// SPDX-License-Identifier: Apache-2.0
package chiselasync.bundled

import chisel3._
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.interop.{ToFourPhase, ToTwoPhase}
import chiselasync.metadata.{BundledTiming, ModelTime, PhaseTiming}
import chiselasync.primitives.MutexPolicy
import chiselasync.protocol.{Channel, FourPhase, TwoPhase}

/** Boundary normalization reuses the established four-phase catalog. Adapters
  * store phase only; capacities below count the actual long-hold data slots.
  */
private[chiselasync] abstract class PhaseComposition(phase: PhaseTiming, domain: ResetDomain)
    extends AsyncModule(domain) {
  contract.endpoint("reset", reset)
  protected def input[T <: Data](id: String, port: TwoPhase[T]): FourPhase[T] = {
    val adapter = asyncChild(s"${id}_phase")(d => new ToFourPhase(port.payloadType, phase, d))
    TwoPhase.connect(adapter.in, port)
    contract.twoPhaseChannel(id, port, "input")
    adapter.out
  }
  protected def output[T <: Data](id: String, port: TwoPhase[T], source: FourPhase[T]): Unit = {
    val adapter = asyncChild(s"${id}_phase")(d => new ToTwoPhase(port.payloadType, phase, d))
    FourPhase.connect(adapter.in, source); TwoPhase.connect(port, adapter.out)
    contract.twoPhaseChannel(id, port, "output")
  }
}

class TwoPhaseStage[A <: Data, B <: Data](a: A, b: B, transform: A => B,
    timing: BundledTiming, phase: PhaseTiming, domain: ResetDomain = new ResetDomain("root"))
    extends PhaseComposition(phase, domain) {
  val in = IO(Flipped(new Channel(a, resetDomain).twoPhase))
  val out = IO(new Channel(b, resetDomain).twoPhase)
  private val storage = asyncChild("storage")(d => new FourPhaseStage(a, b, transform, timing, d))
  FourPhase.connect(storage.in, input("in", in)); output("out", out, storage.out)
  contract.capacity(1)
}
class TwoPhaseBuffer[T <: Data](gen: T, timing: BundledTiming, phase: PhaseTiming,
    domain: ResetDomain = new ResetDomain("root"))
    extends TwoPhaseStage(gen, gen, (x: T) => x, timing, phase, domain)

class TwoPhaseFifo[T <: Data](gen: T, val depth: Int, timing: BundledTiming, phase: PhaseTiming,
    val initial: Seq[T] = Seq.empty, cellDelay: ModelTime = ModelTime.ps(1000),
    domain: ResetDomain = new ResetDomain("root")) extends PhaseComposition(phase, domain) {
  val in = IO(Flipped(new Channel(gen, resetDomain).twoPhase))
  val out = IO(new Channel(gen, resetDomain).twoPhase)
  private val storage = asyncChild("storage")(d => new FourPhaseFifo(gen, depth, timing, initial, cellDelay, d))
  FourPhase.connect(storage.in, input("in", in)); output("out", out, storage.out)
  contract.capacity(depth)
}
class TwoPhaseInitialTokens[T <: Data](gen: T, initial: Seq[T], timing: BundledTiming,
    phase: PhaseTiming, cellDelay: ModelTime, domain: ResetDomain = new ResetDomain("root"))
    extends PhaseComposition(phase, domain) {
  val out = IO(new Channel(gen, resetDomain).twoPhase)
  val done = IO(Output(Bool()))
  private val source = asyncChild("source")(d => new InitialTokens(gen, initial, timing, cellDelay, d))
  output("out", out, source.out); done := source.done
  contract.capacity(initial.size); contract.endpoint("done", done)
}
class TwoPhaseFork[T <: Data](gen: T, val branches: Int, phase: PhaseTiming, cellDelay: ModelTime,
    domain: ResetDomain = new ResetDomain("root")) extends PhaseComposition(phase, domain) {
  val in = IO(Flipped(new Channel(gen, resetDomain).twoPhase))
  val out = IO(Vec(branches, new Channel(gen, resetDomain).twoPhase))
  private val core = asyncChild("core")(d => new FourPhaseFork(gen, branches, cellDelay, d))
  FourPhase.connect(core.in, input("in", in))
  out.zipWithIndex.foreach { case (port, i) => output(s"out$i", port, core.out(i)) }
}
class TwoPhaseJoin[A <: Data, B <: Data](a: A, b: B, timing: BundledTiming, phase: PhaseTiming,
    cellDelay: ModelTime, domain: ResetDomain = new ResetDomain("root")) extends PhaseComposition(phase, domain) {
  val left = IO(Flipped(new Channel(a, resetDomain).twoPhase))
  val right = IO(Flipped(new Channel(b, resetDomain).twoPhase))
  val out = IO(new Channel(new Joined(a, b), resetDomain).twoPhase)
  private val core = asyncChild("core")(d => new FourPhaseJoin(a, b, timing, cellDelay, d))
  FourPhase.connect(core.left, input("left", left)); FourPhase.connect(core.right, input("right", right))
  output("out", out, core.out)
}
class TwoPhaseSelect[T <: Data](gen: T, val destinations: Int, timing: BundledTiming, phase: PhaseTiming,
    cellDelay: ModelTime, domain: ResetDomain = new ResetDomain("root")) extends PhaseComposition(phase, domain) {
  val in = IO(Flipped(new Channel(new Selected(gen, destinations), resetDomain).twoPhase))
  val out = IO(Vec(destinations, new Channel(gen, resetDomain).twoPhase))
  private val core = asyncChild("core")(d => new FourPhaseSelect(gen, destinations, timing, cellDelay, d))
  FourPhase.connect(core.in, input("in", in))
  out.zipWithIndex.foreach { case (port, i) => output(s"out$i", port, core.out(i)) }
  contract.capacity(1)
}
class TwoPhaseMerge[T <: Data](gen: T, val inputs: Int, timing: BundledTiming, phase: PhaseTiming,
    cellDelay: ModelTime, domain: ResetDomain = new ResetDomain("root")) extends PhaseComposition(phase, domain) {
  val in = IO(Flipped(Vec(inputs, new Channel(gen, resetDomain).twoPhase)))
  val out = IO(new Channel(gen, resetDomain).twoPhase)
  private val core = asyncChild("core")(d => new FourPhaseMerge(gen, inputs, timing, cellDelay, d))
  in.zipWithIndex.foreach { case (port, i) => FourPhase.connect(core.in(i), input(s"in$i", port)) }
  output("out", out, core.out); contract.capacity(1)
}
class TwoPhaseArbiter[T <: Data](gen: T, timing: BundledTiming, phase: PhaseTiming, cellDelay: ModelTime,
    resolution: ModelTime, policy: MutexPolicy.Value, domain: ResetDomain = new ResetDomain("root"))
    extends PhaseComposition(phase, domain) {
  val in = IO(Flipped(Vec(2, new Channel(gen, resetDomain).twoPhase)))
  val out = IO(new Channel(gen, resetDomain).twoPhase)
  private val core = asyncChild("core")(d => new FourPhaseArbiter(gen, timing, cellDelay, resolution, policy, d))
  in.zipWithIndex.foreach { case (port, i) => FourPhase.connect(core.in(i), input(s"in$i", port)) }
  output("out", out, core.out); contract.capacity(1)
}
