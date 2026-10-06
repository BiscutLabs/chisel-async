// SPDX-License-Identifier: Apache-2.0
package chiselasync.metadata

import chisel3._
import chisel3.experimental.IntParam

/** Passive carrier for bounded digital QDI-family assumptions. It neither
  * proves indication nor enforces a physical isochronic-fork constraint.
  */
private[metadata] class QdiMarker(parameters: Map[String, BigInt])
    extends ExtModule(parameters.map { case (key, value) => key -> IntParam(value) }) {
  override def desiredName = "ChiselAsyncQdiMarker_v1"
  val reset = IO(Input(AsyncReset()))
  val values = IO(Input(UInt(parameters("WIDTH").toInt.W)))
  addResource("/chiselasync/sv/ChiselAsyncQdiMarker_v1.sv")
}

private[metadata] object QdiMarker {
  val modes = Map("strong" -> 1, "forwarding" -> 2, "selected-strong" -> 3)
  val components = Map("storage" -> 1, "dims" -> 2, "fork" -> 3, "join" -> 4,
    "demux" -> 5, "exclusive-merge" -> 6)
  val indications = Map("storage" -> "strong", "dims" -> "strong", "fork" -> "forwarding",
    "join" -> "strong", "demux" -> "selected-strong", "exclusive-merge" -> "selected-strong")
}
