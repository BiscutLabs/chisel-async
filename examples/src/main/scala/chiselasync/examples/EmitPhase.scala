// SPDX-License-Identifier: Apache-2.0
package chiselasync.examples

import chisel3._
import chiselasync.bundled._
import chiselasync.core.AsyncModule
import chiselasync.interop._
import chiselasync.metadata.{DelayBounds, ExportDesign, ModelTime, PhaseTiming}
import chiselasync.primitives.MutexPolicy
import chiselasync.protocol.{Channel, FourPhase, DualRail, TwoPhase}
import java.nio.file.Paths

object PhaseModels {
  val phase = PhaseTiming(DelayBounds(ModelTime.ps(1000), ModelTime.ps(10000), ModelTime.ps(1000)), ModelTime.ps(40000))
}
class ToFourPhaseExample extends TwoPhaseToFourPhase(UInt(8.W), LongHoldModels.digital, PhaseModels.phase)
class ToTwoPhaseExample extends FourPhaseToTwoPhase(UInt(8.W), LongHoldModels.digital, PhaseModels.phase)
class ArbiterExample extends FourPhaseArbiter(UInt(8.W), LongHoldModels.digital,
  ModelTime.ps(1000), ModelTime.ps(1000), MutexPolicy.Alternate)
class TwoBufferExample extends TwoPhaseBuffer(UInt(8.W), LongHoldModels.digital, PhaseModels.phase)
class TwoWideExample extends TwoPhaseBuffer(UInt(65.W), LongHoldModels.digital, PhaseModels.phase)
class TwoFifoExample extends TwoPhaseFifo(UInt(8.W), 3, LongHoldModels.digital, PhaseModels.phase)
class TwoInitializedExample extends TwoPhaseFifo(UInt(8.W), 3, LongHoldModels.digital, PhaseModels.phase,
  Seq(0x12.U(8.W), 0x12.U(8.W), 0xe7.U(8.W)))
class TwoInitialExample extends TwoPhaseInitialTokens(UInt(8.W), Seq(0x12.U(8.W), 0x12.U(8.W), 0xe7.U(8.W)),
  LongHoldModels.digital, PhaseModels.phase, ModelTime.ps(1000))
class TwoForkExample extends TwoPhaseFork(UInt(8.W), 3, PhaseModels.phase, ModelTime.ps(1000))
class TwoJoinExample extends TwoPhaseJoin(UInt(8.W), SInt(9.W), LongHoldModels.digital, PhaseModels.phase, ModelTime.ps(1000))
class TwoSelectExample extends TwoPhaseDemux(UInt(8.W), 3, LongHoldModels.digital, PhaseModels.phase, ModelTime.ps(1000))
class TwoMergeExample extends TwoPhaseMerge(UInt(8.W), 3, LongHoldModels.digital, PhaseModels.phase, ModelTime.ps(1000))
class TwoArbiterExample extends TwoPhaseArbiter(UInt(8.W), LongHoldModels.digital, PhaseModels.phase,
  ModelTime.ps(1000), ModelTime.ps(1000), MutexPolicy.Alternate)
class TwoTransformExample extends TwoPhaseStage(UInt(8.W), UInt(9.W), (x: UInt) => x +& 1.U(8.W),
  LongHoldModels.digital, PhaseModels.phase)
class ToDualExample extends FourPhaseToDualRail(UInt(3.W), LongHoldModels.digital, PhaseModels.phase)
class FromDualExample extends DualRailToFourPhase(UInt(3.W), LongHoldModels.digital, PhaseModels.phase)
class EncodingRoundTripExample extends AsyncModule {
  val in = IO(Flipped(new Channel(UInt(8.W), resetDomain).bundled))
  val out = IO(new Channel(UInt(8.W), resetDomain).bundled)
  private val encode = asyncChild("encode")(d => new FourPhaseToDualRail(UInt(8.W), LongHoldModels.digital, PhaseModels.phase, d))
  private val decode = asyncChild("decode")(d => new DualRailToFourPhase(UInt(8.W), LongHoldModels.digital, PhaseModels.phase, d))
  FourPhase.connect(encode.in, in); DualRail.connect(decode.in, encode.out); FourPhase.connect(out, decode.out)
  contract.capacity(2); contract.endpoint("reset", reset); contract.channel("in", in, "input"); contract.channel("out", out, "output")
}
class PhaseRoundTripExample extends AsyncModule {
  val in = IO(Flipped(new Channel(UInt(8.W), resetDomain).bundled))
  val out = IO(new Channel(UInt(8.W), resetDomain).bundled)
  private val toTwo = asyncChild("toTwo")(d => new FourPhaseToTwoPhase(UInt(8.W), LongHoldModels.digital, PhaseModels.phase, d))
  private val toFour = asyncChild("toFour")(d => new TwoPhaseToFourPhase(UInt(8.W), LongHoldModels.digital, PhaseModels.phase, d))
  FourPhase.connect(toTwo.in, in); TwoPhase.connect(toFour.in, toTwo.out); FourPhase.connect(out, toFour.out)
  contract.capacity(2); contract.endpoint("reset", reset); contract.channel("in", in, "input"); contract.channel("out", out, "output")
}

object EmitPhase {
  def main(args: Array[String]): Unit = {
    require(args.length == 1)
    Seq[(String, () => AsyncModule)](
      "phase_to_four" -> (() => new ToFourPhaseExample), "phase_to_two" -> (() => new ToTwoPhaseExample),
      "arbiter" -> (() => new ArbiterExample), "two_buffer" -> (() => new TwoBufferExample),
      "two_wide" -> (() => new TwoWideExample),
      "two_fifo" -> (() => new TwoFifoExample), "two_initialized" -> (() => new TwoInitializedExample),
      "two_initial" -> (() => new TwoInitialExample), "two_fork" -> (() => new TwoForkExample),
      "two_join" -> (() => new TwoJoinExample), "two_select" -> (() => new TwoSelectExample),
      "two_merge" -> (() => new TwoMergeExample), "two_arbiter" -> (() => new TwoArbiterExample),
      "two_transform" -> (() => new TwoTransformExample), "encoding_to_dual" -> (() => new ToDualExample),
      "encoding_from_dual" -> (() => new FromDualExample), "encoding_roundtrip" -> (() => new EncodingRoundTripExample),
      "phase_roundtrip" -> (() => new PhaseRoundTripExample)
    ).foreach { case (id, gen) => ExportDesign.emit(gen(), Paths.get(args(0), id)) }
  }
}
