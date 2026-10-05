// SPDX-License-Identifier: Apache-2.0
package chiselasync.bundled

import chisel3._
import chisel3.util.Cat
import chiselasync.core.AsyncModule
import chiselasync.metadata.{DelayPolicy, ModelTime}
import chiselasync.primitives.{DelayLine, Latch}
import chiselasync.protocol.Payload

/** Digital timing fixture: independent data/control delays feed a transparent latch.
  * One launch at a time; unique nonzero transaction IDs accompany the data, even for equal payloads.
  * This is an observable model, not a handshake controller or a physical delay guarantee.
  */
class TimedCapture[T <: Data](gen: T, dataDelay: ModelTime, controlDelay: ModelTime,
                             setup: ModelTime, hold: ModelTime, transform: T => T) extends AsyncModule {
  Payload.validateType(gen)
  val bits = IO(Input(gen))
  val transaction = IO(Input(UInt(32.W)))
  val launch = IO(Input(Bool()))
  val capture = IO(Output(Bool()))
  val dataValid = IO(Output(UInt((32 + gen.getWidth).W)))
  val captured = IO(Output(UInt((32 + gen.getWidth).W)))
  val out = IO(Output(gen))
  val transformed = transform(bits)
  Payload.requireSame(bits, transformed)
  private val data = Module(new DelayLine(32 + gen.getWidth, dataDelay))
  private val control = Module(new DelayLine(1, controlDelay))
  private val storage = Module(new Latch(32 + gen.getWidth))
  data.reset := reset
  control.reset := reset
  storage.reset := reset
  data.d := Cat(transaction, transformed.asUInt)
  control.d := launch.asUInt
  storage.enable := !control.q.asBool
  storage.d := data.q
  capture := control.q.asBool
  dataValid := data.q
  captured := storage.q
  out := storage.q(gen.getWidth - 1, 0).asTypeOf(gen)
  private val resetRef = contract.endpoint("reset", reset)
  contract.primitive("data_delay", data, Map("WIDTH" -> BigInt(32 + gen.getWidth),
    "DELAY_FS" -> BigInt(dataDelay.fs), "POLICY" -> BigInt(DelayPolicy.Transport.code)), resetRef,
    "transport captured values; reset cancels pending deliveries")
  contract.primitive("control_delay", control, Map("WIDTH" -> BigInt(1),
    "DELAY_FS" -> BigInt(controlDelay.fs), "POLICY" -> BigInt(DelayPolicy.Transport.code)), resetRef,
    "transport captured values; reset cancels pending deliveries")
  contract.primitive("latch", storage, Map("WIDTH" -> BigInt(32 + gen.getWidth), "RESET_VALUE" -> BigInt(0)),
    resetRef, "transparent while enable=1; reset clears captured value")
  contract.setupHold("capture_window", contract.endpoint("launch", launch),
    contract.endpoint("transaction", transaction), contract.endpoint("data_valid", dataValid),
    contract.endpoint("capture", capture), contract.endpoint("captured", captured), setup, hold)
}
