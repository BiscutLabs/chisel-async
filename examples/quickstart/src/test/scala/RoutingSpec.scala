import chisel3._
import chiselasync.bundled._
import chiselasync.metadata.{BundledTiming, ModelTime, PhaseTiming}
import chiselasync.core.AsyncModule
import chiselasync.interop.{FourPhaseToTwoPhase, TwoPhaseToFourPhase}
import chiselasync.protocol.{Channel, FourPhase, TwoPhase}
import chiselasync.testing.AsyncTest
import chiselasync.testing.AsyncTest.{Input, Output}
import java.nio.file.Paths
import org.scalatest.funsuite.AnyFunSuite

// Four-phase test boundaries around the actual new two-phase mux and RegFork.
class PhaseRoutingHarness extends AsyncModule {
  private val t = BundledTiming.Simulation
  private val p = PhaseTiming(t.controls.a,ModelTime.ps(40000))
  private val c = ModelTime.ps(1000)
  val a = fourPhaseInput("a",UInt(8.W))
  val b = fourPhaseInput("b",UInt(8.W))
  val select = fourPhaseInput("select",UInt(1.W))
  val left = fourPhaseOutput("left",UInt(9.W))
  val right = fourPhaseOutput("right",UInt(8.W))
  private val mux = asyncChild("mux")(d => new TwoPhaseMux(UInt(8.W),2,t,p,c,d))
  private val fork = asyncChild("fork")(d => new TwoPhaseRegFork(UInt(8.W),UInt(9.W),UInt(8.W),
    (v: UInt) => (v +& 1.U(8.W),v ^ 0xa5.U(8.W)),t,p,c,d))
  Seq(("a",a,mux.in(0)),("b",b,mux.in(1)),("select",select,mux.select)).foreach {
    case (id,from,to) =>
      val bridge = asyncChild(s"${id}_bridge")(d => new FourPhaseToTwoPhase(UInt(from.bits.getWidth.W),t,p,d))
      FourPhase.connect(bridge.in,from); TwoPhase.connect(to,bridge.out)
  }
  TwoPhase.connect(fork.in,mux.out)
  Seq(("left_bridge",fork.left,left),("right_bridge",fork.right,right)).foreach { case(id,from,to) =>
    val bridge = asyncChild(id)(d => new TwoPhaseToFourPhase(UInt(from.bits.getWidth.W),t,p,d))
    TwoPhase.connect(bridge.in,from); FourPhase.connect(to,bridge.out)
  }
}

class RoutingSpec extends AnyFunSuite {
  private val timing = BundledTiming.Simulation
  private val cell = ModelTime.ps(1000)
  private val seeds = (1L to 300L)

  test("controlled mux consumes only the chosen stream across 300 cell configurations") {
    val choices = Seq(0,0,2,1,2,2,1,0) ++ (0 until 40).map(i => (i*7 + i/3) % 3)
    val cursors = Array.fill(3)(0)
    def value(lane: Int, index: Int): BigInt = BigInt((lane*83 + index/2) % 256)
    val expected = choices.map { lane => val v = value(lane,cursors(lane)); cursors(lane) += 1; Map("out_bits" -> v) }
    val sources = (0 until 3).map(lane => Input(s"in_$lane", (0 until cursors(lane)).map(i => Map(s"in_${lane}_bits" -> value(lane,i)))))
    val results = AsyncTest.check(new FourPhaseMux(UInt(8.W),3,timing,cell),
      sources :+ Input("select",choices.map(i => Map("select_bits" -> BigInt(i)))),
      Seq(Output("out",expected)), seeds, Paths.get("build/routing-mux"))
    assert(results.size == 300 && results.forall(_.variedCells > 0))
  }

  test("registered fork preserves heterogeneous results across 300 cell configurations") {
    val words = Seq(0,255,128,128,0,0) ++ (0 until 32).map(i => i*73 % 256)
    val results = AsyncTest.check(new FourPhaseRegFork(UInt(8.W),UInt(9.W),SInt(9.W),
      (v: UInt) => (v +& 1.U(8.W), v.zext - 128.S(9.W)),timing,cell),
      Seq(Input("in",words.map(v => Map("in_bits" -> BigInt(v))))),
      Seq(Output("left",words.map(v => Map("left_bits" -> BigInt(v+1)))),
          Output("right",words.map(v => Map("right_bits" -> BigInt((v-128)&511))))),
      seeds, Paths.get("build/routing-regfork"))
    assert(results.size == 300 && results.forall(_.variedCells > 0))
  }

