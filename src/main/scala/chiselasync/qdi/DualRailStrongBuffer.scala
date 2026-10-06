// SPDX-License-Identifier: Apache-2.0
package chiselasync.qdi

import chisel3._
import chiselasync.bundled.CompositionCells
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.QdiTiming
import chiselasync.protocol.Channel

/** Word-level strong indication: no output rail changes phase until every
  * input bit has arrived/returned. This is a half-buffer, not a decoupled FIFO.
  */
class DualRailStrongBuffer[T <: Data](gen: T, timing: QdiTiming,
    domain: ResetDomain = new ResetDomain("root")) extends AsyncModule(domain) {
  val in = IO(Flipped(new Channel(gen, resetDomain).dualRail))
  val out = IO(new Channel(gen, resetDomain).dualRail)
  private val cells = new CompositionCells(this, timing.cells.model)
  private val width = gen.getWidth
  private val present = (0 until width).map(i =>
    cells.or(s"input_present$i", Seq(in.zero.asUInt(i), in.one.asUInt(i)), "1-of-2 bit presence"))
  private val complete = cells.c("input_completion", present)
  private val zeros = (0 until width).map(i =>
    cells.c(s"strong_zero$i", Seq(in.zero.asUInt(i), complete, out.ack), invert = 4))
  private val ones = (0 until width).map(i =>
    cells.c(s"strong_one$i", Seq(in.one.asUInt(i), complete, out.ack), invert = 4))
  out.zero := VecInit(zeros).asUInt.asTypeOf(gen)
  out.one := VecInit(ones).asUInt.asTypeOf(gen)
  in.ack := cells.c("output_completion", (0 until width).map(i =>
    cells.or(s"output_present$i", Seq(zeros(i), ones(i)), "1-of-2 bit presence")))
  contract.capacity(1)
  contract.dualRailChannel("in", in, "input")
  contract.dualRailChannel("out", out, "output")
  contract.qdiTiming("qdi", Seq("in"), Seq("out"), timing, "strong", "storage")
}
