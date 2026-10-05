// SPDX-License-Identifier: Apache-2.0
package chiselasync.bundled

import chisel3._
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.protocol.FourPhase

/** One-entry functional buffer. Coordinated reset flushes the outstanding token.
  *
  * This first implementation selects a zero-delay behavioral storage view. It does not
  * establish physical timing or a synthesized asynchronous controller implementation.
  */
class FourPhaseBuffer[T <: Data](gen: T, domain: ResetDomain = new ResetDomain("root")) extends AsyncModule(domain) {
  val in = IO(Flipped(new FourPhase(gen, Some(resetDomain))))
  val out = IO(new FourPhase(gen, Some(resetDomain)))
  private val storage = Module(new FourPhaseStorage(gen.getWidth))
  storage.reset := reset
  storage.in_req := in.req
  storage.in_bits := in.bits.asUInt
  in.ack := storage.in_ack
  out.req := storage.out_req
  out.bits := storage.out_bits.asTypeOf(gen)
  storage.out_ack := out.ack
  contract.capacity(1)
  contract.channel("in", in, "input")
  contract.channel("out", out, "output")
  contract.primitive("storage", storage, Map("WIDTH" -> BigInt(gen.getWidth)),
    contract.endpoint("reset", reset), "capacity=1; reset flushes token and data; no external effects")
}

private class FourPhaseStorage(width: Int) extends ExtModule(Map("WIDTH" -> IntParam(width))) {
  override def desiredName: String = "ChiselAsyncFourPhaseStorage_v1"
  val reset = IO(Input(AsyncReset()))
  val in_req = IO(Input(Bool()))
  val in_bits = IO(Input(UInt(width.W)))
  val in_ack = IO(Output(Bool()))
  val out_req = IO(Output(Bool()))
  val out_bits = IO(Output(UInt(width.W)))
  val out_ack = IO(Input(Bool()))
  addResource("/chiselasync/sv/ChiselAsyncFourPhaseStorage_v1.sv")
}
