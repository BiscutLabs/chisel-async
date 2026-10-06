// SPDX-License-Identifier: Apache-2.0
package chiselasync

import chisel3._
import chiselasync.bundled.{FourPhaseStage, LongHoldBuffer}
import chiselasync.metadata.{BundledTiming, ControlDelays, DelayBounds, ModelTime}
import chiselasync.primitives.AsymmetricCElement
import circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite

class LongHoldSpec extends AnyFunSuite {
  class Operands extends Bundle { val a = UInt(8.W); val b = UInt(8.W) }

  test("published stage preserves a type-changing carry and explicit clockless control") {
    val text = ChiselStage.emitCHIRRTL(new FourPhaseStage(new Operands, UInt(9.W),
      (p: Operands) => p.a +& p.b, BundledTiming.FunctionalOnly))
    assert(text.contains("ChiselAsyncAsymmetricC_v1"))
    assert(text.contains("ChiselAsyncClosingLatch_v1"))
    assert(text.contains("parameter WIDTH = 9"))
    assert(text.contains("COMMON_INVERT = 1"))
    assert(!text.contains("input clock"))
  }

  test("stage rejects a transform that silently discards the carry") {
    val error = intercept[IllegalArgumentException] {
      ChiselStage.emitCHIRRTL(new FourPhaseStage(new Operands, UInt(9.W),
        (p: Operands) => p.a + p.b, BundledTiming.FunctionalOnly))
    }
    assert(error.getMessage.contains("identical field types, widths and shape"))
  }

  test("a signed transform can produce a distinct aggregate type") {
    class Result extends Bundle { val sum = SInt(10.W); val flag = Bool() }
    val text = ChiselStage.emitCHIRRTL(new FourPhaseStage(SInt(9.W), new Result, (v: SInt) => {
      val result = Wire(new Result)
      result.sum := v +& (-17).S(9.W)
      result.flag := v >= 0.S
      result
    }, BundledTiming.FunctionalOnly))
    assert(text.contains("parameter WIDTH = 11"))
  }

  test("timed mode rejects zero, insufficient, and overflowing timing margins") {
    def timing(matched: Long, data: Long, cell: Long, latch: Long, output: Long) =
      BundledTiming.Digital(ModelTime(matched), DelayBounds.fixed(ModelTime(data)),
        ControlDelays.uniform(DelayBounds.fixed(ModelTime(cell))), DelayBounds.fixed(ModelTime(latch)), ModelTime(output))
    assert(timing(40, 8, 1, 1, 40).mode == "digital-model")
    intercept[IllegalArgumentException] { timing(8, 8, 1, 1, 40) }
    intercept[IllegalArgumentException] { timing(40, 8, 0, 1, 40) }
    intercept[IllegalArgumentException] { timing(40, 8, 1, 1, 3) }
    intercept[ArithmeticException] { timing(40, 8, Long.MaxValue, 1, 40) }
  }

  test("n-ary cells reject invalid dimensions and input inversion masks") {
    Seq(() => new AsymmetricCElement(0,0,0,ModelTime(0)),
        () => new AsymmetricCElement(1,0,0,ModelTime(0), risingInvert=1),
        () => new AsymmetricCElement(3,0,0,ModelTime(0), commonInvert=8)).foreach { gen =>
      intercept[IllegalArgumentException] {
        ChiselStage.emitCHIRRTL(new RawModule { val cell = Module(gen()) })
      }
    }
    assert(getClass.getResource("/chiselasync/sv/ChiselAsyncAsymmetricC_v1.sv") != null)
    assert(getClass.getResource("/chiselasync/sv/ChiselAsyncClosingLatch_v1.sv") != null)
    assert(getClass.getResource("/chiselasync/sv/ChiselAsyncControlGate_v1.sv") != null)
  }

  test("timing guards use independent worst-case bounds rather than model values") {
    val one = DelayBounds.fixed(ModelTime(1))
    val slow = DelayBounds(ModelTime(1), ModelTime(10), ModelTime(2))
    val cells = ControlDelays(one, slow, one, one)
    intercept[IllegalArgumentException] {
      BundledTiming.Digital(ModelTime(20), slow, cells, one, ModelTime(21))
    }
    val policy = BundledTiming.Digital(ModelTime(20), slow, cells, one, ModelTime(22))
    assert(policy.minimumOutputGuard.fs == 21)
    intercept[IllegalArgumentException] { DelayBounds(ModelTime(3), ModelTime(2), ModelTime(2)) }
    val text = ChiselStage.emitCHIRRTL(new LongHoldBuffer(UInt(8.W), policy))
    assert(text.contains("parameter DELAY_FS = 2"))
  }
}
