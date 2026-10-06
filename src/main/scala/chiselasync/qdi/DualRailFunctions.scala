// SPDX-License-Identifier: Apache-2.0
package chiselasync.qdi

import chisel3._
import chiselasync.bundled.CompositionCells
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.QdiTiming
import chiselasync.protocol.{Channel, DualRail}

/** Small, strongly indicating DIMS table. Bit packing follows Chisel's normal
  * asUInt/asTypeOf order. Each row includes EVERY input, even redundant ones.
  * Output storage retains the word under backpressure. Exponential construction
  * is deliberately limited to four input bits.
  */
class DualRailFunction[A <: Data, B <: Data](inGen: A, outGen: B,
    val table: Seq[BigInt], timing: QdiTiming,
    domain: ResetDomain = new ResetDomain("root")) extends AsyncModule(domain) {
  private val width = inGen.getWidth
  require(width >= 1 && width <= 4, "DIMS table supports one to four input bits")
  require(outGen.isWidthKnown && outGen.getWidth > 0, "DIMS output width must be known and positive")
  require(table.size == (1 << width), "DIMS table must define every input word")
  require(table.forall(v => v >= 0 && v < (BigInt(1) << outGen.getWidth)), "DIMS result does not fit output type")
  val in = IO(Flipped(new Channel(inGen, resetDomain).dualRail))
  val out = IO(new Channel(outGen, resetDomain).dualRail)
  private val cells = new CompositionCells(this, timing.cells.model)
  private val terms = (0 until (1 << width)).map { value =>
    cells.c(s"minterm$value", (0 until width).map { bit =>
      if ((value & (1 << bit)) == 0) in.zero.asUInt(bit) else in.one.asUInt(bit)
    })
  }
  private def cover(bit: Int, one: Boolean): Bool = {
    val selected = table.indices.filter(i => table(i).testBit(bit) == one).map(terms)
    // Keep the typed storage input boundary in optimized exports even when a
    // truth-table column is constant. The behavioral buffer remains tied low.
    if (selected.isEmpty) cells.buffer(s"constant${bit}_${if (one) "one" else "zero"}",
      0.U(1.W), timing.cells.model).asBool
    else cells.or(s"cover${bit}_${if (one) "one" else "zero"}", selected,
      "disjoint complete DIMS minterms; all-input valid/spacer indication; ideal forks")
  }
  private val storage = asyncChild("storage")(d => new DualRailStrongBuffer(outGen, timing, d))
  storage.in.zero := VecInit((0 until outGen.getWidth).map(cover(_, false))).asUInt.asTypeOf(outGen)
  storage.in.one := VecInit((0 until outGen.getWidth).map(cover(_, true))).asUInt.asTypeOf(outGen)
  in.ack := storage.in.ack
  DualRail.connect(out, storage.out)
  contract.capacity(1)
  contract.dualRailChannel("in", in, "input")
  contract.dualRailChannel("out", out, "output")
  contract.qdiTiming("qdi", Seq("in"), Seq("out"), timing, "strong", "dims")
}

/** Binary operands: bit 0 is a, bit 1 is b. */
class DualRailNot(timing: QdiTiming, domain: ResetDomain = new ResetDomain("root"))
    extends DualRailFunction(Bool(), Bool(), Seq(BigInt(1), BigInt(0)), timing, domain)
class DualRailAnd(timing: QdiTiming, domain: ResetDomain = new ResetDomain("root"))
    extends DualRailFunction(UInt(2.W), Bool(), Seq(0, 0, 0, 1).map(BigInt(_)), timing, domain)
class DualRailOr(timing: QdiTiming, domain: ResetDomain = new ResetDomain("root"))
    extends DualRailFunction(UInt(2.W), Bool(), Seq(0, 1, 1, 1).map(BigInt(_)), timing, domain)
class DualRailXor(timing: QdiTiming, domain: ResetDomain = new ResetDomain("root"))
    extends DualRailFunction(UInt(2.W), Bool(), Seq(0, 1, 1, 0).map(BigInt(_)), timing, domain)

/** bit 2 selects bit 0 (zero) or bit 1 (one); BOTH values are indicated. */
class DualRailSelect(timing: QdiTiming, domain: ResetDomain = new ResetDomain("root"))
    extends DualRailFunction(UInt(3.W), Bool(), (0 until 8).map(v =>
      BigInt(if ((v & 4) == 0) v & 1 else (v >> 1) & 1)), timing, domain)

/** Inputs bits 0/1/2 are a/b/carry-in; outputs bit 0 sum, bit 1 carry-out. */
class DualRailFullAdder(timing: QdiTiming, domain: ResetDomain = new ResetDomain("root"))
    extends DualRailFunction(UInt(3.W), UInt(2.W), (0 until 8).map(v =>
      BigInt(Integer.bitCount(v))), timing, domain)
