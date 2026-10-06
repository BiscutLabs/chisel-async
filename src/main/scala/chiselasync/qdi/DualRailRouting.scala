// SPDX-License-Identifier: Apache-2.0
package chiselasync.qdi

import chisel3._
import chiselasync.bundled.{CompositionCells, Joined, Selected}
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.QdiTiming
import chiselasync.protocol.{Channel, DualRail}

/** No storage. Every branch receives the word and both acknowledgement phases
  * rendezvous. A completed branch is not undone by a subsequent domain reset.
  */
class DualRailFork[T <: Data](gen: T, val branches: Int, timing: QdiTiming,
    domain: ResetDomain = new ResetDomain("root")) extends AsyncModule(domain) {
  require(branches >= 2, "dual-rail fork requires at least two branches")
  val in = IO(Flipped(new Channel(gen, resetDomain).dualRail))
  val out = IO(Vec(branches, new Channel(gen, resetDomain).dualRail))
  private val cells = new CompositionCells(this, timing.cells.model)
  out.zipWithIndex.foreach { case (port, index) =>
    port.zero := cells.buffer(s"zero$index", in.zero.asUInt, timing.cells.model).asTypeOf(gen)
    port.one := cells.buffer(s"one$index", in.one.asUInt, timing.cells.model).asTypeOf(gen)
    contract.dualRailChannel(s"out$index", port, "output")
  }
  in.ack := cells.c("completion", out.map(_.ack).toSeq)
  contract.dualRailChannel("in", in, "input")
  contract.qdiTiming("qdi", Seq("in"), (0 until branches).map(i => s"out$i"), timing,
    "forwarding", "fork")
}

/** One pair held by a strongly indicating half-buffer. Inputs are rendezvous
  * operands, without independent input queues; neither acknowledges alone.
  */
class DualRailJoin[A <: Data, B <: Data](a: A, b: B, timing: QdiTiming,
    domain: ResetDomain = new ResetDomain("root")) extends AsyncModule(domain) {
  val left = IO(Flipped(new Channel(a, resetDomain).dualRail))
  val right = IO(Flipped(new Channel(b, resetDomain).dualRail))
  val out = IO(new Channel(new Joined(a, b), resetDomain).dualRail)
  private val storage = asyncChild("storage")(d => new DualRailStrongBuffer(new Joined(a, b), timing, d))
  storage.in.zero.left := left.zero; storage.in.zero.right := right.zero
  storage.in.one.left := left.one; storage.in.one.right := right.one
  left.ack := storage.in.ack; right.ack := storage.in.ack
  DualRail.connect(out, storage.out)
  contract.capacity(1)
  contract.dualRailChannel("left_input", left, "input")
  contract.dualRailChannel("right_input", right, "input")
  contract.dualRailChannel("out", out, "output")
  contract.endpoint("reset", reset)
  contract.qdiTiming("qdi", Seq("left_input", "right_input"), Seq("out"), timing, "strong", "join")
}

/** Two-way routing of a typed data word with a dual-rail selection bit.
  * Only the chosen output receives data. Full return precedes the next word.
  */
class DualRailDemux[T <: Data](gen: T, timing: QdiTiming,
    domain: ResetDomain = new ResetDomain("root")) extends AsyncModule(domain) {
  val in = IO(Flipped(new Channel(new Selected(gen, 2), resetDomain).dualRail))
  val out = IO(Vec(2, new Channel(gen, resetDomain).dualRail))
  private val cells = new CompositionCells(this, timing.cells.model)
  private val storage = asyncChild("storage")(d => new DualRailStrongBuffer(new Selected(gen, 2), timing, d))
  DualRail.connect(storage.in, in)
  out.zipWithIndex.foreach { case (port, index) =>
    val selected = if (index == 0) storage.out.zero.index.asBool else storage.out.one.index.asBool
    val zeros = (0 until gen.getWidth).map(bit =>
      cells.c(s"route${index}_zero$bit", Seq(storage.out.zero.data.asUInt(bit), selected)))
    val ones = (0 until gen.getWidth).map(bit =>
      cells.c(s"route${index}_one$bit", Seq(storage.out.one.data.asUInt(bit), selected)))
    port.zero := VecInit(zeros).asUInt.asTypeOf(gen)
    port.one := VecInit(ones).asUInt.asTypeOf(gen)
    contract.dualRailChannel(s"out$index", port, "output")
  }
  storage.out.ack := cells.or("completion", out.map(_.ack).toSeq)
  contract.capacity(1)
  contract.dualRailChannel("in", in, "input")
  contract.qdiTiming("qdi", Seq("in"), Seq("out0", "out1"), timing, "selected-strong", "demux")
}

/** No arbitration. Exactly one input may be outside idle, including partial
  * valid/spacer phases and acknowledgement return. Overlap is diagnosed.
  */
class DualRailMerge[T <: Data](gen: T, val inputs: Int, timing: QdiTiming,
    domain: ResetDomain = new ResetDomain("root")) extends AsyncModule(domain) {
  require(inputs >= 2, "exclusive dual-rail merge requires at least two inputs")
  val in = IO(Flipped(Vec(inputs, new Channel(gen, resetDomain).dualRail)))
  val out = IO(new Channel(gen, resetDomain).dualRail)
  private val cells = new CompositionCells(this, timing.cells.model)
  private val storage = asyncChild("storage")(d => new DualRailStrongBuffer(gen, timing, d))
  private val active = in.zipWithIndex.map { case (port, index) =>
    cells.or(s"input${index}_active", (0 until gen.getWidth).flatMap(bit =>
      Seq(port.zero.asUInt(bit), port.one.asUInt(bit))), "any input rail; exclusive serialized handshakes")
  }.toSeq
  storage.in.zero := VecInit((0 until gen.getWidth).map(bit =>
    cells.or(s"merge_zero$bit", in.map(_.zero.asUInt(bit)).toSeq))).asUInt.asTypeOf(gen)
  storage.in.one := VecInit((0 until gen.getWidth).map(bit =>
    cells.or(s"merge_one$bit", in.map(_.one.asUInt(bit)).toSeq))).asUInt.asTypeOf(gen)
  in.zipWithIndex.foreach { case (port, index) =>
    port.ack := cells.c(s"acknowledge$index", Seq(active(index), storage.in.ack))
    contract.dualRailChannel(s"in$index", port, "input")
  }
  cells.guard("rail_exclusivity", active, in.map(_.ack).toSeq, true.B, 0)
  DualRail.connect(out, storage.out)
  contract.capacity(1)
  contract.dualRailChannel("out", out, "output")
  contract.qdiTiming("qdi", (0 until inputs).map(i => s"in$i"), Seq("out"), timing,
    "selected-strong", "exclusive-merge")
}
