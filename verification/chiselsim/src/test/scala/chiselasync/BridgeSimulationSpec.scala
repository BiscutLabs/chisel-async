// SPDX-License-Identifier: Apache-2.0
package chiselasync

import chisel3._
import chisel3.util._
import chisel3.simulator.scalatest.ChiselSim
import chiselasync.clocked.{DecoupledToFourPhase, FourPhaseToDecoupled}
import chiselasync.protocol.FourPhase
import org.scalatest.funsuite.AnyFunSuite
import org.scalatest.exceptions.TestFailedException
import java.nio.file.{Path, Paths}

class SourceBridgeHarness(corrupt: Boolean = false) extends Module {
  val in = IO(Flipped(Decoupled(UInt(8.W))))
  val out = IO(new FourPhase(UInt(8.W)))
  private val bridge = Module(new DecoupledToFourPhase(UInt(8.W)))
  bridge.clock := clock
  bridge.reset := reset.asAsyncReset
  bridge.in :<>= in
  out :<>= bridge.out
  if (corrupt) out.bits := bridge.out.bits ^ 1.U
}
class SinkBridgeHarness(corrupt: Boolean = false) extends Module {
  val in = IO(Flipped(new FourPhase(UInt(8.W))))
  val out = IO(Decoupled(UInt(8.W)))
  private val bridge = Module(new FourPhaseToDecoupled(UInt(8.W)))
  bridge.clock := clock
  bridge.reset := reset.asAsyncReset
  bridge.in :<>= in
  out :<>= bridge.out
  if (corrupt) out.bits := bridge.out.bits ^ 1.U
}

/** External handshake/transaction expectations; no access to implementation state.
  * Delays and four-state behavior remain covered by the Icarus event campaigns.
  */
