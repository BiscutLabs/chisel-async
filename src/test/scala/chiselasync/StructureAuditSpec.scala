// SPDX-License-Identifier: Apache-2.0
package chiselasync

import chisel3._
import chiselasync.core.AsyncModule
import chiselasync.metadata.{ExportDesign, ModelTime, StructureAudit}
import chiselasync.primitives.EventRegister
import java.nio.file.{Files, Paths}
import org.scalatest.funsuite.AnyFunSuite

class StructureAuditSpec extends AnyFunSuite {
  private def contract = ujson.Obj("primitives" -> ujson.Arr(ujson.Obj(
    "rtl_path" -> "Top.payload", "model" -> "ChiselAsyncEventRegister_v1",
    "parameters" -> ujson.Obj("WIDTH" -> "1", "DELAY_FS" -> "1000", "RESET_VALUE" -> "0"),
    "ports" -> ujson.Arr.from(Seq("reset", "trigger", "d", "q").map(n =>
      ujson.Obj("name" -> n, "direction" -> (if(n=="q") "output" else "input"), "width" -> 1))))),
    "children" -> ujson.Arr())
  private def ir(trigger: String = "%request", glue: String = "") = s"""
module {
  sv.verbatim.module @Cell<WIDTH: ui32, DELAY_FS: ui32, RESET_VALUE: ui32>(in %reset : i1, in %trigger : i1, in %d : i1, out q : i1) attributes {verilogName = "ChiselAsyncEventRegister_v1"}
  hw.module @Top(in %reset : i1, in %clock : !seq.clock, in %request : i1, in %data : i1, out result : i1) {
    $glue
    %payload.q = hw.instance "payload" @Cell<WIDTH: ui32 = 1, DELAY_FS: ui32 = 1000, RESET_VALUE: ui32 = 0>(reset: %reset: i1, trigger: $trigger: i1, d: %data: i1) -> (q: i1)
    hw.output %payload.q : i1
  }
}
"""
  private def reject(text: String, id: String, c: ujson.Value = contract): Unit = {
    val failure = intercept[IllegalArgumentException](StructureAudit.check(text, "Top", c))
    assert(failure.getMessage.contains("STRUCTURE_" + id), failure.getMessage)
  }
  test("native inventory and outputs are checked independently of their count") {
    val result = StructureAudit.check(ir(), "Top", contract)
    assert(result("primitive_paths").arr.map(_.str).toSet == Set("Top.payload"))
    reject(ir().replace("WIDTH: ui32 = 1", "WIDTH: ui32 = 2"), "PRIMITIVE_PARAMETERS")
    reject(ir().replace("hw.output %payload.q", "hw.output %absent"), "UNDRIVEN_VALUE")
    val missing = contract; missing("primitives") = ujson.Arr()
    reject(ir(), "UNREGISTERED_PRIMITIVE", missing)
  }
  test("periodic clocks cannot drive native capture through aliases and gates") {
    reject(ir("%clockBit", "%clockBit = seq.from_clock %clock"), "CLOCK_REACHES_NATIVE_STORAGE")
    reject(ir("%gated", "%clockBit = seq.from_clock %clock\n%gated = comb.and %request, %clockBit : i1"),
      "CLOCK_REACHES_NATIVE_STORAGE")
  }
  test("registered owners without primitives must exist and parameters parse completely") {
    val c = contract
    c("children") = ujson.Arr(ujson.Obj("contract" -> ujson.Obj(
      "rtl_path" -> "Top.absent", "primitives" -> ujson.Arr(), "children" -> ujson.Arr())))
    reject(ir(), "OWNER_INVENTORY", c)
    reject(ir().replace("RESET_VALUE: ui32 = 0>", "RESET_VALUE: ui32 = 0x1>"), "PARAMETER_SYNTAX")
    reject(ir().replace("RESET_VALUE: ui32 = 0>", "RESET_VALUE: ui32 = 0, RESET_VALUE: ui32 = 0>"), "DUPLICATE_PARAMETER")
  }
  test("a real sequential crossing stops combinational clock propagation") {
    val glue = "%clockBit = seq.from_clock %clock\n%received = seq.firreg %clockBit clock %clock : i1"
    assert(StructureAudit.check(ir("%received", glue), "Top", contract)("status").str == "pass")
  }
  test("unknown producers fail closed rather than silently cutting a clock path") {
    reject(ir("%hidden", "%hidden = unknown.producer %clock : i1"), "UNSUPPORTED_PRODUCER")
  }
  test("transparent payloads and unclassified primitives cannot hide a clock") {
    reject(ir(glue="%bit = seq.from_clock %clock").replace("d: %data:", "d: %bit:"), "CLOCK_REACHES_NATIVE_STORAGE")
    reject(ir().replace("ChiselAsyncEventRegister_v1", "ChiselAsyncUnclassified_v1"), "UNKNOWN_PRIMITIVE_KIND")
  }
  test("arbitrary side effects are rejected, including inside diagnostic blocks") {
    reject(ir(glue="sv.force %request, %data : i1"), "UNSUPPORTED_OPERATION")
    reject(ir(glue="sv.ifdef @SYNTHESIS {\nsv.verbatim \"force request=clock;\"\n}"), "DIAGNOSTIC_SIDE_EFFECT")
    val text=ir(glue="sv.ifdef @SYNTHESIS {\n} else {\nsv.error.procedural \"assertion\"\n}")
    assert(StructureAudit.check(text,"Top",contract)("status").str=="pass")
  }
  test("clock-free registered owners cannot contain ordinary sequential storage") {
    val c=contract; c("rtl_path")="Top"
    val text=ir(glue="%clock = seq.to_clock %request\n%hidden = seq.firreg %data clock %clock : i1")
      .replace("in %clock : !seq.clock, ", "")
    reject(text,"CLOCKED_NATIVE_OWNER",c)
  }
  test("opaque external logic cannot hide a clock behind hierarchy") {
    val text = ir("%box.out", "%bit = seq.from_clock %clock\n%box.out = hw.instance \"box\" @Opaque(in: %bit: i1) -> (out: i1)")
      .replace("module {", "module {\n  hw.module.extern @Opaque(in %in : i1, out out : i1)")
    reject(text, "CLOCK_REACHES_NATIVE_STORAGE")
  }
  test("unregistered sequential helpers inherit their native owner's prohibition") {
    val helper = """hw.module @Helper(in %clock : !seq.clock, in %data : i1, out q : i1) {
      %q = seq.firreg %data clock %clock : i1
      hw.output %q : i1
    }
    """
    val glue = "%eventClock = seq.to_clock %request\n%helper.q = hw.instance \"helper\" @Helper(clock: %eventClock: !seq.clock, data: %data: i1) -> (q: i1)"
    val text = ir("%helper.q", glue).replace("in %clock : !seq.clock, ", "")
      .replace("hw.module @Top", helper + "hw.module @Top")
    val c = contract; c("rtl_path") = "Top"
    reject(text, "CLOCKED_NATIVE_OWNER", c)
  }
  test("production export runs the audit before publishing its contract") {
    val root = Paths.get("target", "structure-spec"); Files.createDirectories(root)
    val destination = Files.createTempDirectory(root, "bad-clock-")
    val error = intercept[IllegalArgumentException] {
      ExportDesign.emit(new AsyncModule {
        this.contract.endpoint("reset", reset)
        val clock = IO(Input(Clock())); val data = IO(Input(UInt(8.W))); val out = IO(Output(UInt(8.W)))
        val cell = Module(new EventRegister(8, ModelTime.ps(1)))
        cell.reset := reset; cell.trigger := clock.asBool; cell.d := data; out := cell.q
        this.contract.primitive("payload", cell, Map("WIDTH" -> BigInt(8), "DELAY_FS" -> BigInt(1000), "RESET_VALUE" -> BigInt(0)),
          "reset", "payload")
      }, destination)
    }
    assert(error.getMessage.contains("STRUCTURE_CLOCK_REACHES_NATIVE_STORAGE"), error.getMessage)
    assert(!Files.exists(destination.resolve("contract.json")))
  }
}
