// SPDX-License-Identifier: Apache-2.0
package chiselasync.bundled

import chisel3._
import chisel3.util.{log2Ceil, Mux1H}
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.{BundledTiming, ModelTime}
import chiselasync.protocol.{Channel, FourPhase, Payload}

/** Captured routing choice is part of the input transaction. */
class Selected[T <: Data](gen: T, val destinations: Int) extends Bundle {
  require(destinations >= 2, "select needs at least two destinations")
  val index = UInt(math.max(1, log2Ceil(destinations)).W)
  val data = gen.cloneType
}
class Joined[A <: Data, B <: Data](a: A, b: B) extends Bundle {
  val left = a.cloneType
  val right = b.cloneType
}
private[bundled] class Routed[T <: Data](gen: T, count: Int) extends Bundle {
  val route = UInt(count.W)
  val data = gen.cloneType
}

/** Unbuffered broadcast: both acknowledgement phases wait for every branch.
  * A branch may deliver before the input is acknowledged; reset cannot undo that delivery.
  */
class FourPhaseFork[T <: Data](gen: T, val branches: Int, cellDelay: ModelTime,
                               domain: ResetDomain = new ResetDomain("root")) extends AsyncModule(domain) {
  require(branches >= 2, "fork needs at least two branches")
  val channel = new Channel(gen, resetDomain)
  val in = IO(Flipped(channel.bundled))
  val out = IO(Vec(branches, channel.bundled))
  private val cells = new CompositionCells(this, cellDelay)
  out.zipWithIndex.foreach { case (port, i) =>
    port.bits := in.bits
    port.req := cells.buffer(s"request$i", in.req.asUInt, cellDelay).asBool
    contract.channel(s"out$i", port, "output")
  }
  in.ack := cells.c("completion", out.map(_.ack).toSeq)
  contract.channel("in", in, "input")
}

/** One stored operand per input; pairs nth left with nth right. */
class FourPhaseJoin[A <: Data, B <: Data](a: A, b: B, timing: BundledTiming, cellDelay: ModelTime,
                                         domain: ResetDomain = new ResetDomain("root")) extends AsyncModule(domain) {
  val left = IO(Flipped(new Channel(a, resetDomain).bundled))
  val right = IO(Flipped(new Channel(b, resetDomain).bundled))
  val out = IO(new Channel(new Joined(a, b), resetDomain).bundled)
  private val cells = new CompositionCells(this, cellDelay)
  private val l = asyncChild("left")(d => new LongHoldBuffer(a, timing, d))
  private val r = asyncChild("right")(d => new LongHoldBuffer(b, timing, d))
  FourPhase.connect(l.in, left); FourPhase.connect(r.in, right)
  out.bits.left := l.out.bits; out.bits.right := r.out.bits
  out.req := cells.c("rendezvous", Seq(l.out.req, r.out.req))
  l.out.ack := out.ack; r.out.ack := out.ack
  contract.channel("left_input", left, "input"); contract.channel("right_input", right, "input")
  contract.channel("out", out, "output")
  // Capacity of operands is declared on the two children, not conflated with tuple capacity.
}

/** One buffered transaction, routed using a one-hot choice captured with its data. */
class FourPhaseSelect[T <: Data](gen: T, val destinations: Int, timing: BundledTiming, cellDelay: ModelTime,
                                 domain: ResetDomain = new ResetDomain("root")) extends AsyncModule(domain) {
  val in = IO(Flipped(new Channel(new Selected(gen, destinations), resetDomain).bundled))
  val out = IO(Vec(destinations, new Channel(gen, resetDomain).bundled))
  private val cells = new CompositionCells(this, cellDelay)
  private val storage = asyncChild("storage")(d => new FourPhaseStage(new Selected(gen, destinations),
    new Routed(gen, destinations), (value: Selected[T]) => {
      val result = Wire(new Routed(gen, destinations))
      result.data := value.data
      result.route := VecInit((0 until destinations).map(i => value.index === i.U)).asUInt
      result
    }, timing, d))
  FourPhase.connect(storage.in, in)
  out.zipWithIndex.foreach { case (port, i) =>
    port.bits := storage.out.bits.data
    port.req := cells.and(s"route$i", Seq(storage.out.req, storage.out.bits.route(i)))
    contract.channel(s"out$i", port, "output")
  }
  storage.out.ack := cells.or("completion", out.map(_.ack).toSeq)
  cells.guard("index_guard", Seq(in.req), Seq(in.ack), in.bits.index < destinations.U, 1)
  contract.capacity(1); contract.channel("in", in, "input")
}

/** Buffered exclusive merge. The caller must serialize COMPLETE input handshakes.
  * There is no priority or arbitration; overlap is diagnosed by the simulation view.
  */
