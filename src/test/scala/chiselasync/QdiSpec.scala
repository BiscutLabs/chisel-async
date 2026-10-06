// SPDX-License-Identifier: Apache-2.0
package chiselasync

import chisel3._
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.{DelayBounds, ModelTime, QdiTiming}
import chiselasync.protocol.{Channel, DualRail}
import chiselasync.qdi._
import circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite

class QdiSpec extends AnyFunSuite {
  private val timing = QdiTiming(DelayBounds(ModelTime(1), ModelTime(10), ModelTime(2)))
  test("strong storage preserves nested payloads and explicit reset without a clock") {
    class Packet extends Bundle { val tag = Bool(); val value = SInt(5.W); val lanes = Vec(2, UInt(2.W)) }
    val text = ChiselStage.emitCHIRRTL(new DualRailStrongBuffer(new Packet, timing))
    assert(text.contains("SInt<5>")); assert(text.contains("input_completion"))
    assert(text.contains("strong_zero9")); assert(!text.contains("input clock"))
    assert(text.contains("ChiselAsyncQdiMarker_v1"))
  }
  test("QDI experiments reject zero minimum delay and invalid bounds") {
    intercept[IllegalArgumentException] { QdiTiming(DelayBounds(ModelTime(0), ModelTime(10), ModelTime(2))) }
    intercept[IllegalArgumentException] { QdiTiming(DelayBounds(ModelTime(3), ModelTime(2), ModelTime(2))) }
    assert(QdiTiming.fixed(ModelTime(1)).cells.max.fs == 1)
  }
  test("small DIMS tables require complete finite truth tables and exact output widths") {
    def emit(width: Int, table: Seq[BigInt]) = ChiselStage.emitCHIRRTL(
      new DualRailFunction(UInt(width.W), UInt(2.W), table, timing))
    intercept[IllegalArgumentException] { emit(5, Seq.fill(32)(BigInt(0))) }
    intercept[IllegalArgumentException] { emit(2, Seq(BigInt(0), BigInt(1))) }
    intercept[IllegalArgumentException] { emit(2, Seq(0, 1, 2, 4).map(BigInt(_))) }
    intercept[IllegalArgumentException] { emit(2, Seq(0, 1, 2, -1).map(BigInt(_))) }
    assert(emit(2, Seq(0, 1, 2, 3).map(BigInt(_))).contains("minterm3"))
  }
  test("constant functions retain every input minterm for indication") {
    val text = ChiselStage.emitCHIRRTL(new DualRailFunction(UInt(3.W), Bool(), Seq.fill(8)(BigInt(1)), timing))
    (0 until 8).foreach(i => assert(text.contains(s"minterm$i")))
  }
  test("named functions and typed routing elaborate through primitive boundaries") {
    val modules: Seq[() => AsyncModule] = Seq(
      () => new DualRailNot(timing), () => new DualRailAnd(timing),
      () => new DualRailOr(timing), () => new DualRailXor(timing),
      () => new DualRailSelect(timing), () => new DualRailFullAdder(timing),
      () => new DualRailFork(UInt(4.W), 3, timing),
      () => new DualRailJoin(SInt(3.W), Bool(), timing),
      () => new DualRailDemux(UInt(4.W), timing),
      () => new DualRailMerge(UInt(4.W), 2, timing))
    modules.foreach { gen =>
      val text = ChiselStage.emitCHIRRTL(gen())
      assert(text.contains("ChiselAsyncQdiMarker_v1")); assert(!text.contains("input clock"))
    }
  }
  test("routing rejects vacuous branch counts") {
    intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new DualRailFork(Bool(), 1, timing)) }
    intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new DualRailMerge(Bool(), 1, timing)) }
  }
  test("dual rail connections reject implicit resizing and reset domain mismatch") {
    intercept[IllegalArgumentException] {
      ChiselStage.emitCHIRRTL(new AsyncModule {
        val in = IO(Flipped(new Channel(UInt(2.W), resetDomain).dualRail))
        val out = IO(new Channel(UInt(3.W), resetDomain).dualRail)
        DualRail.connect(out, in)
      })
    }
    intercept[IllegalArgumentException] {
      ChiselStage.emitCHIRRTL(new AsyncModule {
        val in = IO(Flipped(new Channel(UInt(2.W), resetDomain).dualRail))
        val out = IO(new Channel(UInt(2.W), new ResetDomain("other")).dualRail)
        DualRail.connect(out, in)
      })
    }
  }
}
