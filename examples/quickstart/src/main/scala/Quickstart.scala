import chisel3._
import chiselasync.bundled.{FourPhaseStage, LongHoldBuffer}
import chiselasync.core.AsyncModule
import chiselasync.metadata.{BundledTiming, ControlDelays, DelayBounds, ExportDesign, ModelTime}
import chiselasync.protocol.{Channel, FourPhase}
import java.nio.file.Paths

class Operands extends Bundle {
  val a = UInt(8.W)
  val b = UInt(8.W)
}

object ExampleTiming {
  // Illustrative digital bounds, not characterized technology delays.
  private val cell = DelayBounds(ModelTime.ps(1000), ModelTime.ps(10000), ModelTime.ps(1000))
  val bundled = BundledTiming.Digital(
    matchedDelay = ModelTime.ps(25000),
    dataDelay = DelayBounds.fixed(ModelTime.ps(10000)),
    controls = ControlDelays.uniform(cell),
    latchDelay = cell,
    outputDelay = ModelTime.ps(40000)
  )
}

class AddPipeline extends AsyncModule {
  val in = IO(Flipped(new Channel(new Operands, resetDomain).bundled))
  val out = IO(new Channel(UInt(9.W), resetDomain).bundled)
  private val add = asyncChild("add")(d => new FourPhaseStage(
    new Operands, UInt(9.W), (x: Operands) => x.a +& x.b, ExampleTiming.bundled, d))
  private val hold = asyncChild("hold")(d => new LongHoldBuffer(UInt(9.W), ExampleTiming.bundled, d))
  FourPhase.connect(add.in, in)
  FourPhase.connect(hold.in, add.out)
  FourPhase.connect(out, hold.out)
  contract.channel("in", in, "input")
  contract.channel("out", out, "output")
  contract.capacity(2)
}

object EmitQuickstart extends App {
  ExportDesign.emit(new AddPipeline, Paths.get("generated"))
}
