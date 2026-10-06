// SPDX-License-Identifier: Apache-2.0
package chiselasync.metadata

import chisel3._
import chisel3.experimental.IntParam

/** Passive constraint carrier. No outputs or storage; consume intent before
  * synthesis removes the empty definition. This is not a timing enforcement cell.
  */
private[metadata] class TimingMarker(parameters: Map[String, BigInt])
    extends ExtModule(parameters.map { case (key, value) => key -> IntParam(value) }) {
  override def desiredName = "ChiselAsyncTimingMarker_v1"
  val reset = IO(Input(AsyncReset()))
  val values = IO(Input(UInt(parameters("WIDTH").toInt.W)))
  addResource("/chiselasync/sv/ChiselAsyncTimingMarker_v1.sv")
}

private[metadata] object TimingMarker {
  val boundRoles = Seq("A", "B", "ACKNOWLEDGE", "LONG_HOLD", "DATA", "LATCH")
  val defaults: Map[String, BigInt] = (Seq("KIND", "WIDTH", "SETUP_FS", "HOLD_FS", "MATCHED_FS", "OUTPUT_FS") ++
    boundRoles.flatMap(role => Seq("MIN", "MAX", "MODEL").map(bound => s"${role}_${bound}_FS")))
    .map(_ -> BigInt(0)).toMap
}
