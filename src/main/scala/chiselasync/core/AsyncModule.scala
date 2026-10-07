// SPDX-License-Identifier: Apache-2.0
package chiselasync.core

import chisel3._
import chiselasync.metadata.DesignContract
import chiselasync.protocol.{Channel, FourPhase}

/** A clockless module with an explicit, active-high asynchronous reset. */
abstract class AsyncModule(val resetDomain: ResetDomain = new ResetDomain("root")) extends RawModule {
  val reset = IO(Input(AsyncReset()))
  val contract = new DesignContract(this)

  /** Typed four-phase input IO and its export contract in one declaration.
    * Request/data are inputs; acknowledgement is an output. The Scala `val`
    * supplies the usual Chisel port name; `id` names the semantic contract entry.
    *
    * @param id unique channel identifier within this module's contract
    * @param gen unbound payload type with explicit widths, such as `UInt(8.W)`
    */
  protected final def fourPhaseInput[T <: Data](id: String, gen: T): FourPhase[T] = {
    val port = IO(Flipped(new Channel(gen, resetDomain).bundled))
    contract.channel(id, port, "input")
    port
  }

  /** Typed four-phase output IO and its export contract in one declaration.
    * Request/data are outputs; acknowledgement is an input. This helper registers
    * a channel but does not add storage or declare a token capacity.
    *
    * @param id unique channel identifier within this module's contract
    * @param gen unbound payload type with explicit widths, such as `UInt(8.W)`
    */
  protected final def fourPhaseOutput[T <: Data](id: String, gen: T): FourPhase[T] = {
    val port = IO(new Channel(gen, resetDomain).bundled)
    contract.channel(id, port, "output")
    port
  }

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
