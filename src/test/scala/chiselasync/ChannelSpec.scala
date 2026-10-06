// SPDX-License-Identifier: Apache-2.0
package chiselasync

import chisel3._
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.protocol.{Channel, DualRail}
import chiselasync.clocked.{DecoupledToFourPhase, FourPhaseToDecoupled}
import chiselasync.qdi.DualRailBuffer
import chiselasync.metadata.ModelTime
import circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite

class ChannelSpec extends AnyFunSuite {
  class Packet extends Bundle { val signed = SInt(9.W); val flags = Vec(2, Bool()) }

  test("one logical payload binds to three distinct electrical interfaces") {
    val text = ChiselStage.emitCHIRRTL(new AsyncModule {
      val flow = new Channel(new Packet, resetDomain)
      val bundled = IO(flow.bundled)
      val dual = IO(flow.dualRail)
      val clocked = IO(flow.decoupled)
      bundled.bits := 0.U.asTypeOf(new Packet); bundled.req := false.B
      dual.zero := 0.U.asTypeOf(new Packet);dual.one := 0.U.asTypeOf(new Packet)
      clocked.bits := 0.U.asTypeOf(new Packet);clocked.valid := false.B
      flow.requireCompatible(new Channel(new Packet, resetDomain))
    })
    assert(text.contains("signed : SInt<9>") && text.contains("zero") && text.contains("ready"))
    assert(!text.contains("input clock"))
  }

  test("logical compatibility checks shape and reset identity, not just packed width") {
    val domain = new ResetDomain("same")
    val a = new Channel(UInt(9.W), domain)
    intercept[IllegalArgumentException] { a.requireCompatible(new Channel(SInt(9.W), domain)) }
    intercept[IllegalArgumentException] { a.requireCompatible(new Channel(UInt(9.W), new ResetDomain("same"))) }
  }

  test("dual-rail composition rejects equal-width incompatible payloads") {
    intercept[IllegalArgumentException] {
      ChiselStage.emitCHIRRTL(new AsyncModule {
        val in = IO(Flipped(new DualRail[Data](SInt(9.W), resetDomain)))
        val out = IO(new DualRail[Data](UInt(9.W), resetDomain))
        DualRail.connect(out, in)
      })
    }
  }

  test("dual-rail storage elaborates nested payloads without a clock") {
    val text = ChiselStage.emitCHIRRTL(new DualRailBuffer(new Packet, ModelTime(1000)))
    assert(text.contains("COMMON = 11") && !text.contains("input clock"))
  }

  test("bridges retain explicit clocks and reject a single synchronizer stage") {
    for (gen <- Seq(() => new DecoupledToFourPhase(new Packet), () => new FourPhaseToDecoupled(new Packet))) {
      val text = ChiselStage.emitCHIRRTL(gen())
      assert(text.contains("input clock : Clock") && text.contains("AsyncReset"))
    }
    intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new DecoupledToFourPhase(UInt(8.W), 1)) }
    intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new FourPhaseToDecoupled(UInt(8.W), 1)) }
  }
}
