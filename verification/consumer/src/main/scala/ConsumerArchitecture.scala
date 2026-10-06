// SPDX-License-Identifier: Apache-2.0


import chisel3._
import chiselasync.core.AsyncModule
import chiselasync.clocked.{DecoupledToFourPhase, FourPhaseToDecoupled}
import chiselasync.bundled.LongHoldBuffer
import chiselasync.protocol.{Channel, FourPhase}
import chiselasync.qdi.DualRailBuffer
import chiselasync.metadata.{ExportDesign, ModelTime}
import java.nio.file.Paths

class DualRailExample extends DualRailBuffer(UInt(8.W), ModelTime.ps(1000))
class ToAsyncExample extends DecoupledToFourPhase(UInt(8.W))
class ToClockedExample extends FourPhaseToDecoupled(UInt(8.W))
class BridgeRoundTripExample extends AsyncModule {
  val sourceClock = IO(Input(Clock()))
  val sinkClock = IO(Input(Clock()))
  val channel = new Channel(UInt(8.W), resetDomain)
  val in = IO(Flipped(channel.decoupled))
  val out = IO(channel.decoupled)
  private val source = asyncChild("source")(d => new DecoupledToFourPhase(UInt(8.W), domain=d))
  private val storage = asyncChild("storage")(d => new LongHoldBuffer(UInt(8.W), ConsumerTiming.digital, d))
  private val sink = asyncChild("sink")(d => new FourPhaseToDecoupled(UInt(8.W), domain=d))
  source.clock := sourceClock
  sink.clock := sinkClock
  source.in :<>= in
  FourPhase.connect(storage.in, source.out)
  FourPhase.connect(sink.in, storage.out)
  out :<>= sink.out
  contract.capacity(2)
  contract.clockedChannel("in", in, sourceClock, channel, "input")
  contract.clockedChannel("out", out, sinkClock, channel, "output")
  contract.endpoint("reset", reset)
}
object ConsumerArchitecture {
  def main(args: Array[String]): Unit = {
    require(args.length == 1)
    Seq[(String, () => AsyncModule)]("dualrail" -> (() => new DualRailExample),
      "to_async" -> (() => new ToAsyncExample), "to_clocked" -> (() => new ToClockedExample),
      "bridge_roundtrip" -> (() => new BridgeRoundTripExample)).foreach {
      case (id, gen) => ExportDesign.emit(gen(), Paths.get(args(0), id))
    }
  }
}
