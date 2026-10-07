import chisel3._
import chiselasync.bundled._
import chiselasync.metadata.{ClickTiming,DelayBounds,ModelTime}
import chiselasync.testing.AsyncTest
import chiselasync.testing.AsyncTest.{Input,Output,Options,PinDelay}
import java.nio.file.{Files,Paths}
import org.scalatest.funsuite.AnyFunSuite

class ClickTestSpec extends AnyFunSuite {
  private val timing=ClickTiming.Simulation
  private def fresh(name:String)={ val root=Paths.get("build/click-tests"); Files.createDirectories(root); Files.createTempDirectory(root,name) }
  private val words=(Seq(0,255,0,255,0,0,255,255) ++ (0 until 40).map(i=>(i*73+19)&255)).map(BigInt(_))
  private def inputs=Seq(Input.literals("in",words.map(_.U(8.W))))
  private def outputs=Seq(Output.literals("out",words.map(_.U(8.W))))
  test("standard Click pipeline preserves tokens under 300 independent delay configurations") {
    val results=AsyncTest.check(new ClickFifo(UInt(8.W),3,timing),inputs,outputs,1L to 300L,fresh("standard"))
    assert(results.size==300 && results.forall(_.variedCells>0))
  }
  test("phase-decoupled Click pipeline preserves tokens under 300 independent delay configurations") {
    val results=AsyncTest.check(new PhaseDecoupledClickFifo(UInt(8.W),3,timing),inputs,outputs,1L to 300L,fresh("decoupled"))
    assert(results.size==300 && results.forall(_.variedCells>0))
  }
  test("Click input transform changes type and randomized register clock skew is checked") {
    AsyncTest.check(new ClickStage(UInt(8.W),UInt(9.W),(x:UInt)=>x +& 1.U(8.W),timing),inputs,
      Seq(Output.literals("out",words.map(x=>(x+1).U(9.W)))),1L to 24L,fresh("transform"),
      Options(Seq(PinDelay("payload","trigger",DelayBounds(ModelTime(0),ModelTime.ps(100),ModelTime(0))))))
    val error=intercept[IllegalArgumentException] {
      AsyncTest.check(new ClickBuffer(UInt(8.W),timing),inputs,outputs,Seq(1),fresh("skew-fault"),
        Options(Seq(PinDelay("payload","trigger",DelayBounds.fixed(ModelTime.ps(200))))))
    }
    assert(error.getMessage.contains("CLICK_CLOCK_SKEW"),error.getMessage)
  }

  private def fails(code:String)(body: => Any):Unit={
    val error=intercept[IllegalArgumentException](body)
    val diagnostics="(?m)^FATAL: .*?: ([A-Z_]+)".r.findAllMatchIn(error.getMessage).map(_.group(1)).toSeq
    assert(diagnostics==Seq(code),error.getMessage)
  }
  test("Click setup and hold monitors reject separately delayed payload arrivals") {
    Seq(2950L->"CLICK_SETUP",3050L->"CLICK_HOLD").foreach { case(delay,code)=>
      fails(code) {
        AsyncTest.run(new ClickBuffer(UInt(8.W),timing),Seq(1),fresh(code),
          options=Options(Seq(PinDelay("payload","d",DelayBounds.fixed(ModelTime.ps(delay))))))(_=>
          "in_bits=5; #1; in_req=1; #1000000000;")
      }
    }
  }
  test("Click pulse monitors detect truncated high and low pulses") {
    Seq("force dut.ca_primitive_fire.q=1; #50000; force dut.ca_primitive_fire.q=0; #10;" -> "CLICK_PULSE_HIGH",
      "force dut.ca_primitive_fire.q=1; #1000000; force dut.ca_primitive_fire.q=0; #50000; force dut.ca_primitive_fire.q=1; #10;" -> "CLICK_PULSE_LOW").foreach { case(body,code)=>
      fails(code) { AsyncTest.run(new ClickBuffer(UInt(8.W),timing),Seq(1),fresh(code))(_=>body) }
    }
  }
  test("both native Click variants hold a stalled token and abort it on reset") {
    Seq(false,true).foreach { pd=>
      AsyncTest.run(if(pd) new PhaseDecoupledClickBuffer(UInt(8.W),timing) else new ClickBuffer(UInt(8.W),timing),
        Seq(1,2,19,81),fresh("reset")) { _=> """
in_bits=3; #100000000; in_req=1; wait(in_ack); wait(out_req);
#1000000000; if(out_bits !== 8'd3 || !out_req) $fatal(1,"STALL_CHANGED");
reset=1; #10; in_req=0; in_bits=0; out_ack=0;
#1000000000; reset=0; #1000000000;
fork
 begin in_bits=7; #100000000; in_req=1; wait(in_ack); end
 begin wait(out_req); #100000000; if(out_bits !== 8'd7) $fatal(1,"RESET_PAYLOAD"); out_ack=1; end
join
#1000000000; if(delivered_out != 1) $fatal(1,"RESET_DELIVERY_COUNT");
""" }
    }
  }
  test("phase-decoupled initial token waits for start and precedes new input") {
    AsyncTest.run(new PhaseDecoupledClickBuffer(UInt(8.W),timing,Some(42.U(8.W))),1L to 32L,fresh("seeded")) { _=> """
if(out_req !== 0 || in_ack !== 0) $fatal(1,"START_BARRIER");
in_bits=9; #100000000; in_req=1; #1000000000;
if(in_ack !== 0 || out_req !== 0) $fatal(1,"INITIAL_OVERWRITTEN");
start=1; wait(out_req); #100000000;
if(out_bits !== 8'd42) $fatal(1,"INITIAL_VALUE"); out_ack=1;
wait(!out_req); #100000000;
if(out_bits !== 8'd9) $fatal(1,"INITIAL_ORDER"); out_ack=0; wait(in_ack);
#1000000000; if(delivered_out != 2) $fatal(1,"INITIAL_COUNT");
""" }
    fails("CLICK_START_WITHDRAWN") {
      AsyncTest.run(new PhaseDecoupledClickBuffer(UInt(8.W),timing,Some(42.U(8.W))),Seq(1),fresh("bad-start"))(_=>
        "start=1; #100000000; start=0; #100;")
    }
  }
}
