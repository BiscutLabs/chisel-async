// SPDX-License-Identifier: Apache-2.0
package chiselasync.clocked

import chisel3._
import chisel3.util._
import chiselasync.core.ResetDomain
import chiselasync.protocol.Channel

/** Receive a held four-phase payload without an intermediate payload register.
  *
  * Only valid-qualified consumer logic may use `out.bits`. The consumer must
  * capture on this receipt's actual clock edge; a gated consumer requires ready
  * qualified by its effective clock enable. `maskInvalid` drives typed zero while
  * invalid, but does not make invalid cycles transactions or replace qualification.
  *
  * After the synchronized request is detected, wait `settlingCycles` additional
  * edges before presenting valid. Acceptance requires a subsequent clock edge.
  * The source holds data through complete return to zero; physical setup/hold at
  * the consumer (including mask and ACK paths) still requires qualification.
  *
  * Use POR-only transport or coordinated reset of the entire connected domain.
  * There is no independent application-reset close/rebase protocol. Fanout needs
  * a native join of every sink's ACK outside this receipt.
  */
class FourPhaseCaptureReceipt[T <: Data](gen: T, stages: Int = 2,
    val settlingCycles: Int = 1, val maskInvalid: Boolean = false,
    domain: ResetDomain = new ResetDomain("root")) extends ClockedBridge(domain, stages) {
  require(settlingCycles >= 0, "settling cycles must be nonnegative")
  // Preserve the independent reset source used by strict endpoint mapping.
  dontTouch(localReset)
  val channel = new Channel(gen, resetDomain)
  val in = IO(Flipped(channel.bundled))
  val out = IO(channel.decoupled)
  private val request = synchronizedControl(in.req)
  withClockAndReset(clock, localReset) {
    val state = RegInit(0.U(2.W))
    val acknowledge = RegInit(false.B)
    // The common settings 0 and 1 need no counter beyond the state machine.
    val remaining = if (settlingCycles > 1)
      Some(RegInit(0.U(log2Ceil(settlingCycles).W))) else None
    in.ack := acknowledge
    out.valid := state === 2.U && !localReset.asBool
    out.bits := (if (maskInvalid) Mux(out.valid, in.bits, 0.U.asTypeOf(gen)) else in.bits)
    switch(state) {
      is(0.U) {
        when(request) {
          state := (if (settlingCycles == 0) 2.U else 1.U)
          remaining.foreach(_ := (settlingCycles - 1).U)
        }
      }
      is(1.U) {
        remaining match {
          case Some(count) => when(count === 0.U) { state := 2.U }.otherwise { count := count - 1.U }
          case None => state := 2.U
        }
      }
      is(2.U) { when(out.fire) { acknowledge := true.B; state := 3.U } }
      is(3.U) { when(!request) { acknowledge := false.B; state := 0.U } }
    }
    contract.endpoint("state", state)
    contract.endpoint("acknowledge", acknowledge)
    remaining.foreach(count => contract.endpoint("settling_remaining", count))
  }
  contract.capacity(1)
  contract.channel("in", in, "input")
  contract.clockedChannel("out", out, clock, channel, "output")
  contract.endpoint("request_sync", request)
  contract.endpoint("local_reset", localReset)
  contract.endpoint("reset", reset)
}

/** Native two-phase counterpart of [[FourPhaseCaptureReceipt]].
  *
  * Both request polarities deliver; ACK records the accepted request parity.
  * There is no return-to-zero conversion. The source holds payload until the
  * aggregate ACK and must also meet the consumer's post-capture hold time before
  * reuse. Synchronizer depth/settling cycles provide no post-ACK hold guarantee.
  * The valid, clock, fanout and coordinated-reset rules of the four-phase receipt
  * also apply here.
  */
class ClickCaptureReceipt[T <: Data](gen: T, stages: Int = 2,
    val settlingCycles: Int = 1, val maskInvalid: Boolean = false,
    domain: ResetDomain = new ResetDomain("root")) extends ClockedBridge(domain, stages) {
  require(settlingCycles >= 0, "settling cycles must be nonnegative")
  dontTouch(localReset)
  val channel = new Channel(gen, resetDomain)
  val in = IO(Flipped(channel.twoPhase))
  val out = IO(channel.decoupled)
  private val request = synchronizedControl(in.req)
  withClockAndReset(clock, localReset) {
    val state = RegInit(0.U(2.W))
    val acknowledge = RegInit(false.B)
    val remaining = if (settlingCycles > 1)
      Some(RegInit(0.U(log2Ceil(settlingCycles).W))) else None
    in.ack := acknowledge
    out.valid := state === 2.U && !localReset.asBool
    out.bits := (if (maskInvalid) Mux(out.valid, in.bits, 0.U.asTypeOf(gen)) else in.bits)
    switch(state) {
      is(0.U) {
        when(request =/= acknowledge) {
          state := (if (settlingCycles == 0) 2.U else 1.U)
          remaining.foreach(_ := (settlingCycles - 1).U)
        }
      }
      is(1.U) {
        remaining match {
          case Some(count) => when(count === 0.U) { state := 2.U }.otherwise { count := count - 1.U }
          case None => state := 2.U
        }
      }
      is(2.U) { when(out.fire) { acknowledge := request; state := 0.U } }
    }
    contract.endpoint("state", state)
    contract.endpoint("acknowledge", acknowledge)
    remaining.foreach(count => contract.endpoint("settling_remaining", count))
  }
  contract.capacity(1)
  contract.twoPhaseChannel("in", in, "input")
  contract.clockedChannel("out", out, clock, channel, "output")
  contract.endpoint("request_sync", request)
  contract.endpoint("local_reset", localReset)
  contract.endpoint("reset", reset)
}
