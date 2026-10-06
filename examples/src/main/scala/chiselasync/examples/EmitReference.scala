// SPDX-License-Identifier: Apache-2.0
package chiselasync.examples

import chisel3._
import chiselasync.bundled._
import chiselasync.clocked._
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.interop._
import chiselasync.metadata._
import chiselasync.protocol.{Channel, FourPhase, DualRail, TwoPhase}
import chiselasync.qdi.DualRailAdder2
import java.nio.file.Paths

object ReferenceModels {
  val cell = ModelTime.ps(1000)
  val bounds = DelayBounds(cell, ModelTime.ps(10000), cell)
  val timing = BundledTiming.Digital(ModelTime.ps(40000), bounds,
    ControlDelays.uniform(bounds), bounds, ModelTime.ps(40000))
  val phase = PhaseTiming(bounds, ModelTime.ps(40000))
  def sum(x: UInt): UInt = x(1, 0) +& x(3, 2)
}

class ClockedAdder(domain: ResetDomain) extends ClockedBridge(domain, 2) {
  private val input = new Channel(UInt(4.W), resetDomain)
  private val output = new Channel(UInt(3.W), resetDomain)
  val in = IO(Flipped(input.decoupled)); val out = IO(output.decoupled)
  withClockAndReset(clock, localReset) {
    val full = RegInit(false.B); val data = RegInit(0.U(3.W))
    in.ready := !full && !localReset.asBool
    out.valid := full && !localReset.asBool; out.bits := data
    when(in.fire) { data := ReferenceModels.sum(in.bits); full := true.B }
    when(out.fire) { full := false.B }
  }
  contract.clockedChannel("in", in, clock, input, "input")
  contract.clockedChannel("out", out, clock, output, "output")
  contract.capacity(1); contract.endpoint("reset", reset)
}

/** Shared public boundary and function; distinct capacities and conversion costs. */
class AdderReference(style: String) extends AsyncModule {
  import ReferenceModels._
  val in = IO(Flipped(new Channel(UInt(4.W), resetDomain).bundled))
  val out = IO(new Channel(UInt(3.W), resetDomain).bundled)
  style match {
    case "behavioral" =>
      val core = asyncChild("core")(d => new FourPhaseBuffer(UInt(3.W), d))
      core.in.req := in.req; core.in.bits := sum(in.bits); in.ack := core.in.ack
      FourPhase.connect(out, core.out); contract.capacity(1)
    case "bundled" =>
      val core = asyncChild("core")(d => new FourPhaseStage(UInt(4.W), UInt(3.W), sum, timing, d))
      FourPhase.connect(core.in, in); FourPhase.connect(out, core.out); contract.capacity(1)
    case "qdi" =>
      val encode = asyncChild("encode")(d => new FourPhaseToDualRail(UInt(4.W), timing, phase, d))
      val core = asyncChild("core")(d => new DualRailAdder2(cell, d))
      val decode = asyncChild("decode")(d => new DualRailToFourPhase(UInt(3.W), timing, phase, d))
      FourPhase.connect(encode.in, in); DualRail.connect(core.in, encode.out)
      DualRail.connect(decode.in, core.out); FourPhase.connect(out, decode.out)
      // The WCHB is not fully decoupled: three physical storage sites reserve
      // at most two distinct accepted tokens in this closed-backpressure chain.
      contract.capacity(2)
    case "gals" =>
      val sourceClock = IO(Input(Clock())); val sinkClock = IO(Input(Clock()))
      val receive = asyncChild("receive")(d => new FourPhaseToDecoupled(UInt(4.W), domain=d))
      val compute = asyncChild("compute")(d => new ClockedAdder(d))
      val send = asyncChild("send")(d => new DecoupledToFourPhase(UInt(3.W), domain=d))
      val toTwo = asyncChild("toTwo")(d => new FourPhaseToTwoPhase(UInt(3.W), timing, phase, d))
      val toFour = asyncChild("toFour")(d => new TwoPhaseToFourPhase(UInt(3.W), timing, phase, d))
      val sink = asyncChild("sink")(d => new FourPhaseToDecoupled(UInt(3.W), domain=d))
      val exit = asyncChild("exit")(d => new DecoupledToFourPhase(UInt(3.W), domain=d))
      receive.clock := sourceClock; compute.clock := sourceClock; send.clock := sourceClock
      sink.clock := sinkClock; exit.clock := sinkClock
      FourPhase.connect(receive.in, in)
      compute.in :<>= receive.out; send.in :<>= compute.out
      FourPhase.connect(toTwo.in, send.out); TwoPhase.connect(toFour.in, toTwo.out)
      FourPhase.connect(sink.in, toFour.out); exit.in :<>= sink.out
      FourPhase.connect(out, exit.out); contract.capacity(5)
    case _ => throw new IllegalArgumentException("unknown reference style")
  }
  contract.channel("in", in, "input"); contract.channel("out", out, "output")
  contract.endpoint("reset", reset)
}

object EmitReference {
  def main(args: Array[String]): Unit = {
    require(args.length == 1)
    Seq("behavioral", "bundled", "qdi", "gals").foreach { style =>
      ExportDesign.emit(new AdderReference(style), Paths.get(args(0), s"reference_$style"))
    }
    ExportDesign.emit(new DualRailAdder2(ReferenceModels.cell), Paths.get(args(0), "reference_core"))
  }
}
