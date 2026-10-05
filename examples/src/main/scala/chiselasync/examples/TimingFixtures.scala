// SPDX-License-Identifier: Apache-2.0
package chiselasync.examples

import chisel3._
import chiselasync.bundled.TimedCapture
import chiselasync.core.AsyncModule
import chiselasync.metadata.{DelayPolicy, ModelTime}
import chiselasync.primitives.{DelayLine, Latch}

class LatchExample extends AsyncModule {
  val enable = IO(Input(Bool()))
  val d = IO(Input(UInt(9.W)))
  val q = IO(Output(UInt(9.W)))
  private val cell = Module(new Latch(9, 0x12))
  cell.reset := reset
  cell.enable := enable
  cell.d := d
  q := cell.q
  contract.primitive("latch", cell, Map("WIDTH" -> BigInt(9), "RESET_VALUE" -> BigInt(0x12)),
    contract.endpoint("reset", reset), "transparent latch; reset to 18")
  contract.endpoint("enable", enable)
  contract.endpoint("data", d)
  contract.endpoint("q", q)
}

class DelayExample(policy: DelayPolicy) extends AsyncModule {
  val d = IO(Input(UInt(9.W)))
  val q = IO(Output(UInt(9.W)))
  private val cell = Module(new DelayLine(9, ModelTime.ps(10), policy))
  cell.reset := reset
  cell.d := d
  q := cell.q
  contract.primitive("delay", cell, Map("WIDTH" -> BigInt(9), "DELAY_FS" -> BigInt(10000),
    "POLICY" -> BigInt(policy.code)), contract.endpoint("reset", reset),
    s"${policy.name}; reset cancels pending deliveries")
  contract.endpoint("data", d)
  contract.endpoint("q", q)
}

class TimedExample(controlFs: Long) extends TimedCapture(UInt(8.W), ModelTime.ps(8),
  ModelTime(controlFs), ModelTime.ps(2), ModelTime.ps(2), (value: UInt) => value ^ 0x55.U(8.W))