class BridgeSimulationSpec extends AnyFunSuite with ChiselSim {
  override def buildDir: Path = sys.env.get("CA_CHISELSIM_DIRECTORY").map(Paths.get(_)).getOrElse(super.buildDir)
  private val words = (0 until 256) ++ Seq(0, 0, 255, 255, 85, 85, 170, 170)
  private def waitFor(clock: Clock, diagnostic: String)(done: => Boolean): Unit = {
    var elapsed = 0
    while (!done && elapsed < 16) { clock.step(); elapsed += 1 }
    assert(done, diagnostic)
  }
  private def source(corrupt: Boolean): Unit = simulate(new SourceBridgeHarness(corrupt)) { dut =>
    dut.in.valid.poke(false.B); dut.in.bits.poke(0.U); dut.out.ack.poke(false.B)
    dut.clock.step(5)
    var accepted, delivered, aborted = 0
    def offer(value: Int): Unit = {
      waitFor(dut.clock, "SOURCE_READY_DEADLINE")(dut.in.ready.peekBoolean())
      dut.in.valid.poke(true.B); dut.in.bits.poke(value.U)
      dut.clock.step(); accepted += 1
      dut.in.valid.poke(false.B); dut.in.bits.poke((value ^ 255).U)
      waitFor(dut.clock, "SOURCE_OFFER_DEADLINE")(dut.out.req.peekBoolean())
    }
    def complete(value: Int): Unit = {
      // Decoupled may change or withdraw an unaccepted offer while blocked.
      for (cycle <- 0 until 1 + value % 5) {
        dut.in.valid.poke((cycle % 2 == 0).B); dut.in.bits.poke((cycle ^ value ^ 255).U)
        assert(!dut.in.ready.peekBoolean(), "SOURCE_CAPACITY")
        assert(dut.out.req.peekBoolean(), "SOURCE_REQUEST_HOLD")
        assert(dut.out.bits.peek().litValue == value, "SOURCE_PAYLOAD")
        dut.clock.step()
      }
      dut.in.valid.poke(false.B)
      dut.out.ack.poke(true.B); delivered += 1
      dut.clock.step(2)
      assert(dut.out.req.peekBoolean(), "SOURCE_ACK_SYNC_EARLY")
      waitFor(dut.clock, "SOURCE_RETURN_DEADLINE")(!dut.out.req.peekBoolean())
      dut.out.ack.poke(false.B)
      dut.clock.step(2)
      assert(!dut.in.ready.peekBoolean(), "SOURCE_ACK_RETURN_EARLY")
      waitFor(dut.clock, "SOURCE_IDLE_DEADLINE")(dut.in.ready.peekBoolean())
    }
    // Abort a held offer, then prove reset recovery with the full value corpus.
    offer(93)
    dut.reset.poke(true.B); dut.in.valid.poke(false.B); dut.clock.step(2); aborted += 1
    assert(!dut.out.req.peekBoolean(), "SOURCE_RESET_REQUEST")
    dut.reset.poke(false.B); dut.clock.step(5)
    words.foreach { value => offer(value); complete(value) }
    assert(accepted == 265 && delivered == 264 && aborted == 1, "SOURCE_ACTIVITY")
    assert(accepted == delivered + aborted, "SOURCE_ACCOUNTING")
    println(s"CHISELSIM_SOURCE_PASS accepted=$accepted delivered=$delivered aborted=$aborted")
  }
  private def sink(corrupt: Boolean): Unit = simulate(new SinkBridgeHarness(corrupt)) { dut =>
    dut.in.req.poke(false.B); dut.in.bits.poke(0.U); dut.out.ready.poke(false.B)
    dut.clock.step(5)
    var offered, delivered, aborted = 0
    def offer(value: Int): Unit = {
      dut.in.bits.poke(value.U); dut.in.req.poke(true.B); offered += 1
      dut.clock.step(3)
      assert(!dut.out.valid.peekBoolean(), "SINK_REQUEST_SYNC_EARLY")
      waitFor(dut.clock, "SINK_VALID_DEADLINE")(dut.out.valid.peekBoolean())
    }
    offer(93)
    dut.reset.poke(true.B); dut.in.req.poke(false.B); dut.clock.step(2); aborted += 1
    assert(!dut.out.valid.peekBoolean() && !dut.in.ack.peekBoolean(), "SINK_RESET")
    dut.reset.poke(false.B); dut.clock.step(5)
    words.foreach { value =>
      offer(value)
      for (_ <- 0 until 1 + value % 7) {
        assert(dut.out.valid.peekBoolean() && !dut.in.ack.peekBoolean(), "SINK_STALL_HOLD")
        assert(dut.out.bits.peek().litValue == value, "SINK_PAYLOAD")
        dut.clock.step()
      }
      dut.out.ready.poke(true.B); dut.clock.step(); delivered += 1
      dut.out.ready.poke(false.B)
      assert(dut.in.ack.peekBoolean() && !dut.out.valid.peekBoolean(), "SINK_COMMIT")
      dut.in.req.poke(false.B); dut.clock.step(2)
      assert(dut.in.ack.peekBoolean(), "SINK_RETURN_SYNC_EARLY")
      waitFor(dut.clock, "SINK_IDLE_DEADLINE")(!dut.in.ack.peekBoolean())
    }
    assert(offered == 265 && delivered == 264 && aborted == 1, "SINK_ACTIVITY")
    assert(offered == delivered + aborted, "SINK_ACCOUNTING")
    println(s"CHISELSIM_SINK_PASS offered=$offered delivered=$delivered aborted=$aborted")
  }
  test("source bridge preserves held tokens and reset accounting") { source(false) }
  test("sink bridge commits once under backpressure and reset") { sink(false) }
  test("source observation corruption activates the payload oracle") {
    val error = intercept[TestFailedException](source(true))
    assert(error.getMessage.contains("SOURCE_PAYLOAD"))
  }
  test("sink observation corruption activates the payload oracle") {
    val error = intercept[TestFailedException](sink(true))
    assert(error.getMessage.contains("SINK_PAYLOAD"))
  }
  test("wide payloads survive the simulator command transport") {
    class WideHarness extends Module {
      val in = IO(Flipped(Decoupled(UInt(1024.W))))
      val out = IO(new FourPhase(UInt(1024.W)))
      val bridge = Module(new DecoupledToFourPhase(UInt(1024.W)))
      bridge.clock := clock; bridge.reset := reset.asAsyncReset
      bridge.in :<>= in; out :<>= bridge.out
    }
    simulate(new WideHarness) { dut =>
      dut.in.valid.poke(false.B); dut.in.bits.poke(0.U); dut.out.ack.poke(false.B)
      dut.clock.step(5)
      for (value <- Seq(BigInt(1) << 1023, (BigInt(1) << 1024) - 1, BigInt(0), BigInt(1))) {
        dut.in.ready.expect(true.B)
        dut.in.bits.poke(value.U); dut.in.valid.poke(true.B); dut.clock.step()
        dut.in.valid.poke(false.B); dut.in.bits.poke(0.U)
        waitFor(dut.clock, "WIDE_OFFER_DEADLINE")(dut.out.req.peekBoolean())
        dut.out.bits.expect(value.U)
        dut.out.ack.poke(true.B); dut.clock.step(5)
        dut.out.req.expect(false.B)
        dut.out.ack.poke(false.B); dut.clock.step(5)
      }
      println("CHISELSIM_WIDE_PASS delivered=4 bits=1024")
    }
  }
}
