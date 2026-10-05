// SPDX-License-Identifier: Apache-2.0
package chiselasync.primitives

import chisel3._

/** Two-input C-element, reset to zero. Behavioral SV view; no physical cell claim. */
class CElement extends ExtModule {
  override def desiredName: String = "ChiselAsyncCElement_v1"
  val reset = IO(Input(AsyncReset()))
  val a = IO(Input(Bool()))
  val b = IO(Input(Bool()))
  val q = IO(Output(Bool()))
  addResource("/chiselasync/sv/ChiselAsyncCElement_v1.sv")
}
