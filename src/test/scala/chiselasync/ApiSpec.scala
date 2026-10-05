// SPDX-License-Identifier: Apache-2.0
package chiselasync

import chisel3._
import chiselasync.bundled.{FourPhaseBuffer, FourPhaseStage, StructuralFourPhaseBuffer}
import chiselasync.core.AsyncModule
import chiselasync.primitives.CElement
import chiselasync.protocol.FourPhase
import circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite

class ApiSpec extends AnyFunSuite {
  private class Packet extends Bundle {
    val flag = Bool()
    val signed = SInt(9.W)
    val words = Vec(2, UInt(33.W))
  }

  test("clockless buffer accepts nested payloads and has no implicit clock") {
    val emitted = ChiselStage.emitCHIRRTL(new FourPhaseBuffer(new Packet))
    assert(emitted.contains("ChiselAsyncFourPhaseStorage_v1"))
    assert(emitted.contains("AsyncReset"))
    assert(!emitted.contains("input clock"))
    assert(emitted.contains("parameter WIDTH = 76"))
  }

  test("a resettable C-element has explicit ports and a packaged behavioral resource") {
    val emitted = ChiselStage.emitCHIRRTL(new AsyncModule {
      val a = IO(Input(Bool()))
      val b = IO(Input(Bool()))
      val q = IO(Output(Bool()))
      val cell = Module(new CElement)
      cell.reset := reset
      cell.a := a
      cell.b := b
      q := cell.q
    })
    assert(emitted.contains("ChiselAsyncCElement_v1"))
    assert(getClass.getResource("/chiselasync/sv/ChiselAsyncCElement_v1.sv") != null)
    assert(getClass.getResource("/chiselasync/sv/ChiselAsyncFourPhaseStorage_v1.sv") != null)
  }

  test("structural storage preserves nested payloads without a behavioral controller or clock") {
    val emitted = ChiselStage.emitCHIRRTL(new StructuralFourPhaseBuffer(new Packet))
    assert(emitted.contains("ChiselAsyncLatch_v1"))
    assert(emitted.contains("parameter WIDTH = 76"))
    assert(!emitted.contains("ChiselAsyncFourPhaseStorage_v1"))
    assert(!emitted.contains("input clock"))
  }

  test("stage transform rejects an implicit payload resize") {
    val error = intercept[IllegalArgumentException] {
      ChiselStage.emitCHIRRTL(new FourPhaseStage(UInt(8.W), (value: UInt) => value.pad(9)))
    }
    assert(error.getMessage.contains("identical field types, widths and shape"))
  }

  test("unknown and zero widths are rejected before emission") {
    Seq(() => UInt(), () => UInt(0.W)).foreach { gen =>
      val error = intercept[IllegalArgumentException] {
        ChiselStage.emitCHIRRTL(new FourPhaseBuffer(gen()))
      }
      assert(error.getMessage.contains("known positive width"))
    }
  }

  test("clock payload and empty Vec are rejected") {
    val clockError = intercept[IllegalArgumentException] {
      ChiselStage.emitCHIRRTL(new FourPhaseBuffer(Clock()))
    }
    assert(clockError.getMessage.contains("unsupported payload"))
    val emptyError = intercept[IllegalArgumentException] {
      ChiselStage.emitCHIRRTL(new FourPhaseBuffer(Vec(0, Bool())))
    }
    assert(emptyError.getMessage.contains("empty Vec"))
  }

  test("explicit payload directions are rejected") {
    class Mixed extends Bundle {
      val request = UInt(4.W)
      val back = Flipped(Bool())
    }
    val error = intercept[IllegalArgumentException] {
      ChiselStage.emitCHIRRTL(new FourPhaseBuffer(new Mixed))
    }
    assert(error.getMessage.contains("explicit directions"))
  }

  test("channel connections reject implicit resizing") {
    val error = intercept[IllegalArgumentException] {
      ChiselStage.emitCHIRRTL(new RawModule {
        val in = IO(Flipped(new FourPhase(UInt(8.W))))
        val out = IO(new FourPhase(UInt(9.W)))
        FourPhase.connect(out, in)
      })
    }
    assert(error.getMessage.contains("identical field types, widths and shape"))
  }

  test("distinct aggregate shapes cannot be connected by the typed helper") {
    assertDoesNotCompile("""
      import chisel3._
      import chiselasync.protocol.FourPhase
      def incompatible(a: FourPhase[UInt], b: FourPhase[SInt]): Unit = FourPhase.connect(a, b)
    """)
  }

  test("repeated elaboration does not leak state between designs") {
    val first = ChiselStage.emitCHIRRTL(new FourPhaseBuffer(UInt(8.W)))
    val second = ChiselStage.emitCHIRRTL(new FourPhaseBuffer(UInt(65.W)))
    val repeated = ChiselStage.emitCHIRRTL(new FourPhaseBuffer(UInt(8.W)))
    assert(first.contains("parameter WIDTH = 8"))
    assert(second.contains("parameter WIDTH = 65"))
    assert(repeated.contains("parameter WIDTH = 8"))
    assert(!repeated.contains("parameter WIDTH = 65"))
  }
}