class FourPhaseMerge[T <: Data](gen: T, val inputs: Int, timing: BundledTiming, cellDelay: ModelTime,
                                domain: ResetDomain = new ResetDomain("root")) extends AsyncModule(domain) {
  require(inputs >= 2, "exclusive merge needs at least two inputs")
  val in = IO(Flipped(Vec(inputs, new Channel(gen, resetDomain).bundled)))
  val out = IO(new Channel(gen, resetDomain).bundled)
  private val cells = new CompositionCells(this, cellDelay)
  private val storage = asyncChild("storage")(d => new LongHoldBuffer(gen, timing, d))
  storage.in.req := cells.or("request", in.map(_.req).toSeq)
  // Request-controlled mux is inside the stage's declared source-to-capture data path.
  storage.in.bits := Mux1H(in.map(_.req), in.map(_.bits))
  // Include both mux selection and payload arrival in the downstream data budget.
  contract.endpoint("mux_sources", chisel3.util.Cat(in.reverse.map(p => chisel3.util.Cat(p.req, p.bits.asUInt))))
  private val muxResult = Wire(gen.cloneType)
  muxResult := storage.in.bits
  contract.endpoint("mux_result", muxResult)
  contract.dataPathTiming("merge_mux", "mux_sources", "mux_result", timing,
    "exclusive-merge-input-mux", Seq("storage"))
  in.zipWithIndex.foreach { case (port, i) =>
    port.ack := cells.c(s"acknowledge$i", Seq(port.req, storage.in.ack))
    contract.channel(s"in$i", port, "input")
  }
  FourPhase.connect(out, storage.out)
  cells.guard("exclusivity", in.map(_.req).toSeq, in.map(_.ack).toSeq, true.B, 0)
  contract.capacity(1); contract.channel("out", out, "output")
}

/** Literal tokens emitted in order once after each coordinated reset.
  * State advances on acknowledgement and then return, with positive digital delays.
  */
class InitialTokens[T <: Data](gen: T, val initial: Seq[T], timing: BundledTiming, cellDelay: ModelTime,
                               domain: ResetDomain = new ResetDomain("root")) extends AsyncModule(domain) {
  require(initial.nonEmpty, "initial token source must not be empty")
  require(timing.mode == "digital-model", "initial tokens require digital timing")
  initial.foreach { value =>
    Payload.requireSame(gen, value)
    require(value.litOption.nonEmpty, "initial tokens must be fully specified literals")
  }
  val out = IO(new Channel(gen, resetDomain).bundled)
  val done = IO(Output(Bool()))
  private val cells = new CompositionCells(this, cellDelay)
  private val starts = Wire(Vec(initial.size, Bool()))
  private val finished = Wire(Vec(initial.size, Bool()))
  private val active = Wire(Vec(initial.size, Bool()))
  starts(0) := true.B
  for (i <- initial.indices) {
    if (i > 0) starts(i) := finished(i - 1)
    val accepted = cells.c(s"accepted$i", Seq(active(i), out.ack), sticky = true)
    active(i) := cells.and(s"active$i", Seq(starts(i), accepted), invert = 2)
    finished(i) := cells.c(s"finished$i", Seq(accepted, out.ack), sticky = true, invert = 2)
  }
  private val data = Mux1H(initial.indices.map(i => starts(i) && !finished(i)), initial)
  out.bits := cells.buffer("data", data.asUInt, timing.dataDelay.model).asTypeOf(gen)
  out.req := cells.buffer("request_delay", cells.or("request", active.toSeq).asUInt, timing.matchedDelay).asBool
  done := finished.last
  contract.capacity(initial.size); contract.channel("out", out, "output"); contract.endpoint("done", done)
  contract.endpoint("mux_state", chisel3.util.Cat(reset.asBool, finished.asUInt))
  contract.dataPathTiming("initial_mux", "mux_state", "out_data", timing,
    "initial-token-literal-mux", delayCell = "data")
}

/** Exact-depth pipeline. Initial values are injected before any external acceptance.
  * Initialization occupies the declared capacity; reset aborts old work and reinstalls it.
  */
class FourPhaseFifo[T <: Data](gen: T, val depth: Int, timing: BundledTiming,
                               val initial: Seq[T] = Seq.empty, cellDelay: ModelTime = ModelTime.ps(1000),
                               domain: ResetDomain = new ResetDomain("root")) extends AsyncModule(domain) {
  require(depth >= 1, "FIFO depth must be positive")
  require(initial.size <= depth, "initial tokens exceed FIFO capacity")
  val in = IO(Flipped(new Channel(gen, resetDomain).bundled))
  val out = IO(new Channel(gen, resetDomain).bundled)
  private val head = if (initial.isEmpty) {
    contract.endpoint("reset", reset)
    val stage = asyncChild("stage0")(d => new LongHoldBuffer(gen, timing, d))
    FourPhase.connect(stage.in, in)
    stage.out
  } else {
    val cells = new CompositionCells(this, cellDelay)
    val source = asyncChild("initial")(d => new InitialTokens(gen, initial, timing, cellDelay, d))
    val merge = asyncChild("stage0")(d => new FourPhaseMerge(gen, 2, timing, cellDelay, d))
    FourPhase.connect(merge.in(0), source.out)
    merge.in(1).req := cells.and("external_admission", Seq(source.done, in.req))
    merge.in(1).bits := in.bits
    in.ack := merge.in(1).ack
    merge.out
  }
  private val tail = (1 until depth).foldLeft(head) { (previous, i) =>
    val stage = asyncChild(s"stage$i")(d => new LongHoldBuffer(gen, timing, d))
    FourPhase.connect(stage.in, previous)
    stage.out
  }
  FourPhase.connect(out, tail)
  contract.capacity(depth); contract.channel("in", in, "input"); contract.channel("out", out, "output")
}
