// SPDX-License-Identifier: Apache-2.0
package chiselasync.examples

import chisel3._
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.bundled.{LongHoldBuffer, FourPhaseStage}
import chiselasync.protocol.FourPhase
import chiselasync.metadata.{BundledTiming, ExportDesign}
import java.nio.file.Paths

/** Compiler replication fixture, not a new FIFO/catalog component. */
class ReplicatedLane(bias: Int, domain: ResetDomain) extends AsyncModule(domain) {
  val in = IO(Flipped(new FourPhase(UInt(8.W), Some(resetDomain))))
  val out = IO(new FourPhase(UInt(8.W), Some(resetDomain)))
  private val first = asyncChild("first")(d => new LongHoldBuffer(UInt(8.W), LongHoldModels.digital, d))
  private val second = asyncChild("second")(d => new FourPhaseStage(UInt(8.W), UInt(8.W),
    (x: UInt) => x + bias.U(8.W), LongHoldModels.digital, d))
  FourPhase.connect(first.in, in)
  FourPhase.connect(second.in, first.out)
  FourPhase.connect(out, second.out)
  contract.channel("in", in, "input")
  contract.channel("out", out, "output")
}
class ReplicatedExample extends AsyncModule {
  val in = IO(Flipped(Vec(8, new FourPhase(UInt(8.W), Some(resetDomain)))))
  val out = IO(Vec(8, new FourPhase(UInt(8.W), Some(resetDomain))))
  for (i <- 0 until 8) {
    val lane = asyncChild(s"lane$i")(d => new ReplicatedLane(i % 2, d))
    FourPhase.connect(lane.in, in(i))
    FourPhase.connect(out(i), lane.out)
    contract.channel(s"in$i", in(i), "input")
    contract.channel(s"out$i", out(i), "output")
  }
}
object EmitOptimized {
  def main(args: Array[String]): Unit = {
    require(args.length == 1)
    ExportDesign.emit(new ReplicatedExample, Paths.get(args(0), "replicated"))
    ExportDesign.emit(new ReplicatedExample, Paths.get(args(0), "replicated_debug"), ExportDesign.Debug)
  }
}
