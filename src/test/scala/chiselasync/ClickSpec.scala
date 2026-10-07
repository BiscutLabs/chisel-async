// SPDX-License-Identifier: Apache-2.0
package chiselasync

import chisel3._
import chiselasync.bundled._
import chiselasync.metadata._
import circt.stage.ChiselStage
import java.nio.file.{Files,Paths}
import org.scalatest.funsuite.AnyFunSuite

class ClickSpec extends AnyFunSuite {
  private val timing=ClickTiming.Simulation
  test("native Click uses edge registers and one or two phase registers without adapters") {
    def inspect(decoupled: Boolean): String=ChiselStage.emitCHIRRTL(
      if(decoupled) new PhaseDecoupledClickBuffer(UInt(8.W),timing) else new ClickBuffer(UInt(8.W),timing))
    Seq(false,true).foreach { decoupled =>
      val rtl=inspect(decoupled)
      assert(rtl.contains("ChiselAsyncEventRegister_v1"))
      assert(rtl.contains("ca_primitive_output_phase") == decoupled)
      Seq("ChiselAsyncClosingLatch", "ChiselAsyncAsymmetricC", "ToFourPhase", "ToTwoPhase", "input clock").foreach(s=>assert(!rtl.contains(s)))
    }
  }
  test("Click transforms retain exact types and seeded payloads are output-typed literals") {
    val rtl=ChiselStage.emitCHIRRTL(new PhaseDecoupledClickStage(UInt(8.W),UInt(9.W),
      (x:UInt)=>x +& 1.U(8.W),timing,Some(511.U(9.W))))
    assert(rtl.contains("RESET_VALUE = 511")); assert(rtl.contains("input start"))
    assert(ChiselStage.emitCHIRRTL(new PhaseDecoupledClickBuffer(SInt(8.W),timing,Some((-3).S(8.W))))
      .contains("RESET_VALUE = 253"))
    intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new ClickStage(UInt(8.W),UInt(9.W),(x:UInt)=>x,timing)) }
    intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new PhaseDecoupledClickBuffer(UInt(8.W),timing,Some(UInt(8.W)))) }
    intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new ClickFifo(UInt(8.W),0,timing)) }
  }
  test("Click policy rejects equality at data, pulse, acknowledgement and output limits") {
    intercept[IllegalArgumentException] { timing.copy(requestDelay=timing.data.max+timing.setup) }
    intercept[IllegalArgumentException] { timing.copy(pulseHigh=ModelTime.ps(2900)) }
    intercept[IllegalArgumentException] { timing.copy(acknowledgeDelay=ModelTime.ps(30200)) }
    intercept[IllegalArgumentException] { timing.copy(outputDelay=ModelTime.ps(30200)) }
    intercept[IllegalArgumentException] { timing.copy(controls=timing.controls.copy(fire=DelayBounds.fixed(ModelTime(0)))) }
    // Fast shared phase + fast output comparator must not be hidden by pairing
    // each comparator with a different phase register's minimum.
    val slow=DelayBounds.fixed(ModelTime.ps(10000))
    val fast=DelayBounds.fixed(ModelTime.ps(1000))
    val asymmetric=timing.controls.copy(inputPhase=fast,outputPhase=slow,inputCompare=slow,outputCompare=fast)
    val error=intercept[IllegalArgumentException] {
      timing.copy(controls=asymmetric,pulseHigh=ModelTime.ps(3000))
    }
    assert(error.getMessage.contains("CLICK_HIGH_PULSE_BOUND"))
  }
  test("optimized Click exports retain independent controller and aperture obligations") {
    val root=Paths.get("build/click-exports"); Files.createDirectories(root)
    Seq("standard","decoupled","seeded").foreach { variant =>
      val dir=root.resolve(variant)
      ExportDesign.emit(if(variant=="standard") new ClickBuffer(UInt(8.W),timing)
        else new PhaseDecoupledClickBuffer(UInt(8.W),timing,if(variant=="seeded") Some(42.U(8.W)) else None),dir)
      val node=ujson.read(Files.readString(dir.resolve("contract.json")))("manifest")("design")
      val t=node("timing")(0)
      assert(t("kind").str=="click-bundling-v1")
      assert(t("cells").obj.size==7 && t("times")("PULSE_HIGH_FS").str=="100000")
      val error=intercept[IllegalArgumentException] { TimingConstraints.prepare(dir.resolve("contract.json")) }
      assert(error.getMessage.contains("CLICK_REQUIRES_PULSE_AND_APERTURE_ANALYSIS"))
    }
    val mapping=AsicMapping.prepare(new PhaseDecoupledClickBuffer(UInt(8.W),timing,Some(42.U(8.W))),
      root.resolve("asic-inventory"))
    val phases=mapping.required.filter(_.key.model=="ChiselAsyncPhaseRegister_v1")
    assert(phases.map(_.key.parameters("RESET_VALUE")).toSet==Set(BigInt(0),BigInt(1)))
    assert(phases.forall(_.ports.map(_.name).toSet==Set("reset","trigger","q")))
    val payload=mapping.required.filter(_.key.model=="ChiselAsyncEventRegister_v1")
    assert(payload.size==1 && payload.head.key.parameters("RESET_VALUE")==42)
    assert(payload.head.ports.map(_.name).toSet==Set("reset","trigger","d","q"))
    assert(!mapping.required.exists(_.key.model=="ChiselAsyncClickMarker_v1"))
  }
}
