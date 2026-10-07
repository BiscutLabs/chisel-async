// SPDX-License-Identifier: Apache-2.0
package chiselasync.examples

import chisel3._
import chiselasync.bundled._
import chiselasync.core.AsyncModule
import chiselasync.metadata.{ClickTiming,ExportDesign}
import chiselasync.protocol.TwoPhase
import java.nio.file.Paths

/** Two native Click slots circulate one token. The second stage increments it.
  * The first stage must decouple phases to initialize one token and one bubble.
  * tick/value are observation ports, not another consumer of the token.
  */
class ClickRing extends AsyncModule {
  val start=IO(Input(Bool()))
  val tick=IO(Output(Bool())); val value=IO(Output(UInt(8.W)))
  private val seed=asyncChild("seed")(d=>new PhaseDecoupledClickBuffer(UInt(8.W),ClickTiming.Simulation,Some(7.U(8.W)),d))
  private val increment=asyncChild("increment")(d=>new ClickStage(UInt(8.W),UInt(8.W),(x:UInt)=>x+1.U,ClickTiming.Simulation,d))
  seed.start.get:=start
  TwoPhase.connect(increment.in,seed.out)
  TwoPhase.connect(seed.in,increment.out)
  tick:=seed.out.req; value:=seed.out.bits
  contract.capacity(2); contract.endpoint("reset",reset); contract.endpoint("start",start)
  contract.endpoint("tick",tick); contract.endpoint("value",value)
}

object EmitClick {
  def main(args:Array[String]):Unit={
    require(args.length==1,"Usage: EmitClick output-directory")
    val root=Paths.get(args(0)); val t=ClickTiming.Simulation
    ExportDesign.emit(new ClickBuffer(UInt(8.W),t),root.resolve("click_standard"))
    ExportDesign.emit(new PhaseDecoupledClickBuffer(UInt(8.W),t),root.resolve("click_decoupled"))
    ExportDesign.emit(new PhaseDecoupledClickBuffer(UInt(8.W),t,Some(42.U(8.W))),root.resolve("click_seeded"))
    ExportDesign.emit(new ClickFifo(UInt(8.W),3,t),root.resolve("click_fifo"))
    ExportDesign.emit(new PhaseDecoupledClickFifo(UInt(8.W),3,t),root.resolve("click_decoupled_fifo"))
    ExportDesign.emit(new ClickRing,root.resolve("click_ring"))
  }
}
