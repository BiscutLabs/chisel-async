// SPDX-License-Identifier: Apache-2.0
package chiselasync.bundled

import chisel3._
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.primitives.Latch
import chiselasync.protocol.{FourPhase, Payload}

/** One-entry, shape-preserving transform with explicit latch state.
  * Qualified only with the zero-delay digital latch view. The self-closing capture
  * enable is not a physical pulse-width or gate-delay guarantee; see contracts.md.
  */
class FourPhaseStage[T <: Data](gen: T, transform: T => T,
                               domain: ResetDomain = new ResetDomain("root")) extends AsyncModule(domain) {
  val in = IO(Flipped(new FourPhase(gen, Some(resetDomain))))
  val out = IO(new FourPhase(gen, Some(resetDomain)))
  private val transformed = transform(in.bits)
  Payload.requireSame(in.bits, transformed)

  private val occupied = Module(new Latch(1))
  private val returning = Module(new Latch(1))
  private val acknowledged = Module(new Latch(1))
  private val payload = Module(new Latch(gen.getWidth))
  private val full = occupied.q.asBool
  private val back = returning.q.asBool
  private val ack = acknowledged.q.asBool
  // Wait for BOTH return-state latches to clear before accepting a pending offer.
  private val take = !reset.asBool && !full && !back && in.req && !ack && !out.ack
  private val release = back && !out.ack

  // Each closing enable depends on its own stored state, so a simultaneous
  // data/input transition cannot leak through a stale transparent enable.
  occupied.enable := take || (full && release)
  occupied.d := (!back).asUInt
  returning.enable := out.ack || back
  returning.d := full.asUInt
  acknowledged.enable := take || ack
  acknowledged.d := in.req.asUInt
  payload.enable := take
  payload.d := transformed.asUInt
  in.ack := ack
  out.req := full && !back
  out.bits := payload.q.asTypeOf(gen)

  contract.capacity(1)
  contract.channel("in", in, "input")
  contract.channel("out", out, "output")
  private val resetRef = contract.endpoint("reset", reset)
  Seq("occupied" -> occupied, "returning" -> returning,
      "acknowledged" -> acknowledged, "payload" -> payload).foreach { case (id, cell) =>
    cell.reset := reset
    contract.primitive(id, cell, Map("WIDTH" -> BigInt(cell.q.getWidth), "RESET_VALUE" -> BigInt(0)),
      resetRef, "zero-delay functional latch; reset clears state; no physical pulse-width qualification")
  }
}

/** Identity-transform structural alternative; the behavioral buffer remains available. */
class StructuralFourPhaseBuffer[T <: Data](gen: T, domain: ResetDomain = new ResetDomain("root"))
    extends FourPhaseStage(gen, (value: T) => value, domain)
