// SPDX-License-Identifier: Apache-2.0
package chiselasync.primitives

import chisel3._
import chiselasync.metadata.ModelTime

/** Positive-edge data register with explicit asynchronous reset and a local
  * trigger input. The model delays Q; setup, hold and pulse obligations belong
  * to the enclosing Click timing contract and its test monitors.
  */
class EventRegister(val width: Int, val delay: ModelTime, val resetValue: BigInt = 0)
    extends ExtModule(Map("WIDTH" -> IntParam(width), "DELAY_FS" -> IntParam(delay.fs),
      "RESET_VALUE" -> IntParam(resetValue))) {
  require(width > 0 && delay.fs > 0 && resetValue >= 0 && resetValue.bitLength <= width, "INVALID_EVENT_REGISTER")
  override def desiredName = "ChiselAsyncEventRegister_v1"
  val reset = IO(Input(AsyncReset()))
  val trigger = IO(Input(Bool()))
  val d = IO(Input(UInt(width.W)))
  val q = IO(Output(UInt(width.W)))
  addResource("/chiselasync/sv/ChiselAsyncEventRegister_v1.sv")
}

/** Positive-edge phase flip-flop with selectable reset parity. Its state toggles
  * once per local pulse. This extends the usable initialization choices without
  * changing the existing Toggle model or its adapter contracts.
  */
class PhaseRegister(val delay: ModelTime, val initialPhase: Boolean = false)
    extends ExtModule(Map("DELAY_FS" -> IntParam(delay.fs), "RESET_VALUE" -> IntParam(if(initialPhase) 1 else 0))) {
  require(delay.fs > 0, "INVALID_PHASE_REGISTER")
  override def desiredName = "ChiselAsyncPhaseRegister_v1"
  val reset = IO(Input(AsyncReset()))
  val trigger = IO(Input(Bool()))
  val q = IO(Output(Bool()))
  addResource("/chiselasync/sv/ChiselAsyncPhaseRegister_v1.sv")
}
