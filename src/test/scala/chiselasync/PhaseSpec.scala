// SPDX-License-Identifier: Apache-2.0
package chiselasync

import chisel3._
import chisel3.experimental.BundleLiterals._
import chiselasync.bundled._
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.interop._
import chiselasync.metadata._
import chiselasync.primitives.{Mutex, MutexPolicy}
import chiselasync.protocol.{Channel, TwoPhase}
import circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite

class PhaseSpec extends AnyFunSuite {
  private val cell=ModelTime(1)
  private val timing=BundledTiming.Digital(ModelTime(4),DelayBounds.fixed(cell),
    ControlDelays.uniform(DelayBounds.fixed(cell)),DelayBounds.fixed(cell),ModelTime(4))
  private val phase=PhaseTiming(DelayBounds.fixed(cell),ModelTime(2))
  test("history closure is independent of data-to-Q and guarded strictly") {
    val closure=DelayBounds(ModelTime(0),ModelTime(12),ModelTime(3))
    val policy=PhaseTiming(DelayBounds.fixed(cell),ModelTime(2),closure,ModelTime(13))
    val text=ChiselStage.emitCHIRRTL(new FourPhaseToTwoPhase(UInt(8.W),timing,policy))
    assert(text.contains("history_close")); assert(text.contains("request_guard"))
    intercept[IllegalArgumentException] { policy.copy(requestDelay=ModelTime(12)) }
    intercept[IllegalArgumentException] { policy.copy(requestDelay=ModelTime(0)) }
  }
  test("seeded MUTEX accepts unsigned seeds and rejects zero or overflowing bounds") {
    def emit(seed:Long,jitter:ModelTime) = ChiselStage.emitCHIRRTL(new FourPhaseArbiter(
      UInt(8.W),timing,cell,cell,MutexPolicy.SeededRandom,seed=seed,resolutionJitter=jitter))
    assert(emit(0xffffffffL,ModelTime(19)).contains("RESOLVE_MAX_FS = 20"))
    intercept[IllegalArgumentException] { emit(0L,cell) }
    intercept[IllegalArgumentException] { emit(0x100000000L,cell) }
    intercept[IllegalArgumentException] { emit(1L,ModelTime(Long.MaxValue)) }
  }
  test("phase return bounds reject zero cells, equality and undersized guards") {
    intercept[IllegalArgumentException] { PhaseTiming(DelayBounds.fixed(ModelTime(0)),cell) }
    intercept[IllegalArgumentException] { PhaseTiming(DelayBounds(cell,ModelTime(10),cell),ModelTime(10)) }
    intercept[IllegalArgumentException] { PhaseTiming(DelayBounds(cell,ModelTime(10),cell),ModelTime(2)) }
    assert(PhaseTiming(DelayBounds(cell,ModelTime(10),cell),ModelTime(11)).returnDelay.fs==11)
  }
  test("typed two-phase composition preserves aggregates, signedness and explicit reset") {
    class Packet extends Bundle { val tag=UInt(3.W); val value=SInt(9.W) }
    val text=ChiselStage.emitCHIRRTL(new TwoPhaseFifo(new Packet,2,timing,phase,
      Seq((new Packet).Lit(_.tag -> 5.U, _.value -> (-17).S))))
    assert(text.contains("SInt<9>")); assert(text.contains("ChiselAsyncToggle_v1"))
    assert(text.contains("ChiselAsyncXor_v1")); assert(!text.contains("input clock"))
  }
  test("two-phase connection rejects a different reset domain") {
    intercept[IllegalArgumentException] {
      ChiselStage.emitCHIRRTL(new AsyncModule {
        val a=IO(Flipped(new Channel(UInt(8.W),resetDomain).twoPhase))
        val b=IO(new Channel(UInt(8.W),new ResetDomain("other")).twoPhase)
        TwoPhase.connect(b,a)
      })
    }
  }
  test("two-phase connection rejects implicit payload resizing") {
    intercept[IllegalArgumentException] {
      ChiselStage.emitCHIRRTL(new AsyncModule {
        val a=IO(Flipped(new Channel(UInt(8.W),resetDomain).twoPhase))
        val b=IO(new Channel(UInt(9.W),resetDomain).twoPhase)
        TwoPhase.connect(b,a)
      })
    }
  }
  test("two-phase stages allow distinct payload types and reject truncated transforms") {
    assert(ChiselStage.emitCHIRRTL(new TwoPhaseStage(UInt(8.W),UInt(9.W),
      (x:UInt)=>x +& 1.U(8.W),timing,phase)).contains("UInt<9>"))
    intercept[IllegalArgumentException] {
      ChiselStage.emitCHIRRTL(new TwoPhaseStage(UInt(8.W),UInt(9.W),(x:UInt)=>x+1.U(8.W),timing,phase))
    }
  }
  test("decoder timing includes capture propagation as well as storage data delay") {
    intercept[IllegalArgumentException] {
      ChiselStage.emitCHIRRTL(new DualRailToFourPhase(UInt(3.W),timing,
        PhaseTiming(DelayBounds(cell,ModelTime(3),cell),ModelTime(4))))
    }
    intercept[IllegalArgumentException] {
      ChiselStage.emitCHIRRTL(new FourPhaseToDualRail(UInt(3.W),BundledTiming.FunctionalOnly,phase))
    }
  }
  test("arbiters preserve an explicit digital MUTEX policy and return interlocks") {
    MutexPolicy.values.foreach { policy =>
      val text=ChiselStage.emitCHIRRTL(new FourPhaseArbiter(UInt(8.W),timing,cell,cell,policy))
      assert(text.contains(s"POLICY = ${policy.id}")); assert(text.contains("interlock0"))
      assert(text.contains("interlock1")); assert(!text.contains("input clock"))
    }
    intercept[IllegalArgumentException] {
      ChiselStage.emitCHIRRTL(new FourPhaseArbiter(UInt(8.W),timing,cell,ModelTime(0),MutexPolicy.Alternate))
    }
  }
}
