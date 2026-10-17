// SPDX-License-Identifier: Apache-2.0
package chiselasync

import chisel3._
import chiselasync.bundled._
import chiselasync.core.AsyncModule
import chiselasync.metadata._
import chiselasync.primitives.PassiveDataAllowance
import circt.stage.ChiselStage
import java.nio.file.{Files, Paths}
import org.scalatest.funsuite.AnyFunSuite

class PassiveAllowancePayload extends Bundle {
  val tag = UInt(3.W)
  val signed = Vec(2, SInt(9.W))
  val flag = Bool()
}
class TypedPassiveAllowance extends AsyncModule {
  val in = IO(Input(new PassiveAllowancePayload))
  val out = IO(Output(new PassiveAllowancePayload))
  private val resetRef = contract.endpoint("reset", reset)
  contract.endpoint("in_tag", in.tag); contract.endpoint("out_tag", out.tag)
  contract.endpoint("in_signed0", in.signed(0)); contract.endpoint("out_signed0", out.signed(0))
  contract.endpoint("in_signed1", in.signed(1)); contract.endpoint("out_signed1", out.signed(1))
  contract.endpoint("in_flag", in.flag); contract.endpoint("out_flag", out.flag)
  out := PassiveDataAllowance(this, "data", in, ModelTime.ps(10000), resetRef)
}
class PassiveAllowanceSpec extends AnyFunSuite {
  private val bd = BundledTiming.Simulation.copy(dataAllowance = DataAllowance.Passive)
  private val click = ClickTiming.Simulation.copy(dataAllowance = DataAllowance.Passive)
  private val root = Paths.get("build/passive-allowance-exports")
  private def stages(c: Boolean, passive: Boolean): AsyncModule =
    if(c) new ClickStage(UInt(8.W), UInt(8.W), (x: UInt) => x ^ 0xa5.U(8.W),
      if(passive) click else ClickTiming.Simulation)
    else new FourPhaseStage(UInt(8.W), UInt(8.W), (x: UInt) => x ^ 0xa5.U(8.W),
      if(passive) bd else BundledTiming.Simulation)
  private def walk(n: ujson.Value): Seq[ujson.Value] = Seq(n) ++ n("children").arr.flatMap(c => walk(c("contract")))
  test("passive allowance preserves structured signed payloads and has only a/q primitive pins") {
    val rtl = ChiselStage.emitCHIRRTL(new TypedPassiveAllowance)
    assert(rtl.contains("signed : SInt<9>[2]") && rtl.contains("tag : UInt<3>"))
    assert(!rtl.contains("input clock") && !rtl.contains("regreset "))
    ExportDesign.emit(new TypedPassiveAllowance, root.resolve("typed"))
    val node = ujson.read(Files.readString(root.resolve("typed/contract.json")))("manifest")("design")
    val cell = node("primitives")(0)
    assert(cell("parameters")("WIDTH").str == "22")
    assert(cell("ports").arr.map(_("name").str).toSet == Set("a", "q"))
    assert(cell("model").str == "ChiselAsyncPassiveDataAllowance_v1")
    intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new RawModule { val bad = Module(new PassiveDataAllowance(0, ModelTime(0))) }) }
  }
  test("default stages retain old cells while opt-in changes only payload allowance") {
    for(c <- Seq(false,true); passive <- Seq(false,true)) {
      val dir=root.resolve(s"${if(c) "click" else "bd"}-${if(passive) "passive" else "default"}")
      ExportDesign.emit(stages(c,passive),dir)
      val node=ujson.read(Files.readString(dir.resolve("contract.json")))("manifest")("design")
      val cell=node("primitives").arr.find(_("id").str=="data_delay").get
      assert(cell("model").str == (if(passive) "ChiselAsyncPassiveDataAllowance_v1" else "ChiselAsyncControlGate_v1"))
      assert(node("primitives").arr.count(_("model").str=="ChiselAsyncPassiveDataAllowance_v1") == (if(passive) 1 else 0))
      assert(node("capacity").num==1)
    }
  }
  test("FIFO and seeded token paths inherit passive policy without changing reset seeds") {
    val bdDir=root.resolve("bd-seeded")
    ExportDesign.emit(new FourPhaseFifo(UInt(8.W),2,bd,Seq(9.U(8.W)),ModelTime.ps(1000)),bdDir)
    val bdNodes=walk(ujson.read(Files.readString(bdDir.resolve("contract.json")))("manifest")("design"))
    assert(bdNodes.flatMap(_("primitives").arr).count(_("model").str=="ChiselAsyncPassiveDataAllowance_v1")==3)
    val clickDir=root.resolve("click-seeded")
    ExportDesign.emit(new PhaseDecoupledClickBuffer(UInt(8.W),click,Some(9.U(8.W))),clickDir)
    val clickNode=ujson.read(Files.readString(clickDir.resolve("contract.json")))("manifest")("design")
    assert(clickNode("primitives").arr.find(_("id").str=="payload").get("parameters")("RESET_VALUE").str=="9")
  }
  test("ASIC mapping emits an unmasked alias without technology bindings for allowance") {
    val plan=AsicMapping.prepare(new TypedPassiveAllowance,Files.createTempDirectory(Paths.get("build"),"passive-allowance-mapping-"))
    assert(plan.required.isEmpty)
    val dummy=Paths.get("build/passive-allowance-empty-technology.sv")
    Files.writeString(dummy,"module UnusedTechnologyMarker(); endmodule\n")
    val output=plan.emit(Seq.empty,Seq(dummy))
    val mapped=Files.readString(output.resolve("ChiselAsyncPassiveDataAllowance_v1.sv"))
    assert(mapped.contains("assign q = a;") && !mapped.contains("assign #"))
    assert(!mapped.contains("input wire reset") && !mapped.contains("dont_touch"))
  }
}
