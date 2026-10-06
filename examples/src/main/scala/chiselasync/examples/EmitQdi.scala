// SPDX-License-Identifier: Apache-2.0
package chiselasync.examples

import chisel3._
import chiselasync.bundled.Joined
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.interop.{FourPhaseToDualRail, DualRailToFourPhase}
import chiselasync.metadata._
import chiselasync.protocol.{Channel, DualRail, FourPhase}
import chiselasync.qdi._
import java.nio.file.Paths

object QdiModels {
  val timing = QdiTiming(DelayBounds(ModelTime.ps(1000), ModelTime.ps(10000), ModelTime.ps(1000)))
}
class QdiPacket extends Bundle {
  val flag = Bool()
  val value = SInt(5.W)
  val lanes = Vec(2, UInt(2.W))
}

/** Duplicate a two-bit value through unequal paths, join it, then add the copies.
  * Public bundled boundaries make the value oracle independent of rail encoding.
  */
class QdiCompositionExample extends AsyncModule {
  val in = IO(Flipped(new Channel(UInt(2.W), resetDomain).bundled))
  val out = IO(new Channel(UInt(3.W), resetDomain).bundled)
  private val t = QdiModels.timing
  private val encode = asyncChild("encode")(d => new FourPhaseToDualRail(UInt(2.W), ReferenceModels.timing, ReferenceModels.phase, d))
  private val fork = asyncChild("fork")(d => new DualRailFork(UInt(2.W), 2, t, d))
  private val left = asyncChild("left")(d => new DualRailStrongBuffer(UInt(2.W), t, d))
  private val right0 = asyncChild("right0")(d => new DualRailStrongBuffer(UInt(2.W), t, d))
  private val right1 = asyncChild("right1")(d => new DualRailStrongBuffer(UInt(2.W), t, d))
  private val join = asyncChild("join")(d => new DualRailJoin(UInt(2.W), UInt(2.W), t, d))
  private val add = asyncChild("add")(d => new DualRailFunction(new Joined(UInt(2.W), UInt(2.W)), UInt(3.W),
    (0 until 16).map(v => BigInt((v & 3) + (v >> 2))), t, d))
  private val decode = asyncChild("decode")(d => new DualRailToFourPhase(UInt(3.W), ReferenceModels.timing, ReferenceModels.phase, d))
  FourPhase.connect(encode.in, in)
  DualRail.connect(fork.in, encode.out)
  DualRail.connect(left.in, fork.out(0)); DualRail.connect(right0.in, fork.out(1))
  DualRail.connect(right1.in, right0.out)
  DualRail.connect(join.left, left.out); DualRail.connect(join.right, right1.out)
  DualRail.connect(add.in, join.out); DualRail.connect(decode.in, add.out)
  FourPhase.connect(out, decode.out)
  contract.endpoint("reset", reset)
  contract.channel("in", in, "input"); contract.channel("out", out, "output")
}

object EmitQdi {
  def main(args: Array[String]): Unit = {
    require(args.length == 1)
    val t = QdiModels.timing
    val fixtures: Seq[(String, () => AsyncModule)] = Seq(
      "qdi_buffer" -> (() => new DualRailStrongBuffer(UInt(3.W), t)),
      "qdi_packet" -> (() => new DualRailStrongBuffer(new QdiPacket, t)),
      "qdi_not" -> (() => new DualRailNot(t)),
      "qdi_and" -> (() => new DualRailAnd(t)),
      "qdi_or" -> (() => new DualRailOr(t)),
      "qdi_xor" -> (() => new DualRailXor(t)),
      "qdi_select" -> (() => new DualRailSelect(t)),
      "qdi_adder" -> (() => new DualRailFullAdder(t)),
      "qdi_constant" -> (() => new DualRailFunction(UInt(3.W), Bool(), Seq.fill(8)(BigInt(1)), t)),
      "qdi_fork" -> (() => new DualRailFork(UInt(2.W), 3, t)),
      "qdi_join" -> (() => new DualRailJoin(Bool(), UInt(2.W), t)),
      "qdi_demux" -> (() => new DualRailDemux(UInt(2.W), t)),
      "qdi_merge" -> (() => new DualRailMerge(UInt(2.W), 2, t)),
      "qdi_composition" -> (() => new QdiCompositionExample))
    fixtures.foreach { case (name, gen) => ExportDesign.emit(gen(), Paths.get(args(0), name)) }
  }
}
