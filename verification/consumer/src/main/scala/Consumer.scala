// SPDX-License-Identifier: Apache-2.0
import chisel3._
import chiselasync.bundled.{FourPhaseBuffer, TimedCapture}
import chiselasync.experimental.{UnsafeFourPhaseStage, UnsafeFourPhaseBuffer}
import chiselasync.core.AsyncModule
import chiselasync.metadata.{DelayPolicy, ExportDesign, ModelTime}
import chiselasync.primitives.{DelayLine, Latch}
import java.nio.file.Paths

class BufferExample extends FourPhaseBuffer(UInt(8.W))
// Regression-only checks that the withdrawn experiment stays reproducible in the JAR.
class StructuralBufferExample extends UnsafeFourPhaseBuffer(UInt(8.W))
class TransformExample extends UnsafeFourPhaseStage(UInt(8.W), (value: UInt) => value ^ 0x55.U(8.W))

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
    ExportDesign.emit(new BufferExample, Paths.get("generated/buffer"))
    ExportDesign.emit(new StructuralBufferExample, Paths.get("generated/structural"))
    ExportDesign.emit(new TransformExample, Paths.get("generated/transform"))
    ExportDesign.emit(new ConsumerDelay(DelayPolicy.Transport), Paths.get("generated/transport"))
    ExportDesign.emit(new ConsumerDelay(DelayPolicy.Inertial), Paths.get("generated/inertial"))
    ExportDesign.emit(new ConsumerLatch, Paths.get("generated/latch"))
    Seq("early" -> 9999L, "equal" -> 10000L, "late" -> 10001L).foreach { case (label, delay) =>
      ExportDesign.emit(new TimedCapture(UInt(8.W), ModelTime.ps(8), ModelTime(delay),
        ModelTime.ps(2), ModelTime.ps(2), (value: UInt) => value ^ 0x55.U(8.W)), Paths.get(s"generated/timed_$label"))
    }
  }
}
