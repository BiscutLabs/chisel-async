import chiselasync.testing.AsyncTest
import chiselasync.testing.AsyncTest.{Input, Output}
import java.nio.file.Paths
import org.scalatest.funsuite.AnyFunSuite

class AsyncDesignSpec extends AnyFunSuite {
  test("adder pipeline survives independently varied cells and backpressure") {
    val pairs = Seq((0,0), (255,255), (85,85), (85,85)) ++ (0 until 32).map(i => (i*7 % 256, i*13 % 256))
    val results = AsyncTest.check(new AddPipeline,
      Seq(Input("in", pairs.map { case (a,b) => Map("in_bits_a" -> BigInt(a), "in_bits_b" -> BigInt(b)) })),
      Seq(Output("out", pairs.map { case (a,b) => Map("out_bits" -> BigInt(a+b)) })),
      Seq(1,2,42,137), Paths.get("build/async-adder"))
    assert(results.size == 4 && results.forall(_.variedCells > 0))
  }
  test("GCD public composition computes the mathematical reference") {
    val pairs = Seq((0,0), (0,255), (255,0), (255,255), (255,1), (1,255), (91,35), (91,35), (240,144)) ++
      (1 to 20).map(i => (i*71 % 256, i*31 % 256))
    val results = AsyncTest.check(new Gcd,
      Seq(Input("in", pairs.map { case (a,b) => Map("in_bits_a" -> BigInt(a), "in_bits_b" -> BigInt(b)) })),
      Seq(Output("out", pairs.map { case (a,b) => Map("out_bits" -> BigInt(a).gcd(BigInt(b))) })),
      Seq(1,2,42,137), Paths.get("build/async-gcd"))
    assert(results.size == 4 && results.forall(_.variedCells > 0))
  }
}
