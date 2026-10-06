// SPDX-License-Identifier: Apache-2.0
package chiselasync.primitives

import chisel3._
import chiselasync.metadata.ModelTime

/** Atomic digital cell boundaries; physical mappings require separate constraints. */
object GateOperation extends Enumeration {
  val Buffer, Invert, Or = Value
}

class ControlGate(val width: Int, val operation: GateOperation.Value, val delay: ModelTime,
                  val resetValue: BigInt = 0) extends ExtModule(Map(
    "WIDTH" -> IntParam(width), "OP" -> IntParam(operation.id),
    "DELAY_FS" -> IntParam(delay.fs), "RESET_VALUE" -> IntParam(resetValue))) {
  require(width > 0 && resetValue >= 0 && resetValue.bitLength <= width, "invalid gate width/reset")
  override def desiredName: String = "ChiselAsyncControlGate_v1"
  val reset = IO(Input(AsyncReset()))
  val a = IO(Input(UInt(width.W)))
  val b = IO(Input(UInt(width.W)))
  val q = IO(Output(UInt(width.W)))
  addResource("/chiselasync/sv/ChiselAsyncControlGate_v1.sv")
}

/** Common inputs participate in both transitions; optional groups in one only.
  * Empty groups have a one-bit placeholder port, tied high (rise) or low (fall).
  * Direct n-ary semantics: this is not a tree of binary C-elements.
  */
class AsymmetricCElement(val commonInputs: Int, val risingInputs: Int, val fallingInputs: Int,
                         val delay: ModelTime, val resetValue: Int = 0,
                         val commonInvert: BigInt = 0, val risingInvert: BigInt = 0,
                         val fallingInvert: BigInt = 0) extends ExtModule(Map(
    "COMMON" -> IntParam(commonInputs), "RISING" -> IntParam(risingInputs),
    "FALLING" -> IntParam(fallingInputs), "DELAY_FS" -> IntParam(delay.fs),
    "RESET_VALUE" -> IntParam(resetValue), "COMMON_INVERT" -> IntParam(commonInvert),
    "RISING_INVERT" -> IntParam(risingInvert), "FALLING_INVERT" -> IntParam(fallingInvert))) {
  require(commonInputs > 0 && risingInputs >= 0 && fallingInputs >= 0, "invalid C-element input counts")
  require(resetValue == 0 || resetValue == 1, "invalid C-element reset value")
  Seq(commonInvert -> commonInputs, risingInvert -> risingInputs, fallingInvert -> fallingInputs).foreach {
    case (mask, width) => require(mask >= 0 && mask.bitLength <= width, "invalid C-element inversion mask")
  }
  override def desiredName: String = "ChiselAsyncAsymmetricC_v1"
  val reset = IO(Input(AsyncReset()))
  val common = IO(Input(UInt(commonInputs.W)))
  val rising = IO(Input(UInt(math.max(1, risingInputs).W)))
  val falling = IO(Input(UInt(math.max(1, fallingInputs).W)))
  val q = IO(Output(Bool()))
  addResource("/chiselasync/sv/ChiselAsyncAsymmetricC_v1.sv")
}

/** Transparent while closed=0. Internal capture has zero aperture in this model;
  * propagation to q is inertial. This is not a characterized physical latch.
  */
class ClosingLatch(val width: Int, val delay: ModelTime) extends ExtModule(Map(
    "WIDTH" -> IntParam(width), "DELAY_FS" -> IntParam(delay.fs))) {
  require(width > 0, "invalid closing-latch width")
  override def desiredName: String = "ChiselAsyncClosingLatch_v1"
  val reset = IO(Input(AsyncReset()))
  val closed = IO(Input(Bool()))
  val d = IO(Input(UInt(width.W)))
  val q = IO(Output(UInt(width.W)))
  addResource("/chiselasync/sv/ChiselAsyncClosingLatch_v1.sv")
}
