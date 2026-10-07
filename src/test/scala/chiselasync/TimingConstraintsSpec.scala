// SPDX-License-Identifier: Apache-2.0
package chiselasync

import chisel3._
import chiselasync.bundled.LongHoldBuffer
import chiselasync.interop.FourPhaseToTwoPhase
import chiselasync.metadata._
import chiselasync.qdi.DualRailStrongBuffer
import java.nio.file.Files
import org.scalatest.funsuite.AnyFunSuite

class TimingConstraintsSpec extends AnyFunSuite {
  test("long-hold constraints include whole data paths and both fork branches") {
    val dir = Files.createTempDirectory("ca-constraints-")
    ExportDesign.emit(new LongHoldBuffer(UInt(4.W),BundledTiming.Simulation),dir.resolve("export"))
    val plan = TimingConstraints.prepare(dir.resolve("export/contract.json"))
    assert(plan.rules.exists(r => r.id == "transform_path" && r.maxFs.contains(10000000L)))
    assert(plan.orderings == Seq(TimingConstraints.Ordering("hold_fork","hold_fork.ack_branch","hold_fork.state_branch")))
    val pins = plan.required.map(e => e.id -> (0 until e.width).map(i => TimingConstraints.ObjectRef("pin",s"mapped/${e.id}[$i]"))).toMap
    plan.emit(pins,dir.resolve("constraints"))
    val checker = Files.readString(dir.resolve("constraints/check-timing.tcl"))
    assert(checker.contains("TIMING_ENDPOINT_UNRESOLVED") && checker.contains("TIMING_PATH_UNRESOLVED"))
    assert(checker.contains("TIMING_ORDER_VIOLATION") && checker.contains("-fall_to"))
    assert(Files.readString(dir.resolve("constraints/constraints.sdc")).contains("set_min_delay 11 "))
    val missing = intercept[IllegalArgumentException] { plan.emit(pins - plan.required.head.id,dir.resolve("missing")) }
    assert(missing.getMessage.contains("INCOMPLETE_OR_EXTRA_TIMING_BINDINGS"))
    assert(!Files.exists(dir.resolve("missing")))
  }

  test("phase constraints require an explicit characterized closure margin") {
    val dir = Files.createTempDirectory("ca-phase-constraints-")
    val b = BundledTiming.Simulation
    ExportDesign.emit(new FourPhaseToTwoPhase(UInt(2.W),b,PhaseTiming(b.controls.a,ModelTime.ps(40000))),dir.resolve("export"))
    val plan = TimingConstraints.prepare(dir.resolve("export/contract.json"))
    val pins = plan.required.map(e => e.id -> (0 until e.width).map(i => TimingConstraints.ObjectRef("pin",s"mapped/${e.id}[$i]"))).toMap
    assert(intercept[IllegalArgumentException] { plan.emit(pins,dir.resolve("missing")) }.getMessage.contains("CLOSURE_MARGINS"))
    plan.emit(pins,dir.resolve("complete"),Map("adapter.phase_conversion" -> ModelTime.ps(100)))
    assert(Files.readString(dir.resolve("complete/check-timing.tcl")).contains("0.1\n"))
  }

  test("unsupported QDI obligations and zero-delay policies cannot produce a checked-looking file") {
    val dir = Files.createTempDirectory("ca-unsupported-constraints-")
    ExportDesign.emit(new DualRailStrongBuffer(UInt(2.W),QdiTiming.fixed(ModelTime.ps(1000))),dir.resolve("qdi"))
    assert(intercept[IllegalArgumentException] { TimingConstraints.prepare(dir.resolve("qdi/contract.json")) }
      .getMessage.contains("UNSUPPORTED_TIMING_OBLIGATION"))
    ExportDesign.emit(new LongHoldBuffer(UInt(2.W),BundledTiming.FunctionalOnly),dir.resolve("functional"))
    assert(intercept[IllegalArgumentException] { TimingConstraints.prepare(dir.resolve("functional/contract.json")) }
      .getMessage.contains("TIMING_REQUIRES_POSITIVE_POLICY"))
  }
}
