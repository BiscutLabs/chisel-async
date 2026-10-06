// SPDX-License-Identifier: Apache-2.0
package chiselasync.bundled

import chisel3._
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.{BundledTiming, ModelTime}
import chiselasync.primitives.{AsymmetricCElement, ClosingLatch, ControlGate, GateOperation}
import chiselasync.protocol.{Channel, Payload}

/** Furber-Day section 7, Fig. 15, with explicit request/data/output model delays.
  * Three asymmetric C-elements and the long-hold OR remain primitive boundaries.
  * Qualified only for the documented digital models; no physical mapping is supplied.
  */
class FourPhaseStage[A <: Data, B <: Data](inGen: A, outGen: B, transform: A => B,
                                         val timing: BundledTiming,
                                         domain: ResetDomain = new ResetDomain("root")) extends AsyncModule(domain) {
  val inputChannel = new Channel(inGen, resetDomain)
  val outputChannel = new Channel(outGen, resetDomain)
  val in = IO(Flipped(inputChannel.bundled))
  val out = IO(outputChannel.bundled)
  private val transformed = transform(in.bits)
  Payload.validateType(outGen)
  Payload.requireSame(out.bits, transformed)
  contract.capacity(1)
  contract.channel("in", in, "input")
  contract.channel("out", out, "output")
  private val resetRef = contract.endpoint("reset", reset)

  private def gate(id: String, op: GateOperation.Value, delay: ModelTime, width: Int = 1,
                   resetValue: BigInt = 0): ControlGate = {
    val cell = Module(new ControlGate(width, op, delay, resetValue))
    cell.reset := reset
    cell.b := 0.U
    contract.primitive(id, cell, Map("WIDTH" -> BigInt(width), "OP" -> BigInt(op.id),
      "DELAY_FS" -> BigInt(delay.fs), "RESET_VALUE" -> resetValue), resetRef,
      s"${timing.mode}; atomic inertial ${op.toString}; reset held until quiescent")
    cell
  }
  private def state(id: String, delay: ModelTime, rising: Int, falling: Int, commonInvert: BigInt = 0,
                    fallingInvert: BigInt = 0): AsymmetricCElement = {
    val cell = Module(new AsymmetricCElement(1, rising, falling, delay,
      commonInvert = commonInvert, fallingInvert = fallingInvert))
    cell.reset := reset
    cell.rising := 1.U
    cell.falling := 0.U
    contract.primitive(id, cell, Map("COMMON" -> BigInt(1), "RISING" -> BigInt(rising),
      "FALLING" -> BigInt(falling), "DELAY_FS" -> BigInt(delay.fs),
      "RESET_VALUE" -> BigInt(0), "COMMON_INVERT" -> commonInvert, "RISING_INVERT" -> BigInt(0),
      "FALLING_INVERT" -> fallingInvert), resetRef, s"${timing.mode}; Furber-Day long-hold state cell; atomic input bubbles; ideal forks")
    cell
  }

  private val request = gate("request_delay", GateOperation.Buffer, timing.matchedDelay)
  private val data = gate("data_delay", GateOperation.Buffer, timing.dataDelay.model, outGen.getWidth)
  private val closed = gate("long_hold", GateOperation.Or, timing.controls.longHold.model)
  private val offered = gate("output_delay", GateOperation.Buffer, timing.outputDelay)
  private val a = state("a", timing.controls.a.model, 1, 1, commonInvert = 1, fallingInvert = 1)
  private val b = state("b", timing.controls.b.model, 0, 1)
  private val acknowledge = state("acknowledge", timing.controls.acknowledge.model, 1, 1, commonInvert = 1)
  private val latchData = WireDefault(UInt(outGen.getWidth.W), data.q)
  private val latchClosed = WireDefault(Bool(), closed.q.asBool)
  private val storage = Module(new ClosingLatch(outGen.getWidth, timing.latchDelay.model))
  storage.reset := reset
  contract.primitive("payload", storage, Map("WIDTH" -> BigInt(outGen.getWidth),
    "DELAY_FS" -> BigInt(timing.latchDelay.model.fs)), resetRef,
    s"${timing.mode}; transparent while closed=0; zero model aperture; inertial q propagation")

  request.a := in.req.asUInt
  data.a := transformed.asUInt
  a.common := b.q.asUInt
  a.rising := request.q
  a.falling := out.ack.asUInt
  closed.a := a.q.asUInt
  closed.b := out.ack.asUInt
  acknowledge.common := b.q.asUInt
  acknowledge.rising := closed.q
  acknowledge.falling := request.q
  b.common := acknowledge.q.asUInt
  b.falling := closed.q
  storage.closed := latchClosed
  storage.d := latchData
  offered.a := a.q.asUInt
  in.ack := acknowledge.q
  out.req := offered.q.asBool
  out.bits := storage.q.asTypeOf(outGen)

  // Actual timing intent also resides in the preserved primitive parameters.
  contract.endpoint("latch_data", latchData)
  contract.endpoint("latch_closed", latchClosed)
  contract.longHoldTiming("bundling", timing, "in_request", "in_data", "latch_data", "latch_closed",
    "in_acknowledge", "out_request", "out_data")
}

class LongHoldBuffer[T <: Data](gen: T, timing: BundledTiming,
                                domain: ResetDomain = new ResetDomain("root"))
    extends FourPhaseStage(gen, gen, (value: T) => value, timing, domain)
