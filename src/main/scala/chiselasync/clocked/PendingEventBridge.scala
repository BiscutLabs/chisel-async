// SPDX-License-Identifier: Apache-2.0
package chiselasync.clocked

import chisel3._
import chisel3.util._
import chiselasync.core.ResetDomain
import chiselasync.protocol.{Channel, FourPhase}

/** Synchronize external levels, detect rising edges, and send coalesced bit sets.
  * High AND low must each span at least syncStages+1 destination rising edges.
  * This is not an arbitrary-width pulse catcher. Repeated events coalesce while
  * pending; an event after snapshot (including its edge) belongs to the next batch.
  * Coordinated reset discards pending/in-flight batches. It does not preserve an
  * always-on event bank across an independently reset consumer.
  */
class PendingEventBridge(val width: Int, stages: Int = 2,
    domain: ResetDomain = new ResetDomain("root")) extends ClockedBridge(domain, stages) {
  require(width > 0, "event width must be positive")
  val levels = IO(Input(UInt(width.W)))
  private val events = new Channel(UInt(width.W), resetDomain)
  val out = IO(events.bundled)
  private val sender = asyncChild("sender")(d => new DecoupledToFourPhase(UInt(width.W), stages, d))
  sender.clock := clock
  FourPhase.connect(out, sender.out)
  private val sampled = VecInit((0 until width).map(i => synchronizedControl(levels(i)))).asUInt
  withClockAndReset(clock, localReset) {
    val previous = RegInit(0.U(width.W))
    val pending = RegInit(0.U(width.W))
    val rising = sampled & ~previous
    previous := sampled
    sender.in.bits := pending
    sender.in.valid := pending.orR && !localReset.asBool
    // Clear only the snapshot bank. Set wins, even on the snapshot edge.
    pending := Mux(sender.in.fire, 0.U, pending) | rising
  }
  contract.channel("out", out, "output")
  contract.endpoint("levels", levels)
  contract.endpoint("clock", clock)
  contract.endpoint("reset", reset)
}
