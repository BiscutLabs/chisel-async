// SPDX-License-Identifier: Apache-2.0
package chiselasync.qdi

import chisel3._
import chiselasync.bundled.CompositionCells
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.ModelTime
import chiselasync.protocol.{Channel, DualRail}

/** Exhaustive DIMS example: bits 1:0 + bits 3:2 -> unsigned three-bit sum.
  * Four-input C minterms indicate every input's valid AND spacer phase.
  * Disjoint OR covers feed a WCHB output stage. Atomic cells and ideal forks;
  * no physical QDI mapping or scalable arithmetic implementation is claimed.
  * Topology: Sparso/Furber tutorial, section 5.5.1 (DIMS).
  */
class DualRailAdder2(cellDelay: ModelTime, domain: ResetDomain = new ResetDomain("root"))
    extends AsyncModule(domain) {
  val in = IO(Flipped(new Channel(UInt(4.W), resetDomain).dualRail))
  val out = IO(new Channel(UInt(3.W), resetDomain).dualRail)
  private val cells = new CompositionCells(this, cellDelay)
  private val terms = (0 until 16).map { value =>
    cells.c(s"minterm$value", (0 until 4).map { bit =>
      if ((value & (1 << bit)) == 0) in.zero(bit) else in.one(bit)
    })
  }
  private val result = Wire(new Channel(UInt(3.W), resetDomain).dualRail)
  private def rail(bit: Int, one: Boolean): Bool = cells.or(s"sum${bit}_${if (one) "one" else "zero"}",
    (0 until 16).filter { value => ((((value & 3) + (value >> 2)) >> bit) & 1) == (if (one) 1 else 0) }
      .map(terms), "disjoint DIMS minterms; monotonic valid/spacer; ideal forks")
  result.zero := VecInit((0 until 3).map(rail(_, false))).asUInt
  result.one := VecInit((0 until 3).map(rail(_, true))).asUInt
  private val storage = asyncChild("storage")(d => new DualRailBuffer(UInt(3.W), cellDelay, d))
  DualRail.connect(storage.in, result); DualRail.connect(out, storage.out)
  in.ack := result.ack
  contract.capacity(1)
  contract.dualRailChannel("in", in, "input"); contract.dualRailChannel("out", out, "output")
}
