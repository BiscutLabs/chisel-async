// SPDX-License-Identifier: Apache-2.0
package chiselasync.bundled

import chisel3._
import chisel3.util.{Cat, Mux1H, log2Ceil}
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.{BundledTiming, ModelTime}
import chiselasync.protocol.{Channel, FourPhase}

/** Controlled multiplexer: each selector token chooses exactly one data input.
  * Other inputs may remain offered; they are never acknowledged speculatively.
  * One selector slot and one output data slot. Selector acceptance may precede data.
  * Rendezvous C-elements retain the selected request until both source requests
  * return, preventing a fast producer from reusing an old selector.
  *
  * Use this component for explicit scheduling, including feedback loops. Use
  * [[FourPhaseArbiter]] when competing producers must choose a winner dynamically.
  * Reset discards the buffered selector and undelivered data.
  *
  * @param gen exact payload type shared by all data inputs and the output
  * @param inputs number of data inputs, at least two; `select.bits` is a zero-based
  *   index with width `log2Ceil(inputs)` and must be less than `inputs`
  * @param timing digital envelope for selector/data storage; its data budget must
  *   include the one-hot decoder and input multiplexer paths in their respective stages
  * @param cellDelay nominal propagation delay for rendezvous and routing cells
  * @param domain coordinated reset identity; create children with `asyncChild`
  */
class FourPhaseMux[T <: Data](gen: T, val inputs: Int, timing: BundledTiming, cellDelay: ModelTime,
    domain: ResetDomain = new ResetDomain("root")) extends AsyncModule(domain) {
  require(inputs >= 2, "multiplexer needs at least two inputs")
  private val indexType = UInt(log2Ceil(inputs).W)
  val in = IO(Flipped(Vec(inputs, new Channel(gen, resetDomain).bundled)))
  val select = IO(Flipped(new Channel(indexType, resetDomain).bundled))
  val out = IO(new Channel(gen, resetDomain).bundled)
  private val cells = new CompositionCells(this, cellDelay)
  private val choice = asyncChild("choice")(d => new FourPhaseStage(indexType, UInt(inputs.W),
    (index: UInt) => VecInit((0 until inputs).map(i => index === i.U)).asUInt, timing, d))
  private val storage = asyncChild("storage")(d => new LongHoldBuffer(gen, timing, d))
  FourPhase.connect(choice.in, select)
  private val requests = in.zipWithIndex.map { case (port, i) =>
    val selected = cells.and(s"selected$i", Seq(choice.out.req, choice.out.bits(i)))
    val request = cells.c(s"rendezvous$i", Seq(selected, port.req))
    port.ack := cells.c(s"acknowledge$i", Seq(request, storage.in.ack))
    contract.channel(s"in$i", port, "input")
    request
  }.toSeq
  storage.in.req := cells.or("request", requests)
  // The captured one-hot selector is held through the rendezvous return. Data
  // selection needs no extra request/ack gating; only the request path admits it.
  storage.in.bits := Mux1H(choice.out.bits.asBools, in.map(_.bits))
  choice.out.ack := cells.or("selection_completion", in.map(_.ack).toSeq)
  FourPhase.connect(out, storage.out)
  cells.guard("index_guard", Seq(select.req), Seq(select.ack), select.bits < inputs.U, 1)
  contract.endpoint("mux_sources", Cat(choice.out.bits, Cat(in.reverse.map(_.bits.asUInt))))
  private val muxResult = Wire(gen.cloneType)
  muxResult := storage.in.bits
  contract.endpoint("mux_result", muxResult)
  contract.dataPathTiming("mux_path", "mux_sources", "mux_result", timing,
    "controlled-multiplexer-input-mux", Seq("storage"))
  contract.channel("select", select, "input"); contract.channel("out", out, "output")
  // Child contracts declare the distinct selector and data capacities.
}
