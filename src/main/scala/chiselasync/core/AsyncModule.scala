// SPDX-License-Identifier: Apache-2.0
package chiselasync.core

import chisel3._
import chiselasync.metadata.DesignContract

/** A clockless module with an explicit, active-high asynchronous reset. */
abstract class AsyncModule(val resetDomain: ResetDomain = new ResetDomain("root")) extends RawModule {
  val reset = IO(Input(AsyncReset()))
  val contract = new DesignContract(this)
}
