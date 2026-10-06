// SPDX-License-Identifier: Apache-2.0
package chiselasync.core

import chisel3._
import chiselasync.metadata.DesignContract

/** A clockless module with an explicit, active-high asynchronous reset. */
abstract class AsyncModule(val resetDomain: ResetDomain = new ResetDomain("root")) extends RawModule {
  val reset = IO(Input(AsyncReset()))
  val contract = new DesignContract(this)

  /** Construct, reset and register a child in this module's coordinated domain.
    * A fresh top-level module still owns a distinct domain; matching names do not
    * make independently driven resets equivalent.
    */
  protected final def asyncChild[M <: AsyncModule](id: String)(gen: ResetDomain => M): M = {
    val child = Module(gen(resetDomain))
    contract.child(id, child) // Reject a factory that ignored the supplied domain.
    child.reset := reset
    child
  }
}
