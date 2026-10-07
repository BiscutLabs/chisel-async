// SPDX-License-Identifier: Apache-2.0
package chiselasync.metadata

import chisel3._

/** Passive carrier of Click timing intent through optimization and deduplication. */
private[metadata] class ClickMarker(parameters: Map[String, BigInt])
    extends ExtModule(parameters.map { case(k,v) => k -> IntParam(v) }) {
  override def desiredName = "ChiselAsyncClickMarker_v1"
  val reset = IO(Input(AsyncReset()))
  val values = IO(Input(UInt(parameters("WIDTH").toInt.W)))
  addResource("/chiselasync/sv/ChiselAsyncClickMarker_v1.sv")
}
