// SPDX-License-Identifier: Apache-2.0
package chiselasync.primitives

import chisel3._
import chiselasync.metadata.{DelayPolicy, ModelTime}

/** Behavioral captured-value delay. Reset cancels pending deliveries. */
class DelayLine(width: Int, val delay: ModelTime, val policy: DelayPolicy = DelayPolicy.Transport)
    extends ExtModule(Map("WIDTH" -> IntParam(width), "DELAY_FS" -> IntParam(delay.fs),
                         "POLICY" -> IntParam(policy.code))) {
  require(width > 0 && delay.fs > 0, "delay line requires positive width and delay")
  override def desiredName: String = "ChiselAsyncDelayLine_v1"
  val reset = IO(Input(AsyncReset()))
  val d = IO(Input(UInt(width.W)))
  val q = IO(Output(UInt(width.W)))
  addResource("/chiselasync/sv/ChiselAsyncDelayLine_v1.sv")
}
