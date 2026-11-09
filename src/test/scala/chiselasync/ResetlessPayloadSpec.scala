// SPDX-License-Identifier: Apache-2.0
package chiselasync

import chisel3._
import chiselasync.bundled.{FourPhaseStage, LongHoldBuffer, PayloadStorage}
import chiselasync.core.AsyncModule
import chiselasync.metadata._
import chiselasync.primitives.ResetlessClosingLatch
import chiselasync.testing.{AsyncTest, Simulator}
import java.nio.file.{Files, Path, Paths}
import java.util.concurrent.TimeUnit
import org.scalatest.funsuite.AnyFunSuite

class ResetlessPayloadSpec extends AnyFunSuite {
  private val timing = BundledTiming.Simulation.copy(dataAllowance = DataAllowance.Passive)
  private def fresh(label: String): Path = {
    val root = Paths.get("build/resetless-payload"); Files.createDirectories(root)
    Files.createTempDirectory(root, label + "-").toAbsolutePath
  }
  private def stage(resetless: Boolean) = new FourPhaseStage(UInt(8.W), UInt(8.W),
    (v: UInt) => v ^ 0xa5.U(8.W), timing,
    payloadStorage = if(resetless) PayloadStorage.Resetless else PayloadStorage.Resettable)

  test("resetless latch starts unknown, tracks only while open and treats uncertain closure conservatively") {
    val stream = getClass.getResourceAsStream("/chiselasync/sv/ChiselAsyncResetlessClosingLatch_v1.sv")
    val model = try new String(stream.readAllBytes(), java.nio.charset.StandardCharsets.UTF_8) finally stream.close()
    val bench = """module Bench;
timeunit 1ns; timeprecision 1ps;
reg closed=1; reg [7:0] d=8'h3c; wire [7:0] q;
ChiselAsyncResetlessClosingLatch_v1 #(.WIDTH(8),.DELAY_FS(1000000)) dut(closed,d,q);
initial begin #100; $fatal(1,"MODEL_DEADLINE"); end
initial begin
  #2; if(q!==8'hxx) $fatal(1,"MODEL_INITIALIZED_PAYLOAD");
  closed=0; d=8'h5a; #2; if(q!==8'h5a) $fatal(1,"MODEL_TRACK");
  closed=1; d=8'hff; #2; if(q!==8'h5a) $fatal(1,"MODEL_HOLD");
  d=8'h5a; closed=1'bx; #2; if(q!==8'h5a) $fatal(1,"MODEL_EQUAL_UNKNOWN_ENABLE");
  d=8'ha5; #2; if(q!==8'hxx) $fatal(1,"MODEL_UNKNOWN_ENABLE");
  closed=0; #2; if(q!==8'ha5) $fatal(1,"MODEL_RECOVER");
  closed=1; d=8'hzz; #2; if(q!==8'ha5) $fatal(1,"MODEL_HOLD_Z");
  closed=0; #2; if(q!==8'hzz) $fatal(1,"MODEL_TRACK_Z");
  $display("RESETLESS_MODEL_PASS"); $finish;
end
endmodule
"""
    def run(text: String, label: String): (Int, String) = {
      val dir = fresh(label); Files.writeString(dir.resolve("model.sv"), text)
      Files.writeString(dir.resolve("bench.sv"), bench)
      val simulator = Simulator()
      def command(args: Seq[String], name: String): Int = {
        val p = new ProcessBuilder(args: _*).directory(dir.toFile).redirectErrorStream(true)
          .redirectOutput(dir.resolve(name).toFile).start()
        if(!p.waitFor(90, TimeUnit.SECONDS)) { p.destroyForcibly(); fail("simulation timeout: " + dir) }
        p.exitValue()
      }
      assert(command(Seq(simulator.iverilog,"-g2012","-s","Bench","-o","test.vvp","model.sv","bench.sv"),"compile.log")==0)
      val code = command(Seq(simulator.vvp,"test.vvp"),"run.log")
      code -> Files.readString(dir.resolve("run.log"))
    }
    val good = run(model,"model"); assert(good._1==0 && good._2.contains("RESETLESS_MODEL_PASS"),good._2)
    val bad = run(model.replace("closed === 1'b0", "closed === 1'b0 || d === 8'hff"),"hold-fault")
    assert(bad._1!=0 && bad._2.contains("MODEL_HOLD"),bad._2)
  }

