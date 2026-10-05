// SPDX-License-Identifier: Apache-2.0
package chiselasync.examples

import chisel3._
import chiselasync.bundled.FourPhaseBuffer
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

class PipelineExample extends AsyncModule {
  val in = IO(Flipped(new FourPhase(UInt(8.W), Some(resetDomain))))
  val out = IO(new FourPhase(UInt(8.W), Some(resetDomain)))
  private val first = Module(new FourPhaseBuffer(UInt(8.W), resetDomain))
  private val second = Module(new FourPhaseBuffer(UInt(8.W), resetDomain))
  first.reset := reset
  second.reset := reset
  FourPhase.connect(first.in, in)
  FourPhase.connect(second.in, first.out)
  FourPhase.connect(out, second.out)
  contract.capacity(2)
  contract.channel("in", in, "input")
  contract.channel("out", out, "output")
  contract.child("first", first)
  contract.child("second", second)
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
      ExportDesign.emit(gen(), destination)
    }
  }
}
