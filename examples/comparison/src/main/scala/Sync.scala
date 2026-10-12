// SPDX-License-Identifier: Apache-2.0
import chisel3._
import chisel3.util._
import circt.stage.ChiselStage

/** The quickstart designs again, synchronous: the same algorithms with ordinary
  * Decoupled interfaces and a clock, for a like-for-like comparison through the
  * same physical flow. Nothing here uses chisel-async.
  */
class SyncOperands extends Bundle { val a = UInt(8.W); val b = UInt(8.W) }

/** AddPipeline: an adder stage and a holding stage, one token per clock. */
class SyncAddPipeline extends Module {
  val in = IO(Flipped(Decoupled(new SyncOperands)))
  val out = IO(Decoupled(UInt(9.W)))
  val add = Module(new Queue(UInt(9.W), 1, pipe = true))
  add.io.enq.valid := in.valid
  add.io.enq.bits := in.bits.a +& in.bits.b
  in.ready := add.io.enq.ready
  out <> Queue(add.io.deq, 1, pipe = true)
}

/** Gcd: Euclid by subtraction, one subtraction per clock, finishing on a == b,
  * a == 0 or b == 0, and answering b when a == 0, as the asynchronous Gcd does.
  */
class SyncGcd extends Module {
  val in = IO(Flipped(Decoupled(new SyncOperands)))
  val out = IO(Decoupled(UInt(8.W)))
  val busy = RegInit(false.B)
  val a = Reg(UInt(8.W))
  val b = Reg(UInt(8.W))
  val finished = a === b || a === 0.U || b === 0.U
  in.ready := !busy
  out.valid := busy && finished
  out.bits := Mux(a === 0.U, b, a)
  when(in.fire) {
    a := in.bits.a; b := in.bits.b; busy := true.B
  }.elsewhen(busy && !finished) {
    when(a > b) { a := a - b }.otherwise { b := b - a }
  }
  when(out.fire) { busy := false.B }
}

/** Usage: EmitSync DESIGN OUTPUT_DIRECTORY */
object EmitSync {
  def main(args: Array[String]): Unit = {
    require(args.length == 2, "Usage: EmitSync DESIGN OUTPUT_DIRECTORY")
    val gen: () => RawModule = args(0) match {
      case "SyncAddPipeline" => () => new SyncAddPipeline
      case "SyncGcd" => () => new SyncGcd
      case other => throw new IllegalArgumentException(s"unknown design $other")
    }
    ChiselStage.emitSystemVerilogFile(gen(), Array("--target-dir", args(1)),
      Array("--disable-all-randomization", "--strip-debug-info"))
  }
}