  test("default and opt-in preserve the same typed transfer stream under randomized stalls and cell delays") {
    val values = (0 until 96).map(i => BigInt((i*73+19)&255))
    for(resetless <- Seq(false,true)) {
      AsyncTest.check(stage(resetless), Seq(AsyncTest.Input("in",values.map(v=>Map("in_bits"->v)))),
        Seq(AsyncTest.Output("out",values.map(v=>Map("out_bits"->(v ^ 0xa5))))),
        seeds=Seq(1,2,37,91), directory=fresh(if(resetless) "resetless-stream" else "default-stream"),
        options=AsyncTest.Options(pinDelays=Seq(AsyncTest.PinDelay.closingAperture("payload",
          DelayBounds.fixed(ModelTime.ps(100))))))
    }
  }

  test("coordinated reset discards a stalled token and accepts fresh tokens without zeroing invalid payload") {
    for(resetless <- Seq(false,true)) {
      AsyncTest.run(new LongHoldBuffer(UInt(8.W),timing,
        payloadStorage=if(resetless) PayloadStorage.Resetless else PayloadStorage.Resettable),
        Seq(1,2,59),fresh("reset")) { _ => """
in_bits=8'hxx; #100000000;
if(in_ack!==0 || out_req!==0) $fatal(1,"INVALID_DATA_CREATED_TOKEN");
repeat(3) begin
  in_bits=8'hf1; #1000000; in_req=1;
  wait(in_ack===1); wait(out_req===1);
  #100000000; if(out_bits!==8'hf1) $fatal(1,"STALLED_PAYLOAD");
  reset=1; in_req=0; out_ack=0; in_bits=8'hxx; #1000000000;
  reset=0; #1000000000;
  if(in_ack!==0 || out_req!==0) $fatal(1,"RESET_OLD_TOKEN");
  in_bits=8'h3c; #1000000; in_req=1; wait(in_ack===1); #1000000;
  in_req=0; wait(in_ack===0); #1000000; in_bits=8'hxx; wait(out_req===1);
  #100000000; if(out_bits!==8'h3c) $fatal(1,"RESET_FRESH_TOKEN");
  out_ack=1; wait(out_req===0); #1000000; out_ack=0; #100000000;
end
""" }
    }
  }

  test("export and ASIC inventory preserve a distinct reset-free primitive with native storage audit") {
    val dir=fresh("export")
    val plan=AsicMapping.prepare(stage(true),dir)
    val payload=plan.required.filter(_.key.model=="ChiselAsyncResetlessClosingLatch_v1")
    assert(payload.size==1 && payload.head.ports.map(_.name).toSet==Set("closed","d","q"))
    assert(!plan.required.exists(_.key.model=="ChiselAsyncClosingLatch_v1"))
    val timingPlan=TimingConstraints.prepare(dir.resolve("simulation/contract.json"))
    assert(timingPlan != null)
    val failure=intercept[IllegalArgumentException] {
      ExportDesign.emit(new AsyncModule {
        val clock=IO(Input(Clock())); val data=IO(Input(UInt(8.W))); val out=IO(Output(UInt(8.W)))
        val cell=Module(new ResetlessClosingLatch(8,ModelTime.ps(1)))
        cell.closed:=clock.asBool; cell.d:=data; out:=cell.q
        contract.primitive("payload",cell,Map("WIDTH"->BigInt(8),"DELAY_FS"->BigInt(1000)),
          contract.endpoint("reset",reset),"invalid periodic enable")
      },fresh("bad-clock"))
    }
    assert(failure.getMessage.contains("STRUCTURE_CLOCK_REACHES_NATIVE_STORAGE"),failure.getMessage)
  }
}
