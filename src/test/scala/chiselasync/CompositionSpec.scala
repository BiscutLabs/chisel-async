// SPDX-License-Identifier: Apache-2.0
package chiselasync

import chisel3._
import chisel3.experimental.BundleLiterals._
import chiselasync.bundled._
import chiselasync.core.AsyncModule
import chiselasync.metadata.{BundledTiming, ControlDelays, DelayBounds, ModelTime}
import circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite

class CompositionSpec extends AnyFunSuite {
  private val cell = ModelTime(1)
  private val timing = BundledTiming.Digital(ModelTime(4), DelayBounds.fixed(cell),
    ControlDelays.uniform(DelayBounds.fixed(cell)), DelayBounds.fixed(cell), ModelTime(4))
  test("controlled mux rejects vacuous fanin and registers selector/data slots separately") {
    intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new FourPhaseMux(UInt(8.W),1,timing,cell)) }
    val mux = ChiselStage.emitCHIRRTL(new FourPhaseMux(UInt(8.W),3,timing,cell))
    assert(mux.contains("select :") && mux.contains("UInt<2>"))
    assert(mux.contains("ChiselAsyncAsymmetricC_v1") && !mux.contains("input clock"))
  }
  test("registered fork rejects implicit branch resizing") {
    val typed = ChiselStage.emitCHIRRTL(new FourPhaseRegFork(UInt(8.W),UInt(9.W),SInt(9.W),
      (x: UInt) => (x +& 1.U(8.W),x.zext),timing,cell))
    assert(typed.contains("SInt<9>") && !typed.contains("input clock"))
    intercept[IllegalArgumentException] {
      ChiselStage.emitCHIRRTL(new FourPhaseRegFork(UInt(8.W),UInt(8.W),UInt(9.W),
        (x: UInt) => (x +& 1.U(8.W),x +& 1.U(8.W)),timing,cell))
    }
  }
  test("simulation presets derive strict guards from the complete worst case") {
    val t = BundledTiming.simulation(ModelTime(2),ModelTime(9),ModelTime(17))
    assert(t.matchedDelay.fs == 19 && t.outputDelay.fs == 29)
    intercept[IllegalArgumentException] { BundledTiming.simulation(ModelTime(0)) }
    intercept[IllegalArgumentException] { BundledTiming.simulation(ModelTime(9),ModelTime(2)) }
    intercept[ArithmeticException] { BundledTiming.simulation(ModelTime(1),ModelTime(Long.MaxValue)) }
  }
  test("composition rejects impossible capacities, fanout and zero-time initialization") {
    Seq(() => new FourPhaseFifo(UInt(8.W), 0, timing),
      () => new FourPhaseFifo(UInt(8.W), 1, timing, Seq(1.U(8.W), 2.U(8.W))),
      () => new FourPhaseFork(UInt(8.W), 1, cell),
      () => new FourPhaseSelect(UInt(8.W), 1, timing, cell),
      () => new FourPhaseMerge(UInt(8.W), 1, timing, cell),
      () => new InitialTokens(UInt(8.W), Seq.empty, timing, cell),
      () => new InitialTokens(UInt(8.W), Seq(1.U(8.W)), BundledTiming.FunctionalOnly, cell),
      () => new InitialTokens(UInt(8.W), Seq(1.U(8.W)), timing, ModelTime(0)),
      () => new InitialTokens(UInt(8.W), Seq(1.U(9.W)), timing, cell)
    ).foreach { gen => intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(gen()) } }
  }
  test("initialized aggregate values preserve field widths and signed values") {
    class Packet extends Bundle { val tag = UInt(3.W); val value = SInt(9.W) }
    val text = ChiselStage.emitCHIRRTL(new InitialTokens(new Packet,
      Seq((new Packet).Lit(_.tag -> 5.U, _.value -> (-17).S)), timing, cell))
    assert(text.contains("SInt<9>")); assert(!text.contains("input clock"))
  }
  test("initial values cannot depend on runtime wires") {
    intercept[IllegalArgumentException] {
      ChiselStage.emitCHIRRTL(new InitialTokens(UInt(8.W), Seq(UInt(8.W)), timing, cell))
    }
  }
  test("composition exports all typed endpoints and explicit cell boundaries") {
    val fork = ChiselStage.emitCHIRRTL(new FourPhaseFork(UInt(65.W), 3, cell))
    assert(fork.contains("COMMON = 3")); assert(fork.contains("UInt<65>"))
    val join = ChiselStage.emitCHIRRTL(new FourPhaseJoin(UInt(8.W), SInt(9.W), timing, cell))
    assert(join.contains("SInt<9>")); assert(join.contains("ChiselAsyncClosingLatch_v1"))
    val select = ChiselStage.emitCHIRRTL(new FourPhaseSelect(UInt(8.W), 3, timing, cell))
    assert(select.contains("ChiselAsyncAnd_v1")); assert(select.contains("ChiselAsyncProtocolGuard_v1"))
    val merge = ChiselStage.emitCHIRRTL(new FourPhaseMerge(UInt(8.W), 3, timing, cell))
    assert(merge.contains("ChiselAsyncProtocolGuard_v1")); assert(!merge.contains("input clock"))
  }
  test("nested construction contexts do not prefix the reserved observation ABI") {
    val text = ChiselStage.emitCHIRRTL(new AsyncModule {
      val context = {
        contract.endpoint("reset", reset)
        val child = asyncChild("storage")(d => new LongHoldBuffer(UInt(8.W), timing, d))
        child.in.req := false.B; child.in.bits := 0.U; child.out.ack := false.B
        child
      }
    })
    assert(text.contains("output ca_p_5_reset"))
    assert(text.contains("output ca_p_7_storage_10_in_request"))
    assert(!text.contains("output context_ca_p_"))
  }
}
