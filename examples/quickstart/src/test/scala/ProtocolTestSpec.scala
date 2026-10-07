import chisel3._
import chisel3.experimental.BundleLiterals._
import chiselasync.bundled.{FourPhaseStage, LongHoldBuffer, TwoPhaseBuffer}
import chiselasync.interop.FourPhaseToTwoPhase
import chiselasync.metadata.{BundledTiming, DelayBounds, ModelTime, PhaseTiming, QdiTiming}
import chiselasync.qdi.{DualRailFunction, DualRailStrongBuffer}
import chiselasync.testing.{AsyncTest, Simulator}
import chiselasync.testing.AsyncTest.{Input, Output, Options, PinDelay}
import java.nio.file.{Files, Path, Paths}
import org.scalatest.funsuite.AnyFunSuite

class ProtocolTestSpec extends AnyFunSuite {
  private val timing = BundledTiming.Simulation
  private val phase = PhaseTiming(timing.controls.a, ModelTime.ps(40000))
  private val qdi = QdiTiming(timing.controls.a)
  private def fresh(name: String): Path = {
    val root = Paths.get("build/public-testkit"); Files.createDirectories(root)
    Files.createTempDirectory(root, name + "-")
  }
  private val words = Seq(0, 0, 15, 15, 5, 10, 1, 14).map(BigInt(_))
  private def failure(code: String)(run: => Any): Unit = {
    val error = intercept[IllegalArgumentException](run)
    assert(error.getMessage.contains(code), error.getMessage)
    if (error.getMessage.contains("SIMULATOR_FAILED")) {
      val diagnostics = "(?m)^FATAL: .*?: ([A-Z_]+)".r.findAllMatchIn(error.getMessage).map(_.group(1)).toSeq
      assert(diagnostics == Seq(code), error.getMessage)
    }
  }

  test("typed Bundle literals run against the published adder") {
    val pairs = Seq((0,0), (255,255), (19,7), (19,7))
    val values = pairs.map { case (a,b) => (new Operands).Lit(_.a -> a.U(8.W), _.b -> b.U(8.W)) }
    val results = AsyncTest.check(new AddPipeline, Seq(Input.literals("in", values)),
      Seq(Output.literals("out", pairs.map { case(a,b) => (a+b).U(9.W) })), 1L to 12L, fresh("typed"))
    assert(results.size == 12 && results.forall(_.variedCells > 0))
  }

  test("native two-phase tests count both acknowledgement edges") {
    val results = AsyncTest.check(new TwoPhaseBuffer(UInt(4.W),timing,phase),
      Seq(Input.literals("in", words.map(_.U(4.W)))), Seq(Output.literals("out", words.map(_.U(4.W)))),
      1L to 32L, fresh("two-phase"))
    assert(results.size == 32)
  }

  test("native dual-rail function handles partial waves and repeated words") {
    val table = (0 until 16).map(n => BigInt(Integer.bitCount(n)))
    val results = AsyncTest.check(new DualRailFunction(UInt(4.W),UInt(3.W),table,qdi),
      Seq(Input.literals("in", words.map(_.U(4.W)))),
      Seq(Output.literals("out", words.map(w => w.bitCount.U(3.W)))), 1L to 32L, fresh("dual-rail"))
    assert(results.size == 32)
  }

  test("signed literals preserve bit patterns and reject width mismatches") {
    val values = Seq(-16,-1,-1,0,15)
    AsyncTest.check(new LongHoldBuffer(SInt(5.W),timing),
      Seq(Input.literals("in",values.map(_.S(5.W)))), Seq(Output.literals("out",values.map(_.S(5.W)))),
      Seq(1,2,17), fresh("signed"))
    failure("TEST_LITERAL_PORT_TYPE_MISMATCH") {
      AsyncTest.check(new LongHoldBuffer(UInt(4.W),timing), Seq(Input.literals("in",Seq(1.U(3.W)))),
        Seq(Output.literals("out",Seq(1.U(4.W)))), Seq(1), fresh("wrong-width"))
    }
  }

