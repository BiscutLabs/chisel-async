// SPDX-License-Identifier: Apache-2.0
package chiselasync.qdi

import chisel3._
import chisel3.util.Cat
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.ModelTime
import chiselasync.primitives.{AsymmetricCElement, ControlGate, GateOperation}
import chiselasync.protocol.Channel

/** Small WCHB-style storage/completion probe. Atomic cells and ideal forks only;
  * no physical QDI mapping is supplied. This half-buffer is not a fully decoupled FIFO.
  */
class DualRailBuffer[T <: Data](gen: T, cellDelay: ModelTime,
                               domain: ResetDomain = new ResetDomain("root")) extends AsyncModule(domain) {
  require(cellDelay.fs > 0, "dual-rail probe requires positive model delay")
  val channel = new Channel(gen, resetDomain)
  val in = IO(Flipped(channel.dualRail))
  val out = IO(channel.dualRail)
  contract.capacity(1)
  contract.dualRailChannel("in", in, "input")
  contract.dualRailChannel("out", out, "output")
  private val resetRef = contract.endpoint("reset", reset)
  private val width = gen.getWidth
  private val zeros = Wire(Vec(width, Bool()))
  private val ones = Wire(Vec(width, Bool()))
  private val present = Wire(Vec(width, Bool()))
  private def c(id: String, count: Int, invert: Int): AsymmetricCElement = {
    val instance = Module(new AsymmetricCElement(count, 0, 0, cellDelay, commonInvert = invert))
    instance.reset := reset
    instance.rising := 1.U
    instance.falling := 0.U
    contract.primitive(id, instance, Map("COMMON" -> BigInt(count), "RISING" -> BigInt(0), "FALLING" -> BigInt(0),
      "DELAY_FS" -> BigInt(cellDelay.fs), "RESET_VALUE" -> BigInt(0), "COMMON_INVERT" -> BigInt(invert),
      "RISING_INVERT" -> BigInt(0), "FALLING_INVERT" -> BigInt(0)), resetRef, "atomic C; monotonic phases; ideal forks")
    instance
  }
  for (i <- 0 until width) {
    val z = c(s"zero$i", 2, 2)
    val o = c(s"one$i", 2, 2)
    z.common := Cat(out.ack, in.zero.asUInt(i))
    o.common := Cat(out.ack, in.one.asUInt(i))
    zeros(i) := z.q
    ones(i) := o.q
    val p = Module(new ControlGate(1, GateOperation.Or, cellDelay))
    p.reset := reset
    p.a := z.q.asUInt
    p.b := o.q.asUInt
    present(i) := p.q.asBool
    contract.primitive(s"present$i", p, Map("WIDTH" -> BigInt(1), "OP" -> BigInt(2),
      "DELAY_FS" -> BigInt(cellDelay.fs), "RESET_VALUE" -> BigInt(0)), resetRef, "per-bit presence OR")
  }
  private val completion = c("completion", width, 0)
  completion.common := present.asUInt
  in.ack := completion.q
  out.zero := zeros.asUInt.asTypeOf(gen)
  out.one := ones.asUInt.asTypeOf(gen)
}
