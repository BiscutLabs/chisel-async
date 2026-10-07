import chisel3._
import chisel3.experimental.BundleLiterals._
import chiselasync.testing.AsyncTest
import chiselasync.testing.AsyncTest.{Input, Output}
import java.nio.file.Paths
import org.scalatest.funsuite.AnyFunSuite

class ClickAdderSpec extends AnyFunSuite {
  test("tagged Click adder preserves carry, order and repeated tokens under backpressure") {
    val jobs = Seq((0, 0, 0), (255, 255, 15), (85, 85, 7), (85, 85, 7)) ++
      (0 until 40).map(i => (i * 37 % 256, i * 71 % 256, i % 16))
    val inputs = jobs.map { case (a, b, tag) =>
      (new ClickOperands).Lit(_.a -> a.U(8.W), _.b -> b.U(8.W), _.tag -> tag.U(4.W))
    }
    val expected = jobs.map { case (a, b, tag) =>
      // Independent integer arithmetic; do not reuse the hardware transform.
      (new ClickSum).Lit(_.sum -> (BigInt(a) + b).U(9.W), _.tag -> tag.U(4.W))
    }
    val results = AsyncTest.check(
      new ClickAdder,
      Seq(Input.literals("in", inputs)),
      Seq(Output.literals("out", expected)),
      seeds = 1L to 64L,
      directory = Paths.get("build/click-adder"))
    assert(results.size == 64 && results.forall(_.variedCells > 0))
  }
}
