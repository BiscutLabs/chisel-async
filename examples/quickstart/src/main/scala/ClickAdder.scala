import chisel3._
import chiselasync.bundled.{ClickStage, PhaseDecoupledClickFifo}
import chiselasync.core.AsyncModule
import chiselasync.metadata.{ClickTiming, ExportDesign}
import chiselasync.protocol.TwoPhase
import java.nio.file.Paths

class ClickOperands extends Bundle {
  val a = UInt(8.W)
  val b = UInt(8.W)
  val tag = UInt(4.W)
}

class ClickSum extends Bundle {
  val sum = UInt(9.W)
  val tag = UInt(4.W)
}

/** A native Click adder followed by two phase-decoupled storage slots.
  * All three slots reset empty. Results preserve the input tag and the carry.
  */
class ClickAdder(timing: ClickTiming = ClickTiming.Simulation) extends AsyncModule {
  val in = twoPhaseInput("in", new ClickOperands)
  val out = twoPhaseOutput("out", new ClickSum)

  private val add = asyncChild("add") { domain =>
    new ClickStage(
      inGen = new ClickOperands,
      outGen = new ClickSum,
      transform = (operands: ClickOperands) => {
        val result = Wire(new ClickSum)
        result.sum := operands.a +& operands.b
        result.tag := operands.tag
        result
      },
      timing = timing,
      domain = domain)
  }
  private val queue = asyncChild("queue") { domain =>
    new PhaseDecoupledClickFifo(
      gen = new ClickSum, depth = 2, timing = timing, domain = domain)
  }

  TwoPhase.connect(add.in, in)
  TwoPhase.connect(queue.in, add.out)
  TwoPhase.connect(out, queue.out)
  contract.capacity(3)
}

object EmitClickAdder extends App {
  ExportDesign.emit(new ClickAdder, Paths.get("generated-click"))
}
