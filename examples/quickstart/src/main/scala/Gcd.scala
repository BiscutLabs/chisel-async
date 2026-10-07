import chisel3._
import chiselasync.bundled._
import chiselasync.core.AsyncModule
import chiselasync.metadata.{BundledTiming, ExportDesign, ModelTime}
import chiselasync.protocol.{Channel, FourPhase}
import java.nio.file.Paths

class GcdOperands extends Bundle { val a = UInt(8.W); val b = UInt(8.W) }

/** Euclid's subtraction algorithm, including gcd(0,b), gcd(a,0) and gcd(0,0).
  * The initial selector admits a job; each iteration selects feedback until done.
  * All state and control use public library components, with no implicit clock.
  */
class Gcd extends AsyncModule {
  private val timing = BundledTiming.Simulation
  private val cell = ModelTime.ps(1000)
  val in = fourPhaseInput("in", new GcdOperands)
  val out = fourPhaseOutput("out", UInt(8.W))
  private val mux = asyncChild("mux")(d => new FourPhaseMux(new GcdOperands, 2, timing, cell, d))
  private val selectors = asyncChild("selectors")(d => new FourPhaseFifo(UInt(1.W), 2, timing,
    Seq(0.U(1.W)), cell, d))
  private val step = asyncChild("step")(d => new FourPhaseRegFork(new GcdOperands,
    new Selected(new GcdOperands, 2), UInt(1.W), (p: GcdOperands) => {
      val finished = p.a === p.b || p.a === 0.U || p.b === 0.U
      val route = Wire(new Selected(new GcdOperands, 2))
      route.index := finished.asUInt
      route.data.a := Mux(!finished && p.a > p.b, p.a - p.b, p.a)
      route.data.b := Mux(!finished && p.b > p.a, p.b - p.a, p.b)
      val next = Wire(UInt(1.W)); next := Mux(finished, 0.U(1.W), 1.U(1.W))
      (route, next)
    }, timing, cell, d))
  private val demux = asyncChild("demux")(d => new FourPhaseDemux(new GcdOperands, 2, timing, cell, d))
  private val result = asyncChild("result")(d => new FourPhaseStage(new GcdOperands, UInt(8.W),
    (p: GcdOperands) => Mux(p.a === 0.U, p.b, p.a), timing, d))
  FourPhase.connect(mux.in(0), in); FourPhase.connect(mux.in(1), demux.out(0))
  FourPhase.connect(mux.select, selectors.out); FourPhase.connect(step.in, mux.out)
  FourPhase.connect(demux.in, step.left); FourPhase.connect(selectors.in, step.right)
  FourPhase.connect(result.in, demux.out(1)); FourPhase.connect(out, result.out)
}

object EmitGcd extends App { ExportDesign.emit(new Gcd, Paths.get("generated-gcd")) }
