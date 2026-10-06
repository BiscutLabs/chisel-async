// SPDX-License-Identifier: Apache-2.0
package chiselasync.examples

import chisel3._
import chisel3.util._
import chiselasync.clocked.{AsyncMemoryPort, MemoryShape, MemoryRequest, MemoryResponse, PendingEventBridge}
import chiselasync.core.AsyncModule
import chiselasync.protocol.{Channel, FourPhase}
import chiselasync.metadata.ExportDesign
import java.nio.file.Paths

/** Small reference backends, not replacement memory primitives. Byte-addressed,
  * aligned 16-bit words, 16 entries. RAM contents persist across protocol reset;
  * reads of bytes never written are unspecified. ROM image is literal and fixed.
  */
abstract class MemoryBoundaryExample(rom: Boolean) extends AsyncModule {
  val clock = IO(Input(Clock()))
  val accept = IO(Input(Bool()))
  val latency = IO(Input(UInt(4.W)))
  private val shape = MemoryShape(6, 16)
  val request = IO(Flipped(new Channel(new MemoryRequest(shape), resetDomain).bundled))
  val response = IO(new Channel(new MemoryResponse(shape), resetDomain).bundled)
  private val port = asyncChild("port")(d => new AsyncMemoryPort(shape, domain = d))
  port.clock := clock
  FourPhase.connect(port.request, request)
  FourPhase.connect(response, port.response)
  withClockAndReset(clock, port.backendReset) {
    val busy = RegInit(false.B)
    val captureRead = RegInit(false.B)
    val remaining = RegInit(0.U(4.W))
    val data = RegInit(0.U(16.W))
    val error = RegInit(false.B)
    val req = port.backendRequest
    val resp = port.backendResponse
    req.ready := accept && !busy && !port.backendReset.asBool
    val badAddress = req.bits.address(0) || req.bits.address >= 32.U
    val bad = badAddress || (rom.B && req.bits.write)
    val writeCommit = req.fire && req.bits.write && !bad && req.bits.mask.orR
    val readEnable = req.fire && !req.bits.write && !bad
    val index = req.bits.address(4, 1)
    if (rom) {
      val image = VecInit((0 until 16).map(i => ((i * 0x1235 + 0x5a3c) & 0xffff).U(16.W)))
      when(req.fire) { data := Mux(bad || req.bits.write, 0.U, image(index)) }
    } else {
      val memory = SyncReadMem(16, Vec(2, UInt(8.W)))
      contract.synchronousMemory("ram", memory, 16, 2)
      val readData = memory.read(index, readEnable)
      when(writeCommit) { memory.write(index, req.bits.data.asTypeOf(Vec(2, UInt(8.W))), req.bits.mask.asBools) }
      when(req.fire) { data := 0.U }
      when(captureRead) { data := readData.asUInt }
    }
    captureRead := readEnable
    when(req.fire) { busy := true.B; error := bad; remaining := latency }
    when(busy && remaining =/= 0.U) { remaining := remaining - 1.U }
    resp.valid := busy && !captureRead && remaining === 0.U && !port.backendReset.asBool
    resp.bits.data := data
    resp.bits.error := error
    when(resp.fire) { busy := false.B }
  }
  contract.channel("request", request, "input")
  contract.channel("response", response, "output")
  contract.endpoint("reset", reset)
}
class MemoryRamExample extends MemoryBoundaryExample(false)
class MemoryRomExample extends MemoryBoundaryExample(true)
class PendingEventsExample extends PendingEventBridge(4)
object EmitBoundaries {
  def main(args: Array[String]): Unit = {
    require(args.length == 1)
    Seq[(String, () => AsyncModule)](
      "memory_ram" -> (() => new MemoryRamExample),
      "memory_rom" -> (() => new MemoryRomExample),
      "pending_events" -> (() => new PendingEventsExample),
      "memory_port" -> (() => new AsyncMemoryPort(MemoryShape(16, 32)))
    ).foreach { case (id, gen) => ExportDesign.emit(gen(), Paths.get(args(0), id)) }
  }
}
