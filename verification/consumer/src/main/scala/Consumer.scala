// SPDX-License-Identifier: Apache-2.0
import chisel3._
import chiselasync.bundled.{FourPhaseBuffer, FourPhaseStage, LongHoldBuffer, TimedCapture}
import chiselasync.experimental.{UnsafeFourPhaseStage, UnsafeFourPhaseBuffer}
import chiselasync.core.AsyncModule
import chiselasync.metadata.{BundledTiming, ControlDelays, DelayBounds, DelayPolicy, ExportDesign, ModelTime}
import chiselasync.primitives.{DelayLine, Latch}
import java.nio.file.Paths

class BufferExample extends FourPhaseBuffer(UInt(8.W))
// Regression-only checks that the withdrawn experiment stays reproducible in the JAR.
class StructuralBufferExample extends UnsafeFourPhaseBuffer(UInt(8.W))
class TransformExample extends UnsafeFourPhaseStage(UInt(8.W), (value: UInt) => value ^ 0x55.U(8.W))

object ConsumerTiming {
  private def bounded(ns: Long) = DelayBounds(ModelTime.ps(1000), ModelTime.ps(10000), ModelTime.ps(ns * 1000))
  val digital = BundledTiming.Digital(ModelTime.ps(40000), bounded(8),
    ControlDelays(bounded(1), bounded(2), bounded(3), bounded(4)), bounded(1), ModelTime.ps(40000))
}
class LongHoldExample extends LongHoldBuffer(UInt(8.W), BundledTiming.FunctionalOnly)
class LongHoldComparisonExample extends LongHoldBuffer(UInt(40.W), ConsumerTiming.digital)
class Operands extends Bundle { val left = UInt(8.W); val right = UInt(8.W) }
class LongHoldSumExample extends FourPhaseStage(new Operands, UInt(9.W),
  (p: Operands) => p.left +& p.right, ConsumerTiming.digital)
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
}, ConsumerTiming.digital)

class ConsumerDelay(policy: DelayPolicy) extends AsyncModule {
  val d = IO(Input(UInt(9.W)))
  val q = IO(Output(UInt(9.W)))
  val cell = Module(new DelayLine(9, ModelTime.ps(10), policy))
  cell.reset := reset
  cell.d := d
  q := cell.q
  contract.primitive("delay", cell, Map("WIDTH" -> BigInt(9), "DELAY_FS" -> BigInt(10000),
    "POLICY" -> BigInt(policy.code)), contract.endpoint("reset", reset), "reset cancels pending events")
  contract.endpoint("data", d)
  contract.endpoint("q", q)
}

class ConsumerLatch extends AsyncModule {
  val d = IO(Input(UInt(9.W)))
  val enable = IO(Input(Bool()))
  val q = IO(Output(UInt(9.W)))
  val cell = Module(new Latch(9, 0x12))
  cell.reset := reset
  cell.d := d
  cell.enable := enable
  q := cell.q
  contract.primitive("latch", cell, Map("WIDTH" -> BigInt(9), "RESET_VALUE" -> BigInt(0x12)),
    contract.endpoint("reset", reset), "transparent latch")
  contract.endpoint("data", d)
  contract.endpoint("enable", enable)
  contract.endpoint("q", q)
}

object Consumer {
  def main(args: Array[String]): Unit = {
    ConsumerArchitecture.main(Array("generated"))
    ConsumerComposition.main(Array("generated"))
    ConsumerPhase.main(Array("generated"))
    chiselasync.examples.EmitReference.main(Array("generated"))
    ExportDesign.emit(new BufferExample, Paths.get("generated/buffer"))
    ExportDesign.emit(new StructuralBufferExample, Paths.get("generated/structural"), ExportDesign.Debug)
    ExportDesign.emit(new TransformExample, Paths.get("generated/transform"), ExportDesign.Debug)
    ExportDesign.emit(new LongHoldExample, Paths.get("generated/longhold"))
    ExportDesign.emit(new LongHoldComparisonExample, Paths.get("generated/longhold_comparison"))
    ExportDesign.emit(new LongHoldSumExample, Paths.get("generated/longhold_sum"))
    ExportDesign.emit(new LongHoldSignedExample, Paths.get("generated/longhold_signed"))
    ExportDesign.emit(new ConsumerDelay(DelayPolicy.Transport), Paths.get("generated/transport"))
    ExportDesign.emit(new ConsumerDelay(DelayPolicy.Inertial), Paths.get("generated/inertial"))
    ExportDesign.emit(new ConsumerLatch, Paths.get("generated/latch"))
    Seq("early" -> 9999L, "equal" -> 10000L, "late" -> 10001L).foreach { case (label, delay) =>
      ExportDesign.emit(new TimedCapture(UInt(8.W), ModelTime.ps(8), ModelTime(delay),
        ModelTime.ps(2), ModelTime.ps(2), (value: UInt) => value ^ 0x55.U(8.W)), Paths.get(s"generated/timed_$label"))
    }
  }
}
