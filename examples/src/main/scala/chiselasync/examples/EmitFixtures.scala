// SPDX-License-Identifier: Apache-2.0
package chiselasync.examples

import chisel3._
import chiselasync.bundled.FourPhaseBuffer
import chiselasync.experimental.{UnsafeFourPhaseStage, UnsafeFourPhaseBuffer}
import chiselasync.core.AsyncModule
import chiselasync.primitives.CElement
import chiselasync.metadata.{DelayPolicy, ExportDesign}
import chiselasync.protocol.FourPhase
import circt.stage.ChiselStage
import java.nio.file.{Files, Paths}

class BufferExample extends FourPhaseBuffer(UInt(8.W))

class WideBufferExample extends FourPhaseBuffer(UInt(65.W))

class Packet extends Bundle {
  val tag = UInt(3.W)
  val signed = SInt(9.W)
  val lanes = Vec(2, UInt(5.W))
}

class PacketBufferExample extends FourPhaseBuffer(new Packet)

// Withdrawn controller: these fixtures preserve the historical regression corpus.
class StructuralBufferExample extends UnsafeFourPhaseBuffer(UInt(8.W))
class StructuralWideExample extends UnsafeFourPhaseBuffer(UInt(65.W))
class StructuralPacketExample extends UnsafeFourPhaseBuffer(new Packet)
class TransformExample extends UnsafeFourPhaseStage(UInt(8.W), (value: UInt) => value ^ 0x55.U(8.W))

class PipelineExample extends AsyncModule {
  val in = IO(Flipped(new FourPhase(UInt(8.W), Some(resetDomain))))
  val out = IO(new FourPhase(UInt(8.W), Some(resetDomain)))
  private val first = asyncChild("first")(domain => new FourPhaseBuffer(UInt(8.W), domain))
  private val second = asyncChild("second")(domain => new FourPhaseBuffer(UInt(8.W), domain))
  FourPhase.connect(first.in, in)
  FourPhase.connect(second.in, first.out)
  FourPhase.connect(out, second.out)
  contract.capacity(2)
  contract.channel("in", in, "input")
  contract.channel("out", out, "output")
}

class StructuralPipelineExample extends AsyncModule {
  val in = IO(Flipped(new FourPhase(UInt(8.W), Some(resetDomain))))
  val out = IO(new FourPhase(UInt(8.W), Some(resetDomain)))
  private val first = asyncChild("first")(domain => new UnsafeFourPhaseBuffer(UInt(8.W), domain))
  private val second = asyncChild("second")(domain => new UnsafeFourPhaseBuffer(UInt(8.W), domain))
  FourPhase.connect(first.in, in)
  FourPhase.connect(second.in, first.out)
  FourPhase.connect(out, second.out)
  contract.capacity(2)
  contract.channel("in", in, "input")
  contract.channel("out", out, "output")
}

class CElementExample extends AsyncModule {
  val a = IO(Input(Bool()))
  val b = IO(Input(Bool()))
  val q = IO(Output(Bool()))
  private val cell = Module(new CElement)
  cell.reset := reset
  cell.a := a
  cell.b := b
  q := cell.q
  contract.primitive("cell", cell, Map.empty, contract.endpoint("reset", reset), "reset clears state")
  contract.endpoint("a", a)
  contract.endpoint("b", b)
  contract.endpoint("q", q)
}

object EmitFixtures {
  def main(args: Array[String]): Unit = {
    require(args.length == 1, "usage: EmitFixtures <output-directory>")
    val fixtures: Seq[(String, () => AsyncModule)] = Seq(
      "buffer" -> (() => new BufferExample),
      "wide" -> (() => new WideBufferExample),
      "packet" -> (() => new PacketBufferExample),
      "pipeline" -> (() => new PipelineExample),
      "structural" -> (() => new StructuralBufferExample),
      "structural_wide" -> (() => new StructuralWideExample),
      "structural_packet" -> (() => new StructuralPacketExample),
      "structural_pipeline" -> (() => new StructuralPipelineExample),
      "transform" -> (() => new TransformExample),
      "celement" -> (() => new CElementExample),
      "latch" -> (() => new LatchExample),
      "transport" -> (() => new DelayExample(DelayPolicy.Transport)),
      "inertial" -> (() => new DelayExample(DelayPolicy.Inertial)),
      "timed_early" -> (() => new TimedExample(9999)),
      "timed_equal" -> (() => new TimedExample(10000)),
      "timed_late" -> (() => new TimedExample(10001))
    )
    fixtures.foreach { case (name, gen) =>
      val destination = Paths.get(args(0), name).toAbsolutePath
      Files.createDirectories(destination)
      // Preserve the withdrawn controller's original Boolean decomposition for
      // its historical delay counterexample; production fixtures use release.
      val mode = if (name.startsWith("structural") || name == "transform") ExportDesign.Debug else ExportDesign.Optimized
      ExportDesign.emit(gen(), destination, mode)
    }
  }
}
