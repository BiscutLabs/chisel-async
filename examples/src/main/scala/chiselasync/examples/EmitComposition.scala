// SPDX-License-Identifier: Apache-2.0
package chiselasync.examples

import chisel3._
import chiselasync.bundled._
import chiselasync.core.AsyncModule
import chiselasync.metadata.{ExportDesign, ModelTime}
import chiselasync.protocol.{Channel, FourPhase}
import java.nio.file.Paths

class FifoOneExample extends FourPhaseFifo(UInt(8.W), 1, LongHoldModels.digital)
class FifoExample extends FourPhaseFifo(UInt(8.W), 3, LongHoldModels.digital)
class InitializedFifoExample extends FourPhaseFifo(UInt(8.W), 3, LongHoldModels.digital,
  Seq(0x12.U(8.W), 0x12.U(8.W), 0xe7.U(8.W)))
class InitialTokensExample extends InitialTokens(UInt(8.W), Seq(0x12.U(8.W), 0x12.U(8.W), 0xe7.U(8.W)),
  LongHoldModels.digital, ModelTime.ps(1000))
class InitialWideExample extends InitialTokens(UInt(65.W),
  Seq(BigInt(1)<<64, (BigInt(1)<<65)-1, BigInt(1)<<32, BigInt(1)<<32).map(_.U(65.W)),
  LongHoldModels.digital, ModelTime.ps(1000))
class ForkExample extends FourPhaseFork(UInt(8.W), 3, ModelTime.ps(1000))
class JoinExample extends FourPhaseJoin(UInt(8.W), SInt(9.W), LongHoldModels.digital, ModelTime.ps(1000))
class SelectExample extends FourPhaseSelect(UInt(8.W), 3, LongHoldModels.digital, ModelTime.ps(1000))
class MergeExample extends FourPhaseMerge(UInt(8.W), 3, LongHoldModels.digital, ModelTime.ps(1000))

/** Unequal branch depths and type-changing arithmetic reconverge by token position. */
class ForkJoinExample extends AsyncModule {
  val in = IO(Flipped(new Channel(UInt(8.W), resetDomain).bundled))
  val out = IO(new Channel(new Joined(UInt(8.W), UInt(9.W)), resetDomain).bundled)
  private val fork = asyncChild("fork")(d => new FourPhaseFork(UInt(8.W), 2, ModelTime.ps(1000), d))
  private val fast = asyncChild("fast")(d => new FourPhaseStage(UInt(8.W), UInt(8.W),
    (x: UInt) => x ^ 0xa5.U(8.W), LongHoldModels.digital, d))
  private val slow = asyncChild("slow")(d => new FourPhaseFifo(UInt(8.W), 2, LongHoldModels.digital, domain = d))
  private val sum = asyncChild("sum")(d => new FourPhaseStage(UInt(8.W), UInt(9.W),
    (x: UInt) => x +& 1.U(8.W), LongHoldModels.digital, d))
  private val join = asyncChild("join")(d => new FourPhaseJoin(UInt(8.W), UInt(9.W),
    LongHoldModels.digital, ModelTime.ps(1000), d))
  FourPhase.connect(fork.in, in); FourPhase.connect(fast.in, fork.out(0))
  FourPhase.connect(slow.in, fork.out(1)); FourPhase.connect(sum.in, slow.out)
  FourPhase.connect(join.left, fast.out); FourPhase.connect(join.right, sum.out)
  FourPhase.connect(out, join.out)
  contract.endpoint("reset", reset); contract.channel("in", in, "input"); contract.channel("out", out, "output")
}

/** One initialized token circulates, advances, and broadcasts each value externally.
  * External backpressure stops the ring. No periodic clock or zero-time oscillation.
  */
class FeedbackExample extends AsyncModule {
  val out = IO(new Channel(UInt(8.W), resetDomain).bundled)
  private val fifo = asyncChild("fifo")(d => new FourPhaseFifo(UInt(8.W), 2, LongHoldModels.digital,
    Seq(7.U(8.W)), domain = d))
  private val fork = asyncChild("fork")(d => new FourPhaseFork(UInt(8.W), 2, ModelTime.ps(1000), d))
  private val step = asyncChild("step")(d => new FourPhaseStage(UInt(8.W), UInt(8.W),
    (x: UInt) => x + 1.U(8.W), LongHoldModels.digital, d))
  FourPhase.connect(fork.in, fifo.out); FourPhase.connect(out, fork.out(0))
  FourPhase.connect(step.in, fork.out(1)); FourPhase.connect(fifo.in, step.out)
  contract.endpoint("reset", reset); contract.channel("out", out, "output")
}

object EmitComposition {
  def main(args: Array[String]): Unit = {
    require(args.length == 1)
    Seq[(String, () => AsyncModule)](
      "fifo_one" -> (() => new FifoOneExample), "fifo" -> (() => new FifoExample),
      "initialized_fifo" -> (() => new InitializedFifoExample), "initial_tokens" -> (() => new InitialTokensExample),
      "initial_wide" -> (() => new InitialWideExample),
      "fork" -> (() => new ForkExample), "join" -> (() => new JoinExample),
      "select" -> (() => new SelectExample), "merge" -> (() => new MergeExample),
      "fork_join" -> (() => new ForkJoinExample), "feedback" -> (() => new FeedbackExample)
    ).foreach { case (id, gen) => ExportDesign.emit(gen(), Paths.get(args(0), id)) }
  }
}