  test("wire skew is selected independently and unsafe long-hold skew fails") {
    def run(delay: DelayBounds) = AsyncTest.check(new LongHoldBuffer(UInt(4.W),timing),
      Seq(Input.literals("in",words.map(_.U(4.W)))), Seq(Output.literals("out",words.map(_.U(4.W)))),
      Seq(1,2,41), fresh("fork"), Options(Seq(PinDelay("long_hold","b",delay))))
    run(DelayBounds(ModelTime(0),ModelTime.ps(100),ModelTime(0)))
    failure("TIMING_LONG_HOLD_FORK") { run(DelayBounds.fixed(ModelTime.ps(20000))) }
  }

  test("history aperture is exercised independently of latch propagation") {
    def run(ps: Long) = AsyncTest.check(new FourPhaseToTwoPhase(UInt(4.W),timing,phase),
      Seq(Input.literals("in",words.map(_.U(4.W)))), Seq(Output.literals("out",words.map(_.U(4.W)))),
      Seq(1,2,43), fresh("closure"),
      Options(Seq(PinDelay.closingAperture("adapter.history",DelayBounds.fixed(ModelTime.ps(ps))))))
    run(100)
    failure("TIMING_HISTORY_CLOSURE") { run(100000) }
  }

  test("pin delay targeting fails on an unknown cell or an output pin") {
    Seq(PinDelay("missing","a",timing.controls.a) -> "UNKNOWN_DELAY_CELL",
      PinDelay("long_hold","q",timing.controls.a) -> "PIN_DELAY_REQUIRES_INPUT").foreach { case(p,code) =>
      failure(code) { AsyncTest.run(new LongHoldBuffer(UInt(4.W),timing),Seq(1),fresh("bad-target"),options=Options(Seq(p)))(_ => "") }
    }
  }

  test("dual-rail observers reject illegal codes and premature return") {
    Seq("in_one=3; in_zero=1; #10;" -> "ILLEGAL_DUAL_RAIL",
      "in_one=1; #10; in_one=0; #10;" -> "DUAL_RAIL_EARLY_WITHDRAW").foreach { case(body,code) =>
      failure(code) { AsyncTest.run(new DualRailStrongBuffer(UInt(2.W),qdi),Seq(1),fresh("bad-rail"))(_ => body) }
    }
  }

  test("two-phase observers reject a second request before acknowledgement") {
    failure("HANDSHAKE_ORDER") {
      AsyncTest.run(new TwoPhaseBuffer(UInt(4.W),timing,phase),Seq(1),fresh("bad-two"))(_ =>
        "in_bits=3; #10; in_req=1; #10; in_req=0; #10;")
    }
  }

  test("dual-rail reset aborts a partial word and permits a fresh delivery") {
    AsyncTest.run(new DualRailStrongBuffer(UInt(2.W),qdi),Seq(1,2,37),fresh("dual-reset")) { _ => """
in_one=1; #100000000; reset=1; #10; in_one=0; in_zero=0; out_ack=0;
#1000000000; reset=0; #1000000000;
fork
  begin in_zero=2; #100000000; in_one=1; wait(in_ack); #100000000;
    in_one=0; #100000000; in_zero=0; wait(!in_ack); end
  begin wait ((out_zero ^ out_one) == 3); #100000000;
    if (out_one !== 2'd1) $fatal(1,"PAYLOAD_MISMATCH"); out_ack=1;
    wait ((out_zero | out_one)==0); #100000000; out_ack=0; end
join
#100000000; if (delivered_out != 1) $fatal(1,"RESET_DELIVERY_COUNT");
""" }
  }

  test("two-phase reset restores parity and permits a fresh delivery") {
    AsyncTest.run(new TwoPhaseBuffer(UInt(4.W),timing,phase),Seq(1,2,37),fresh("two-reset")) { _ => """
in_bits=3; #10; in_req=1; #100000000; reset=1; #10; in_req=0; out_ack=0;
#1000000000; reset=0; #1000000000;
fork
  begin in_bits=7; #100000000; in_req=1; wait(in_ack); end
  begin wait(out_req); #100000000; if (out_bits !== 4'd7) $fatal(1,"PAYLOAD_MISMATCH"); out_ack=1; end
join
#1000000000; if (delivered_out != 1) $fatal(1,"RESET_DELIVERY_COUNT");
""" }
  }

  test("simulator discovery explains a missing executable") {
    val error = intercept[IllegalStateException] { Simulator("chisel-async-nonexistent-iverilog").check(fresh("missing-simulator")) }
    assert(error.getMessage.contains("SIMULATOR_NOT_FOUND") && error.getMessage.contains("CA_IVERILOG"))
  }
}
