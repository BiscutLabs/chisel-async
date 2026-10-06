// SPDX-License-Identifier: Apache-2.0
package chiselasync.interop

import chisel3._
import chiselasync.bundled.{CompositionCells, LongHoldBuffer}
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.{BundledTiming, PhaseTiming}
import chiselasync.protocol.{Channel, FourPhase}

/** Buffered bundled -> RTZ dual rail. Stored data and request are held until
  * the receiver has acknowledged all valid rails and then all spacer rails.
  */
class FourPhaseToDualRail[T <: Data](gen: T, timing: BundledTiming, phase: PhaseTiming,
    domain: ResetDomain = new ResetDomain("root")) extends AsyncModule(domain) {
  require(timing.mode == "digital-model", "encoding boundaries require digital timing")
  val in = IO(Flipped(new Channel(gen, resetDomain).bundled))
  val out = IO(new Channel(gen, resetDomain).dualRail)
  private val cells = new CompositionCells(this, phase.cells.model)
  private val storage = asyncChild("storage")(d => new LongHoldBuffer(gen, timing, d))
  FourPhase.connect(storage.in, in)
  private val zeros = Wire(Vec(gen.getWidth, Bool()))
  private val ones = Wire(Vec(gen.getWidth, Bool()))
  for (i <- 0 until gen.getWidth) {
    zeros(i) := cells.and(s"zero$i", Seq(storage.out.req, storage.out.bits.asUInt(i)), invert = 2)
    ones(i) := cells.and(s"one$i", Seq(storage.out.req, storage.out.bits.asUInt(i)))
  }
  out.zero := zeros.asUInt.asTypeOf(gen); out.one := ones.asUInt.asTypeOf(gen)
  storage.out.ack := out.ack
  contract.capacity(1); contract.channel("in", in, "input"); contract.dualRailChannel("out", out, "output")
  contract.encodingTiming("encoding", "bundled-to-dual", timing, phase)
}

/** Buffered RTZ dual rail -> bundled. A stateful completion C-element waits for
  * ALL valid rails and ALL spacer rails. A binary latch retains decoded data
  * through the entire internal four-phase return, not just acknowledgement rise.
  */
class DualRailToFourPhase[T <: Data](gen: T, timing: BundledTiming, phase: PhaseTiming,
    domain: ResetDomain = new ResetDomain("root")) extends AsyncModule(domain) {
  require(timing.mode == "digital-model", "encoding boundaries require digital timing")
  require(timing.matchedDelay.fs > (phase.cells.max + timing.dataDelay.max).fs,
    "decoder admission guard must cover binary latch and storage data path")
  val in = IO(Flipped(new Channel(gen, resetDomain).dualRail))
  val out = IO(new Channel(gen, resetDomain).bundled)
  private val cells = new CompositionCells(this, phase.cells.model)
  private val storage = asyncChild("storage")(d => new LongHoldBuffer(gen, timing, d))
  private val present = (0 until gen.getWidth).map(i => cells.or(s"present$i", Seq(in.zero.asUInt(i), in.one.asUInt(i))))
  private val complete = cells.c("completion", present)
  private val closed = cells.or("decode_close", Seq(complete, storage.in.ack))
  storage.in.bits := cells.latch("decoded", in.one.asUInt, closed).asTypeOf(gen)
  // Completion may outrun the decoded latch's output propagation. Admission
  // must wait for the binary payload, even though the storage has its own guard.
  storage.in.req := cells.buffer("decoded_request_guard", complete.asUInt, timing.matchedDelay).asBool
  // Delay BOTH ack edges. In particular, opening the binary latch precedes the
  // externally visible ack fall and therefore the next input word's arrival.
  in.ack := cells.buffer("acknowledge_guard", storage.in.ack.asUInt, phase.returnDelay).asBool
  FourPhase.connect(out, storage.out)
  contract.capacity(1); contract.dualRailChannel("in", in, "input"); contract.channel("out", out, "output")
  contract.encodingTiming("encoding", "dual-to-bundled", timing, phase)
}
