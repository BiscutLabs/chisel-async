// SPDX-License-Identifier: Apache-2.0
package chiselasync.primitives

import chisel3._
import chiselasync.core.AsyncModule
import chiselasync.metadata.ModelTime
import chiselasync.protocol.Payload

/** Packed external boundary for a whole-transform simulation allowance.
  * No reset or validity mask, no storage, no clock, and no physical delay line.
  * Physical exporters replace this model with q=a and retain transform timing
  * obligations. Unknown/invalid inputs propagate; do not use this on control.
  */
class PassiveDataAllowance(val width: Int, val delay: ModelTime) extends ExtModule(Map(
    "WIDTH" -> IntParam(width), "DELAY_FS" -> IntParam(delay.fs))) {
  require(width > 0, "PASSIVE_ALLOWANCE_WIDTH")
  override def desiredName: String = "ChiselAsyncPassiveDataAllowance_v1"
  val a = IO(Input(UInt(width.W)))
  val q = IO(Output(UInt(width.W)))
  addResource("/chiselasync/sv/ChiselAsyncPassiveDataAllowance_v1.sv")
}

object PassiveDataAllowance {
  /** Typed convenience wrapper. The reset endpoint records the enclosing
    * protocol domain only; this primitive has no reset pin or reset behavior.
    * The caller owns complete transform, fanout, capture and source-release STA.
    */
  def apply[T <: Data](owner: AsyncModule, id: String, data: T,
                      delay: ModelTime, resetEndpoint: String): T = {
    Payload.validateType(data, allowDirections = true)
    val cell = Module(new PassiveDataAllowance(data.getWidth, delay))
    cell.a := data.asUInt
    owner.contract.primitive(id, cell, Map("WIDTH" -> BigInt(data.getWidth),
      "DELAY_FS" -> BigInt(delay.fs)), resetEndpoint,
      "whole-transform inertial simulation allowance; physical alias q=a; no reset, mask or storage; invalid/X payload propagates; handshake-qualified use; setup/hold and fanout audit required")
    cell.q.asTypeOf(chiselTypeOf(data))
  }
}
