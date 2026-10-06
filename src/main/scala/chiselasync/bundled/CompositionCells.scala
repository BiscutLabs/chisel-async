// SPDX-License-Identifier: Apache-2.0
package chiselasync.bundled

import chisel3._
import chisel3.util.Cat
import chiselasync.core.AsyncModule
import chiselasync.metadata.ModelTime
import chiselasync.primitives.{AsymmetricCElement, ControlGate, GateOperation}

private[bundled] class AtomicAnd(count: Int, delay: ModelTime, invert: BigInt)
    extends ExtModule(Map("INPUTS" -> IntParam(count), "DELAY_FS" -> IntParam(delay.fs),
      "INVERT" -> IntParam(invert))) {
  override def desiredName = "ChiselAsyncAnd_v1"
  val reset = IO(Input(AsyncReset()))
  val d = IO(Input(UInt(count.W)))
  val q = IO(Output(Bool()))
  addResource("/chiselasync/sv/ChiselAsyncAnd_v1.sv")
}

private[bundled] class ProtocolGuard(lanes: Int, mode: Int)
    extends ExtModule(Map("LANES" -> IntParam(lanes), "MODE" -> IntParam(mode))) {
  override def desiredName = "ChiselAsyncProtocolGuard_v1"
  val reset = IO(Input(AsyncReset()))
  val request = IO(Input(UInt(lanes.W)))
  val acknowledge = IO(Input(UInt(lanes.W)))
  val valid = IO(Input(Bool()))
  addResource("/chiselasync/sv/ChiselAsyncProtocolGuard_v1.sv")
}

/** Stateless gates and published C-element rendezvous; no Boolean feedback synthesis. */
private[bundled] final class CompositionCells(owner: AsyncModule, delay: ModelTime) {
  require(delay.fs > 0, "composition requires positive cell delay (including feedback)")
  private val resetRef = owner.contract.endpoint("reset", owner.reset)
  private def packed(values: Seq[Bool]): UInt = Cat(values.reverse)

  def buffer(id: String, data: UInt, propagation: ModelTime): UInt = {
    val cell = Module(new ControlGate(data.getWidth, GateOperation.Buffer, propagation))
    cell.reset := owner.reset; cell.a := data; cell.b := 0.U
    owner.contract.primitive(id, cell, Map("WIDTH" -> BigInt(data.getWidth), "OP" -> BigInt(0),
      "DELAY_FS" -> BigInt(propagation.fs), "RESET_VALUE" -> BigInt(0)), resetRef,
      "inertial digital propagation; coordinated quiescent reset")
    cell.q
  }
  def and(id: String, inputs: Seq[Bool], invert: BigInt = 0): Bool = {
    val cell = Module(new AtomicAnd(inputs.size, delay, invert))
    cell.reset := owner.reset; cell.d := packed(inputs)
    owner.contract.primitive(id, cell, Map("INPUTS" -> BigInt(inputs.size), "DELAY_FS" -> BigInt(delay.fs),
      "INVERT" -> invert), resetRef, "atomic AND with input bubbles; stable selection during handshake")
    cell.q
  }
  def or(id: String, inputs: Seq[Bool]): Bool = {
    require(inputs.nonEmpty)
    inputs.tail.zipWithIndex.foldLeft(inputs.head) { case (a, (b, index)) =>
      val cell = Module(new ControlGate(1, GateOperation.Or, delay))
      cell.reset := owner.reset; cell.a := a.asUInt; cell.b := b.asUInt
      owner.contract.primitive(s"${id}_$index", cell, Map("WIDTH" -> BigInt(1), "OP" -> BigInt(2),
        "DELAY_FS" -> BigInt(delay.fs), "RESET_VALUE" -> BigInt(0)), resetRef,
        "OR of mutually exclusive handshakes; ideal wires")
      cell.q.asBool
    }
  }
  def c(id: String, inputs: Seq[Bool], sticky: Boolean = false, invert: BigInt = 0): Bool = {
    val common = if (sticky) 1 else inputs.size
    val rise = if (sticky) inputs.size else 0
    val cell = Module(new AsymmetricCElement(common, rise, 0, delay,
      commonInvert = if (sticky) 0 else invert, risingInvert = if (sticky) invert else 0))
    cell.reset := owner.reset
    cell.common := (if (sticky) 1.U else packed(inputs))
    cell.rising := (if (sticky) packed(inputs) else 1.U)
    cell.falling := 0.U
    owner.contract.primitive(id, cell, Map("COMMON" -> BigInt(common), "RISING" -> BigInt(rise),
      "FALLING" -> BigInt(0), "DELAY_FS" -> BigInt(delay.fs), "RESET_VALUE" -> BigInt(0),
      "COMMON_INVERT" -> (if (sticky) BigInt(0) else invert),
      "RISING_INVERT" -> (if (sticky) invert else BigInt(0)), "FALLING_INVERT" -> BigInt(0)), resetRef,
      if (sticky) "monotonic initialization state; reset clears; constant common input retains completion"
      else "C-element rendezvous; both phase completions; ideal forks")
    cell.q
  }
  def guard(id: String, requests: Seq[Bool], acknowledgements: Seq[Bool], valid: Bool, mode: Int): Unit = {
    val cell = Module(new ProtocolGuard(requests.size, mode))
    cell.reset := owner.reset; cell.request := packed(requests)
    cell.acknowledge := packed(acknowledgements); cell.valid := valid
    owner.contract.primitive(id, cell, Map("LANES" -> BigInt(requests.size), "MODE" -> BigInt(mode)),
      resetRef, "simulation-only assumption diagnostic; disabled only for mapping probes or synthesis")
  }
}
