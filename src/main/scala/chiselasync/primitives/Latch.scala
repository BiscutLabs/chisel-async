// SPDX-License-Identifier: Apache-2.0
package chiselasync.primitives

import chisel3._

/** Transparent-high latch with asynchronous reset. Packed primitive boundary. */
class Latch(width: Int, resetValue: BigInt = 0) extends ExtModule(Map(
    "WIDTH" -> IntParam(width), "RESET_VALUE" -> IntParam(resetValue))) {
  require(width > 0 && resetValue >= 0 && resetValue.bitLength <= width, "invalid latch width/reset value")
  override def desiredName: String = "ChiselAsyncLatch_v1"
  val reset = IO(Input(AsyncReset()))
  val enable = IO(Input(Bool()))
  val d = IO(Input(UInt(width.W)))
  val q = IO(Output(UInt(width.W)))
  addResource("/chiselasync/sv/ChiselAsyncLatch_v1.sv")
}
