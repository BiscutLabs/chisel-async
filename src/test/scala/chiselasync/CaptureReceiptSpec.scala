// SPDX-License-Identifier: Apache-2.0
package chiselasync

import chisel3._
import chiselasync.clocked._
import chiselasync.core.AsyncModule
import circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite

private class ReceiptPayload extends Bundle {
  val tag = UInt(3.W)
  val samples = Vec(2, SInt(9.W))
  val flag = Bool()
}

/** Deliberately includes the unsafe consumer for the structural negative control. */
private class ReceiptConsumer(qualified: Boolean) extends RawModule {
  val clock = IO(Input(Clock()))
  val reset = IO(Input(AsyncReset()))
  val ready = IO(Input(Bool()))
  val in = IO(Input(UInt(8.W)))
  val req = IO(Input(Bool()))
  val ack = IO(Output(Bool()))
  val observed = IO(Output(UInt(8.W)))
  val receipt = Module(new FourPhaseCaptureReceipt(UInt(8.W)))
  receipt.clock := clock
  receipt.reset := reset
  receipt.in.bits := in
  receipt.in.req := req
  receipt.out.ready := ready
  ack := receipt.in.ack
  withClockAndReset(clock, reset) {
    val captured = RegInit(0.U(8.W))
    if (qualified) {
      when(receipt.out.fire) { captured := receipt.out.bits }
    } else {
      when(ready) { captured := receipt.out.bits }
    }
    observed := captured
  }
}

class CaptureReceiptSpec extends AnyFunSuite {
  private def receipt[T <: Data](click: Boolean, gen: T, stages: Int = 2,
      settle: Int = 1, mask: Boolean = false): AsyncModule =
    if (click) new ClickCaptureReceipt(gen, stages, settle, mask)
    else new FourPhaseCaptureReceipt(gen, stages, settle, mask)

  test("retained receipts preserve typed payloads and native protocol without payload registers") {
    for (click <- Seq(false, true); mask <- Seq(false, true)) {
      val text = ChiselStage.emitCHIRRTL(receipt(click, new ReceiptPayload, mask = mask))
      assert(text.contains("tag : UInt<3>") && text.contains("samples : SInt<9>[2]") &&
        text.contains("flag : UInt<1>"))
      val regs = text.linesIterator.filter(_.trim.startsWith("regreset ")).toSeq
      assert(regs.size == 4, regs.mkString("\n")) // release vector, sync vector, state, ACK
      assert(regs.forall(line => Seq("localReset_release", "request_stages", "state", "acknowledge").exists(
        name => line.trim.startsWith(s"regreset $name :"))), regs.mkString("\n"))
      assert(!text.contains("FourPhaseToTwoPhase") && !text.contains("TwoPhaseToFourPhase"))
      assert(!text.contains("smem ") && !text.contains("cmem "))
    }
  }

  test("timing parameters reject unsupported values and allocate only required control storage") {
    for (click <- Seq(false, true)) {
      intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(receipt(click, UInt(8.W), stages = 1)) }
      intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(receipt(click, UInt(8.W), settle = -1)) }
      for (stages <- Seq(2, 3); settle <- Seq(0, 1, 2, 3, 8)) {
        val text = ChiselStage.emitCHIRRTL(receipt(click, UInt(337.W), stages, settle))
        val regs = text.linesIterator.filter(_.trim.startsWith("regreset ")).toSeq
        assert(regs.size == (if (settle > 1) 5 else 4), regs.mkString("\n"))
        assert(!regs.exists(_.contains("UInt<337>")))
      }
      intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(receipt(click, UInt())) }
      intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(receipt(click, Clock())) }
    }
  }

  test("optional invalid mask is combinational typed zero and has no storage") {
    for (click <- Seq(false, true)) {
      val masked = ChiselStage.emitCHIRRTL(receipt(click, UInt(8.W), mask = true))
      val direct = ChiselStage.emitCHIRRTL(receipt(click, UInt(8.W)))
      assert(masked.contains("mux(out.valid, in.bits,"), masked)
      assert(direct.contains("connect out.bits, in.bits"), direct)
      assert(!direct.contains("mux(out.valid, in.bits,"))
    }
  }

  test("consumer capture structure must qualify receipt bits with valid and ready") {
    // A scoped structural check of these emitted consumer fixtures, not a claim
    // of a whole-design valid-fanout checker. Removing valid leaves a register
    // that samples the live native bus on idle cycles and must be rejected.
    def check(text: String): Unit = {
      val consumer = text.substring(text.indexOf("module ReceiptConsumer :"))
      val predicate = "node ([A-Za-z0-9_]+) = and\\(receipt.out.ready, receipt.out.valid\\)".r
        .findFirstMatchIn(consumer).map(_.group(1))
        .getOrElse(throw new IllegalArgumentException("RECEIPT_UNQUALIFIED_CAPTURE"))
      val qualifiedLoad = ("(?s)when " + predicate + " :[^\\n]*\\n\\s+connect captured, receipt.out.bits").r
      require(qualifiedLoad.findFirstIn(consumer).nonEmpty, "RECEIPT_UNQUALIFIED_CAPTURE")
    }
    check(ChiselStage.emitCHIRRTL(new ReceiptConsumer(true)))
    val error = intercept[IllegalArgumentException] { check(ChiselStage.emitCHIRRTL(new ReceiptConsumer(false))) }
    assert(error.getMessage == "RECEIPT_UNQUALIFIED_CAPTURE")
  }
}