  test("mux ignores unselected offers and resets an outstanding selection") {
    AsyncTest.run(new FourPhaseMux(UInt(8.W),3,timing,cell),Seq(1,2,43),Paths.get("build/routing-reset")) { _ =>
      """
in_0_bits=31; in_1_bits=79; in_2_bits=113;
in_0_req=1; in_2_req=1;
select_bits=1; select_req=1;
wait(select_ack); #1000000; select_req=0; wait(!select_ack);
#1000000000;
if(in_0_ack || in_2_ack || out_req) $fatal(1,"UNSELECTED_CONSUMED");
in_1_req=1; wait(in_1_ack); #1000000; in_1_req=0; wait(!in_1_ack);
wait(out_req); #1000000000;
if(in_0_ack || in_2_ack || out_bits !== 8'd79) $fatal(1,"UNSELECTED_CONSUMED");
reset=1; #1000000000; in_0_req=0; in_2_req=0; reset=0; #1000000000;
if(out_req || in_0_ack || in_1_ack || in_2_ack) $fatal(1,"RESET_IDLE");
in_2_bits=27; in_2_req=1; select_bits=2; select_req=1;
fork
  begin wait(select_ack); #1000000; select_req=0; wait(!select_ack); end
  begin wait(in_2_ack); #1000000; in_2_req=0; wait(!in_2_ack); end
  begin wait(out_req); #1000000; if(out_bits !== 8'd27) $fatal(1,"RESET_PAYLOAD");
    out_ack=1; wait(!out_req); #1000000; out_ack=0; end
join
#1000000000;
if(out_req) $fatal(1,"DUPLICATE_AFTER_RESET");
"""
    }
  }

  test("async helper rejects a wrong payload and an invalid selector") {
    val wrong = intercept[IllegalArgumentException] {
      AsyncTest.check(new LongHoldBuffer(UInt(8.W),timing),
        Seq(Input("in",Seq(Map("in_bits" -> BigInt(7))))),
        Seq(Output("out",Seq(Map("out_bits" -> BigInt(8))))),Seq(43),Paths.get("build/fault-payload"))
    }
    assert(wrong.getMessage.contains("PAYLOAD_MISMATCH"))
    val invalid = intercept[IllegalArgumentException] {
      AsyncTest.run(new FourPhaseMux(UInt(8.W),3,timing,cell),Seq(43),Paths.get("build/fault-selector")) { _ =>
        "select_bits=3; select_req=1; #1000000000;"
      }
    }
    assert(invalid.getMessage.contains("SELECT_INDEX_OUT_OF_RANGE"))
    val empty = intercept[IllegalArgumentException] {
      AsyncTest.run(new LongHoldBuffer(UInt(8.W),timing),Seq(43),Paths.get("build/fault-empty"))(_ => "#1000000;")
    }
    assert(empty.getMessage.contains("ASYNC_NO_ACTIVITY"))
  }

  test("two-phase mux and registered fork preserve tokens across explicit conversion") {
    val order = Seq(0,1,1,0,1,0,0,1)
    val expected = Seq(3,21,22,4,23,5,6,24)
    AsyncTest.check(new PhaseRoutingHarness,
      Seq(Input("a",(3 to 6).map(v => Map("a_bits" -> BigInt(v)))),
          Input("b",(21 to 24).map(v => Map("b_bits" -> BigInt(v)))),
          Input("select",order.map(v => Map("select_bits" -> BigInt(v))))),
      Seq(Output("left",expected.map(v => Map("left_bits" -> BigInt(v+1)))),
          Output("right",expected.map(v => Map("right_bits" -> BigInt(v^0xa5))))),
      (1L to 16L),Paths.get("build/routing-phase"))
  }
}
