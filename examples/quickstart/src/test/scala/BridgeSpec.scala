import chisel3._
import chisel3.util.Decoupled
import chisel3.simulator.scalatest.ChiselSim
import chiselasync.clocked.DecoupledToFourPhase
import chiselasync.protocol.FourPhase
import org.scalatest.funsuite.AnyFunSuite
import java.nio.file.{Path, Paths}

class BridgeHarness extends Module {
  val in = IO(Flipped(Decoupled(UInt(8.W))))
  val out = IO(new FourPhase(UInt(8.W)))
  private val bridge = Module(new DecoupledToFourPhase(UInt(8.W)))
  bridge.clock := clock
  bridge.reset := reset.asAsyncReset
  bridge.in :<>= in
  out :<>= bridge.out
}

class BridgeSpec extends AnyFunSuite with ChiselSim {
  override def buildDir: Path = sys.env.get("CA_CHISELSIM_DIRECTORY")
    .map(Paths.get(_)).getOrElse(super.buildDir)

  test("holds tokens through return") {
    simulate(new BridgeHarness) { dut =>
      dut.in.valid.poke(false.B)
      dut.in.bits.poke(0.U)
      dut.out.ack.poke(false.B)
      dut.reset.poke(true.B)
      dut.clock.step(2)
      dut.reset.poke(false.B)
      dut.clock.step(5)

      def awaitState(message: String)(ready: => Boolean): Unit = {
        var cycles = 0
        while (!ready && cycles < 20) { dut.clock.step(); cycles += 1 }
        assert(ready, message)
      }

      var delivered = 0
      for (value <- Seq(0, 255, 85, 85)) {
        awaitState("input ready deadline")(dut.in.ready.peekBoolean())
        dut.in.bits.poke(value.U)
        dut.in.valid.poke(true.B)
        dut.clock.step()
        dut.in.valid.poke(false.B)
        dut.in.bits.poke((value ^ 255).U)
        awaitState("output request deadline")(dut.out.req.peekBoolean())
        for (_ <- 0 until 4) {
          dut.out.bits.expect(value.U)
          dut.out.req.expect(true.B)
          dut.in.ready.expect(false.B)
          dut.clock.step()
        }
        dut.out.ack.poke(true.B)
        delivered += 1
        awaitState("request return deadline")(!dut.out.req.peekBoolean())
        dut.out.bits.expect(value.U)
        dut.in.ready.expect(false.B)
        dut.clock.step(3)
        dut.out.bits.expect(value.U)
        dut.out.ack.poke(false.B)
        awaitState("ack return deadline")(dut.in.ready.peekBoolean())
      }
      assert(delivered == 4)
    }
  }
}
