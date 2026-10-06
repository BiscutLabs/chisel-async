// SPDX-License-Identifier: Apache-2.0
package chiselasync.primitives

import chisel3._
import chiselasync.metadata.ModelTime

/** Atomic XOR; neither a Boolean feedback network nor a synthesized gate decomposition. */
class XorGate(val delay: ModelTime) extends ExtModule(Map("DELAY_FS" -> IntParam(delay.fs))) {
  override def desiredName = "ChiselAsyncXor_v1"
  val reset = IO(Input(AsyncReset()))
  val a = IO(Input(Bool())); val b = IO(Input(Bool())); val q = IO(Output(Bool()))
  addResource("/chiselasync/sv/ChiselAsyncXor_v1.sv")
}

/** Resettable T flip-flop, triggered by a rising handshake event, not a periodic clock.
  * Event spacing must exceed propagation. The enclosing handshake establishes that order.
  */
class Toggle(val delay: ModelTime) extends ExtModule(Map("DELAY_FS" -> IntParam(delay.fs))) {
  require(delay.fs > 0, "toggle requires positive model delay")
  override def desiredName = "ChiselAsyncToggle_v1"
  val reset = IO(Input(AsyncReset()))
  val trigger = IO(Input(Bool())); val q = IO(Output(Bool()))
  addResource("/chiselasync/sv/ChiselAsyncToggle_v1.sv")
}

/** Tie choices in a finite digital MUTEX view. None promises a bounded physical
  * resolution time or implements an analog metastability filter.
  */
object MutexPolicy extends Enumeration {
  val PreferFirst, PreferSecond, Alternate, SeededRandom = Value
}
class Mutex(val resolution: ModelTime, val policy: MutexPolicy.Value,
    val seed: Long = 1L, val resolutionJitter: ModelTime = ModelTime(0)) extends ExtModule(Map(
    "RESOLVE_FS" -> IntParam(resolution.fs), "POLICY" -> IntParam(policy.id),
    "RESOLVE_MAX_FS" -> IntParam(BigInt(resolution.fs) + resolutionJitter.fs), "SEED" -> IntParam(seed))) {
  require(resolution.fs > 0, "mutex simulation resolution must be positive")
  require(seed > 0 && seed <= 0xffffffffL, "mutex seed must be a nonzero unsigned 32-bit value")
  require(BigInt(resolution.fs) + resolutionJitter.fs <= Long.MaxValue, "mutex resolution range overflows")
  override def desiredName = "ChiselAsyncMutex_v1"
  val reset = IO(Input(AsyncReset()))
  val request = IO(Input(UInt(2.W))); val grant = IO(Output(UInt(2.W)))
  addResource("/chiselasync/sv/ChiselAsyncMutex_v1.sv")
}
