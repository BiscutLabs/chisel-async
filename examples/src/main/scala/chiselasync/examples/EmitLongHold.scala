// SPDX-License-Identifier: Apache-2.0
package chiselasync.examples

import chisel3._
import chiselasync.bundled.{FourPhaseStage, LongHoldBuffer}
import chiselasync.core.AsyncModule
import chiselasync.metadata.{BundledTiming, ControlDelays, DelayBounds, ExportDesign, ModelTime}
import chiselasync.protocol.FourPhase
import java.nio.file.Paths

object LongHoldModels {
  private def bounded(ns: Long) = DelayBounds(ModelTime.ps(1000), ModelTime.ps(10000), ModelTime.ps(ns * 1000))
  val digital = BundledTiming.Digital(ModelTime.ps(40000), bounded(8),
    ControlDelays(bounded(1), bounded(2), bounded(3), bounded(4)), bounded(1), ModelTime.ps(40000))
}
class LongHoldExample extends LongHoldBuffer(UInt(8.W), BundledTiming.FunctionalOnly)
class LongHoldWideExample extends LongHoldBuffer(UInt(65.W), BundledTiming.FunctionalOnly)
class LongHoldPacketExample extends LongHoldBuffer(new Packet, BundledTiming.FunctionalOnly)
class LongHoldComparisonExample extends LongHoldBuffer(UInt(40.W), LongHoldModels.digital)

class LongHoldPipelineExample extends AsyncModule {
  val in = IO(Flipped(new FourPhase(UInt(8.W), Some(resetDomain))))
  val out = IO(new FourPhase(UInt(8.W), Some(resetDomain)))
  private val first = asyncChild("first")(d => new LongHoldBuffer(UInt(8.W), BundledTiming.FunctionalOnly, d))
  private val second = asyncChild("second")(d => new LongHoldBuffer(UInt(8.W), BundledTiming.FunctionalOnly, d))
  FourPhase.connect(first.in, in)
  FourPhase.connect(second.in, first.out)
  FourPhase.connect(out, second.out)
  contract.capacity(2)
  contract.channel("in", in, "input")
  contract.channel("out", out, "output")
}

class Operands extends Bundle { val left = UInt(8.W); val right = UInt(8.W) }
class LongHoldSumExample extends FourPhaseStage(new Operands, UInt(9.W),
  (p: Operands) => p.left +& p.right, LongHoldModels.digital)

class SignedResult extends Bundle {
  val value = SInt(10.W)
  val nonnegative = Bool()
  val lanes = Vec(2, UInt(4.W))
}
class LongHoldSignedExample extends FourPhaseStage(SInt(9.W), new SignedResult, (v: SInt) => {
  val result = Wire(new SignedResult)
  result.value := v +& (-17).S(9.W)
  result.nonnegative := v >= 0.S
  result.lanes(0) := v.asUInt(3, 0)
  result.lanes(1) := v.asUInt(7, 4)
  result
}, LongHoldModels.digital)

object EmitLongHold {
  def main(args: Array[String]): Unit = {
    require(args.length == 1, "usage: EmitLongHold <output-directory>")
    Seq[(String, () => AsyncModule)](
      "longhold" -> (() => new LongHoldExample),
      "longhold_wide" -> (() => new LongHoldWideExample),
      "longhold_packet" -> (() => new LongHoldPacketExample),
      "longhold_pipeline" -> (() => new LongHoldPipelineExample),
      "longhold_comparison" -> (() => new LongHoldComparisonExample),
      "longhold_sum" -> (() => new LongHoldSumExample),
      "longhold_signed" -> (() => new LongHoldSignedExample)
    ).foreach { case (id, gen) => ExportDesign.emit(gen(), Paths.get(args(0), id)) }
  }
}
