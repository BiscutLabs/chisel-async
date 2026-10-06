// SPDX-License-Identifier: Apache-2.0
package chiselasync.interop

import chisel3._
import chiselasync.bundled.{CompositionCells, LongHoldBuffer}
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.{BundledTiming, PhaseTiming}
import chiselasync.protocol.{Channel, FourPhase, TwoPhase}

/** Unbuffered sequential control conversion. Internal implementation detail;
  * the caller supplies storage and the source holds data until input completion.
  */
private[chiselasync] class ToFourPhase[T <: Data](gen: T, phase: PhaseTiming, domain: ResetDomain)
    extends AsyncModule(domain) {
  val in = IO(Flipped(new Channel(gen, resetDomain).twoPhase))
  val out = IO(new Channel(gen, resetDomain).bundled)
  private val cells = new CompositionCells(this, phase.cells.model)
  private val master = cells.latch("phase", in.req.asUInt, cells.invert("master_close", out.ack)).asBool
  private val returned = cells.latch("returned", master.asUInt, out.ack).asBool
  out.req := cells.xor("request", in.req, master)
  out.bits := in.bits
  in.ack := cells.buffer("return_guard", returned.asUInt, phase.returnDelay).asBool
  contract.twoPhaseChannel("in", in, "input"); contract.channel("out", out, "output")
  contract.phaseTiming("phase_conversion", "two-to-four", phase)
}

/** req4+ -> req2 edge -> ack2 edge -> ack4+ -> req4- -> ack4-.
  * The acknowledgement history latch closes before the toggle can propagate.
  */
private[chiselasync] class ToTwoPhase[T <: Data](gen: T, phase: PhaseTiming, domain: ResetDomain)
    extends AsyncModule(domain) {
  val in = IO(Flipped(new Channel(gen, resetDomain).bundled))
  val out = IO(new Channel(gen, resetDomain).twoPhase)
  private val cells = new CompositionCells(this, phase.cells.model)
  private val history = cells.latch("history", out.ack.asUInt, in.req).asBool
  out.req := cells.toggle("request_phase", in.req)
  out.bits := in.bits
  in.ack := cells.xor("acknowledge", out.ack, history)
  contract.channel("in", in, "input"); contract.twoPhaseChannel("out", out, "output")
  contract.phaseTiming("phase_conversion", "four-to-two", phase)
}

/** One long-hold storage slot plus explicit input phase conversion. */
class TwoPhaseToFourPhase[T <: Data](gen: T, timing: BundledTiming, phase: PhaseTiming,
    domain: ResetDomain = new ResetDomain("root")) extends AsyncModule(domain) {
  val in = IO(Flipped(new Channel(gen, resetDomain).twoPhase))
  val out = IO(new Channel(gen, resetDomain).bundled)
  private val adapter = asyncChild("adapter")(d => new ToFourPhase(gen, phase, d))
  private val storage = asyncChild("storage")(d => new LongHoldBuffer(gen, timing, d))
  TwoPhase.connect(adapter.in, in); FourPhase.connect(storage.in, adapter.out); FourPhase.connect(out, storage.out)
  contract.capacity(1); contract.endpoint("reset", reset)
  contract.twoPhaseChannel("in", in, "input"); contract.channel("out", out, "output")
}

/** One long-hold storage slot plus explicit output phase conversion. */
class FourPhaseToTwoPhase[T <: Data](gen: T, timing: BundledTiming, phase: PhaseTiming,
    domain: ResetDomain = new ResetDomain("root")) extends AsyncModule(domain) {
  val in = IO(Flipped(new Channel(gen, resetDomain).bundled))
  val out = IO(new Channel(gen, resetDomain).twoPhase)
  private val storage = asyncChild("storage")(d => new LongHoldBuffer(gen, timing, d))
  private val adapter = asyncChild("adapter")(d => new ToTwoPhase(gen, phase, d))
  FourPhase.connect(storage.in, in); FourPhase.connect(adapter.in, storage.out); TwoPhase.connect(out, adapter.out)
  contract.capacity(1); contract.endpoint("reset", reset)
  contract.channel("in", in, "input"); contract.twoPhaseChannel("out", out, "output")
}
