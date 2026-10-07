import chisel3._
import chiselasync.bundled.{FourPhaseStage, LongHoldBuffer}
import chiselasync.core.AsyncModule
import chiselasync.metadata.{BundledTiming, ExportDesign}
import chiselasync.protocol.FourPhase
import java.nio.file.Paths

class Operands extends Bundle {
  val a = UInt(8.W)
  val b = UInt(8.W)
}

object ExampleTiming {
  // Illustrative digital bounds, not characterized technology delays.
  val bundled = BundledTiming.Simulation
}

class AddPipeline extends AsyncModule {
  val in = fourPhaseInput("in", new Operands)
  val out = fourPhaseOutput("out", UInt(9.W))
  private val add = asyncChild("add")(d => new FourPhaseStage(
    new Operands, UInt(9.W), (x: Operands) => x.a +& x.b, ExampleTiming.bundled, d))
  private val hold = asyncChild("hold")(d => new LongHoldBuffer(UInt(9.W), ExampleTiming.bundled, d))
  FourPhase.connect(add.in, in)
  FourPhase.connect(hold.in, add.out)
  FourPhase.connect(out, hold.out)
  contract.capacity(2)
}

object EmitQuickstart extends App {
  ExportDesign.emit(new AddPipeline, Paths.get("generated"))
}
