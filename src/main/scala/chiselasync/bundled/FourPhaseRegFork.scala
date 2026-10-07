// SPDX-License-Identifier: Apache-2.0
package chiselasync.bundled

import chisel3._
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.{BundledTiming, ModelTime}
import chiselasync.protocol.{Channel, FourPhase}

/** Registered fork with two independently typed results of one input token.
  * One shared payload slot; both outputs must complete before it can be reused.
  * This composition has long-hold storage, not a native Click event-clock register.
  * Reset empties both branches; independent initial branch tokens are not supported.
  *
  * Each branch can acknowledge independently, but a stalled branch holds the shared
  * slot and prevents its reuse. For broadcast without this extra storage/transform,
  * use [[FourPhaseFork]].
  *
  * @param a exact input payload type
  * @param b exact left-output payload type
  * @param c exact right-output payload type
  * @param transform pure combinational Chisel function producing `(left, right)`;
  *   both results must match their declared types and widths without resizing
  * @param timing digital envelope covering the complete transform before storage
  * @param cellDelay nominal delay of branch offers and completion C-element
  * @param domain coordinated reset identity; create children with `asyncChild`
  */
class FourPhaseRegFork[A <: Data, B <: Data, C <: Data](a: A, b: B, c: C,
    transform: A => (B, C), timing: BundledTiming, cellDelay: ModelTime,
    domain: ResetDomain = new ResetDomain("root")) extends AsyncModule(domain) {
  val in = IO(Flipped(new Channel(a, resetDomain).bundled))
  val left = IO(new Channel(b, resetDomain).bundled)
  val right = IO(new Channel(c, resetDomain).bundled)
  private val storage = asyncChild("storage")(d => new FourPhaseStage(a, new Joined(b, c), (value: A) => {
    val (l, r) = transform(value)
    chiselasync.protocol.Payload.requireSame(b, l)
    chiselasync.protocol.Payload.requireSame(c, r)
    val pair = Wire(new Joined(b, c)); pair.left := l; pair.right := r; pair
  }, timing, d))
  private val cells = new CompositionCells(this, cellDelay)
  FourPhase.connect(storage.in, in)
  left.bits := storage.out.bits.left
  right.bits := storage.out.bits.right
  left.req := cells.buffer("left_offer", storage.out.req.asUInt, cellDelay).asBool
  right.req := cells.buffer("right_offer", storage.out.req.asUInt, cellDelay).asBool
  storage.out.ack := cells.c("completion", Seq(left.ack, right.ack))
  contract.channel("in", in, "input"); contract.channel("left", left, "output")
  contract.channel("right", right, "output"); contract.capacity(1)
}
