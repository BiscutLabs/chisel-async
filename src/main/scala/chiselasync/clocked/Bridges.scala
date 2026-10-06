// SPDX-License-Identifier: Apache-2.0
package chiselasync.clocked

import chisel3._
import chisel3.util._
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.protocol.Channel

/** Digital control synchronizers with explicit clock, asynchronous assertion and
  * local synchronous reset release. Physical metastability/placement/bus-delay bounds are external obligations.
  */
abstract class ClockedBridge(domain: ResetDomain, val syncStages: Int) extends AsyncModule(domain) {
  require(syncStages >= 2, "control synchronization requires at least two stages")
  val clock = IO(Input(Clock()))
  protected val localReset = withClockAndReset(clock, reset) {
    val release = RegInit(VecInit(Seq.fill(syncStages)(true.B)))
    release(0) := false.B
    for (i <- 1 until syncStages) release(i) := release(i-1)
    dontTouch(release)
    release.last.asAsyncReset
  }
  protected def synchronizedControl(input: Bool): Bool = withClockAndReset(clock, localReset) {
    val stages = RegInit(VecInit(Seq.fill(syncStages)(false.B)))
    stages(0) := input
    for (i <- 1 until syncStages) stages(i) := stages(i-1)
    dontTouch(stages)
    stages.last
  }
}

/** Snapshot Decoupled only on fire, then hold through the complete asynchronous handshake. */
class DecoupledToFourPhase[T <: Data](gen: T, stages: Int = 2,
    domain: ResetDomain = new ResetDomain("root")) extends ClockedBridge(domain, stages) {
  val channel = new Channel(gen, resetDomain)
  val in = IO(Flipped(channel.decoupled))
  val out = IO(channel.bundled)
  private val ack = synchronizedControl(out.ack)
  withClockAndReset(clock, localReset) {
    val state = RegInit(0.U(2.W))
    val data = RegInit(0.U.asTypeOf(gen))
    val request = RegInit(false.B)
    in.ready := state === 0.U && !localReset.asBool
    out.bits := data
    out.req := request
    switch(state) {
      is(0.U) { when(in.fire) { data := in.bits; state := 1.U } }
      is(1.U) { request := true.B; state := 2.U } // One full local cycle for data to settle.
      is(2.U) { when(ack) { request := false.B; state := 3.U } }
      is(3.U) { when(!ack) { state := 0.U } }
    }
  }
  contract.capacity(1)
  contract.clockedChannel("in", in, clock, channel, "input")
  contract.channel("out", out, "output")
  contract.endpoint("reset", reset)
}

/** Synchronize request, allow an extra settling cycle, then capture the held bus.
  * Input acknowledgement denotes downstream Decoupled fire, not speculative capture.
  */
class FourPhaseToDecoupled[T <: Data](gen: T, stages: Int = 2,
    domain: ResetDomain = new ResetDomain("root")) extends ClockedBridge(domain, stages) {
  val channel = new Channel(gen, resetDomain)
  val in = IO(Flipped(channel.bundled))
  val out = IO(channel.decoupled)
  private val request = synchronizedControl(in.req)
  withClockAndReset(clock, localReset) {
    val state = RegInit(0.U(2.W))
    val data = RegInit(0.U.asTypeOf(gen))
    val acknowledge = RegInit(false.B)
    in.ack := acknowledge
    out.bits := data
    out.valid := state === 2.U && !localReset.asBool
    switch(state) {
      is(0.U) { when(request) { state := 1.U } }
      is(1.U) { data := in.bits; state := 2.U }
      is(2.U) { when(out.fire) { acknowledge := true.B; state := 3.U } }
      is(3.U) { when(!request) { acknowledge := false.B; state := 0.U } }
    }
  }
  contract.capacity(1)
  contract.channel("in", in, "input")
  contract.clockedChannel("out", out, clock, channel, "output")
  contract.endpoint("reset", reset)
}
