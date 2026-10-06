// SPDX-License-Identifier: Apache-2.0
package chiselasync.clocked

import chisel3._
import chisel3.util._
import chiselasync.core.ResetDomain
import chiselasync.protocol.{Channel, FourPhase}

/** Byte addresses and little-endian byte enables; no implicit resizing. */
final case class MemoryShape(addressBits: Int, dataBits: Int) {
  require(dataBits >= 8 && dataBits % 8 == 0 && isPow2(dataBits / 8),
    "memory words require a power-of-two number of bytes")
  val bytes: Int = dataBits / 8
  require(addressBits > log2Ceil(bytes), "address must include at least one word-index bit")
}
class MemoryRequest(val shape: MemoryShape) extends Bundle {
  val write = Bool()
  val address = UInt(shape.addressBits.W)
  val data = UInt(shape.dataBits.W)
  val mask = UInt(shape.bytes.W)
}
class MemoryResponse(val shape: MemoryShape) extends Bundle {
  val data = UInt(shape.dataBits.W)
  val error = Bool()
}

/** One outstanding transaction, through the response's complete return to idle.
  * Reuses the existing held-bus bridges. The backend runs on clock and backendReset.
  * Request ack means backendRequest.fire, not response delivery or write rollback.
  * Backend owns address/error/commit semantics; reset aborts transport, never undoes
  * a committed effect. There is no automatic retry after an ambiguous reset.
  */
class AsyncMemoryPort(val shape: MemoryShape, stages: Int = 2,
    domain: ResetDomain = new ResetDomain("root")) extends ClockedBridge(domain, stages) {
  private val requests = new Channel(new MemoryRequest(shape), resetDomain)
  private val responses = new Channel(new MemoryResponse(shape), resetDomain)
  val request = IO(Flipped(requests.bundled))
  val response = IO(responses.bundled)
  val backendRequest = IO(requests.decoupled)
  // ROM consumers may ignore write payload/mask; keep the declared backend ABI.
  dontTouch(backendRequest.bits)
  val backendResponse = IO(Flipped(responses.decoupled))
  val backendReset = IO(Output(AsyncReset()))
  backendReset := localReset
  private val receiver = asyncChild("requestBridge")(d => new FourPhaseToDecoupled(new MemoryRequest(shape), stages, d))
  private val sender = asyncChild("responseBridge")(d => new DecoupledToFourPhase(new MemoryResponse(shape), stages, d))
  receiver.clock := clock
  sender.clock := clock
  FourPhase.connect(receiver.in, request)
  FourPhase.connect(response, sender.out)
  withClockAndReset(clock, localReset) {
    val idle :: waiting :: returning :: Nil = Enum(3)
    val state = RegInit(idle)
    backendRequest.bits := receiver.out.bits
    backendRequest.valid := receiver.out.valid && state === idle && !localReset.asBool
    receiver.out.ready := backendRequest.ready && state === idle && !localReset.asBool
    sender.in.bits := backendResponse.bits
    sender.in.valid := backendResponse.valid && state === waiting && !localReset.asBool
    backendResponse.ready := sender.in.ready && state === waiting && !localReset.asBool
    when(backendRequest.fire) { state := waiting }
    when(backendResponse.fire) { state := returning }
    // sender.in.ready falls on response capture, and returns only after both
    // acknowledgement phases have traversed its synchronizer.
    when(state === returning && sender.in.ready) { state := idle }
  }
  contract.capacity(1)
  contract.channel("request", request, "input")
  contract.channel("response", response, "output")
  contract.clockedChannel("backendRequest", backendRequest, clock, requests, "output")
  contract.clockedChannel("backendResponse", backendResponse, clock, responses, "input")
  contract.endpoint("backend_reset", backendReset)
  contract.endpoint("reset", reset)
}
