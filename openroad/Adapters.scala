// SPDX-License-Identifier: Apache-2.0
package chiselasync.openroad

import chiselasync.metadata.AsicMapping
import scala.collection.mutable.ArrayBuffer

/** Structural standard-cell adapters for every primitive specialization a design
  * needs, and where each logical port lands on a real cell pin.
  *
  * These are trial adapters for a demonstration flow, built from library gates:
  * a C-element is input bubbles and set/hold decode feeding one state gate with
  * feedback, not a characterized atomic cell. `AsicMapping` records them as
  * `mapped-unqualified`, which is what they are.
  */
object Adapters {
  /** Cell pins for one logical port, one entry per bit. `path` pins are where a
    * propagation path starts (inputs) or ends (outputs); `arc` pins are the state
    * cell's own pins, for checks that read a single characterized arc.
    */
  final case class PortPins(path: Seq[String], arc: Seq[String])
  final case class Adapter(module: String, verilog: String, ports: Map[String, PortPins])

  private final class Netlist(tech: Technology) {
    val lines = ArrayBuffer.empty[String]
    private var n = 0
    private def fresh(prefix: String): String = { n += 1; s"$prefix$n" }
    def wire(): String = { val w = fresh("n"); lines += s"  wire $w;"; w }
    def cell(c: Technology.Cell, ins: Seq[String], out: Option[String] = None): (String, String) = {
      require(ins.size == c.ins.size, s"${c.module}: ${ins.size} inputs for ${c.ins.size} pins")
      val inst = fresh("g")
      val y = out.getOrElse(wire())
      val pins = (c.ins.zip(ins) :+ (c.out -> y)).map { case (p, net) => s".$p($net)" }.mkString(", ")
      lines += s"""  (* keep = 1, dont_touch = 1 *) ${c.module} $inst ($pins);"""
      (inst, y)
    }
    def latch(l: Technology.Latch, d: String, enable: String, resetN: Option[String], q: String): String = {
      val inst = fresh("g")
      val pins = Seq(l.d -> d, l.enable -> enable, l.q -> q) ++ l.resetN.zip(resetN)
      lines += s"""  (* keep = 1, dont_touch = 1 *) ${l.module} $inst (${pins.map { case (p, s) => s".$p($s)" }.mkString(", ")});"""
      inst
    }
  }

  /** @param role the primitive's id in its parent, e.g. `request_delay`
    * @param cellMaxFs a control-gate delay above this is a matched delay line;
    *   at or below it the gate is one cell
    * @param dataMaxFs a control gate of exactly this delay (or a `data_delay`)
    *   is a data allowance modelling the transform path; it maps to reset gating
    *   only, so the real mapped logic is the delay
    */
  def generate(required: AsicMapping.RequiredCell, role: String, module: String, tech: Technology,
      cellMaxFs: Long, dataMaxFs: Long): Adapter = {
    val k = required.key
    def p(name: String): Int = k.parameters(name).toInt
    def bit(mask: BigInt, i: Int): Boolean = mask.testBit(i)
    val nl = new Netlist(tech)
    val ports = scala.collection.mutable.LinkedHashMap.empty[String, PortPins]
    val width = required.ports.map(q => q.name -> q.width).toMap
    def pin(inst: String, name: String) = s"$inst/$name"
    // Reset is ordinary logic: synthesis and the resizer may buffer and share it.
    val rn = "rn"
    nl.lines += "  wire rn = ~reset[0];"
    def and2(a: String, b: String) = nl.cell(tech.and2, Seq(a, b))
    def or2(a: String, b: String) = nl.cell(tech.or2, Seq(a, b))
    // A balanced tree; returns the output net, the root cell's output pin
    // (empty for a single leaf) and, per leaf, the pin it enters.
    def tree(gate: (String, String) => (String, String), c: Technology.Cell, leaves: Seq[String]): (String, String, Seq[String]) = {
      if (leaves.size == 1) (leaves.head, "", Seq(""))
      else {
        val (l, r) = leaves.splitAt(leaves.size / 2)
        val (ln, _, lp) = tree(gate, c, l); val (rnet, _, rp) = tree(gate, c, r)
        val (inst, y) = gate(ln, rnet)
        (y, pin(inst, c.out), lp.map(x => if (x.isEmpty) pin(inst, c.ins(0)) else x) ++
          rp.map(x => if (x.isEmpty) pin(inst, c.ins(1)) else x))
      }
    }

    k.model match {
      case "ChiselAsyncControlGate_v1" =>
        require(p("RESET_VALUE") == 0, s"$module: nonzero RESET_VALUE")
        val w = p("WIDTH"); val delay = k.parameters("DELAY_FS")
        p("OP") match {
          case 0 =>
            // A data allowance models the transform logic before it: the mapped
            // logic is the delay, so the allowance is reset gating only.
            val allowance = role == "data_delay" || delay == dataMaxFs
            val line = !allowance && delay > cellMaxFs
            val stages = if (line) ((delay + tech.delayStageFs - 1) / tech.delayStageFs).toInt else 0
            val (as, qs) = (0 until w).map { i =>
              val (g, y0) = and2(s"a[$i]", rn)
              val y = (0 until stages).foldLeft((g, y0)) { case ((_, x), s) =>
                nl.cell(tech.delay, Seq(x), if (s == stages - 1) Some(s"q[$i]") else None)
              }
              if (stages == 0) nl.lines += s"  assign q[$i] = $y0;"
              (pin(g, tech.and2.ins(0)), pin(y._1, if (stages == 0) tech.and2.out else tech.delay.out))
            }.unzip
            ports("a") = PortPins(as, as); ports("q") = PortPins(qs, qs)
            ports("b") = PortPins(Seq.fill(w)(""), Seq.fill(w)(""))
          case 2 =>
            val (as, bs, qs) = (0 until w).map { i =>
              val (o, y) = or2(s"a[$i]", s"b[$i]")
              val (g, _) = nl.cell(tech.and2, Seq(y, rn), Some(s"q[$i]"))
              (pin(o, tech.or2.ins(0)), pin(o, tech.or2.ins(1)), pin(g, tech.and2.out))
            }.unzip3
            ports("a") = PortPins(as, as); ports("b") = PortPins(bs, bs); ports("q") = PortPins(qs, qs)
          case op => throw new IllegalArgumentException(s"$module: unsupported OP $op")
        }

      case "ChiselAsyncAnd_v1" =>
        val n = p("INPUTS"); val inv = k.parameters("INVERT")
        val (ds, entry) = (0 until n).map { i =>
          if (bit(inv, i)) { val (g, y) = nl.cell(tech.inv, Seq(s"d[$i]")); (y, Some(pin(g, tech.inv.ins(0)))) }
          else (s"d[$i]", None)
        }.unzip
        val (y, root, leafPins) = tree(and2, tech.and2, ds :+ rn)
        nl.lines += s"  assign q[0] = $y;"
        val dPins = entry.zip(leafPins).map { case (e, l) => e.getOrElse(l) }
        ports("d") = PortPins(dPins, dPins)
        ports("q") = PortPins(Seq(root), Seq(root))

      case "ChiselAsyncAsymmetricC_v1" =>
        require(p("RESET_VALUE") == 0, s"$module: nonzero RESET_VALUE")
        def inputs(port: String, count: Int, mask: BigInt): Seq[(String, Option[String])] = (0 until count).map { i =>
          if (bit(mask, i)) { val (g, y) = nl.cell(tech.inv, Seq(s"$port[$i]")); (y, Some(pin(g, tech.inv.ins(0)))) }
          else (s"$port[$i]", None)
        }
        val c = inputs("common", p("COMMON"), k.parameters("COMMON_INVERT"))
        val r = inputs("rising", p("RISING"), k.parameters("RISING_INVERT"))
        val f = inputs("falling", p("FALLING"), k.parameters("FALLING_INVERT"))
        // Rise when every common and rising input is 1; fall when every common
        // and falling input is 0; otherwise hold: q = S | q & H, gated by reset.
        val (s, _, sPins) = tree(and2, tech.and2, (c ++ r).map(_._1) :+ rn)
        val (h0, _, hPins) = tree(or2, tech.or2, (c ++ f).map(_._1))
        val (_, h) = and2(h0, rn)
        val g = tech.stateGate
        val q = if (tech.stateGateInverting) "qn" else "q[0]"
        if (tech.stateGateInverting) nl.lines += "  wire qn;"
        val (state, _) = nl.cell(g, Seq("q[0]", h, s), Some(q))
        val out = if (tech.stateGateInverting) nl.cell(tech.inv, Seq("qn"), Some("q[0]"))._1 else state
        val outPin = if (tech.stateGateInverting) tech.inv.out else g.out
        def entry(xs: Seq[(String, Option[String])], tree: Seq[String]) = xs.zip(tree).map { case ((_, e), t) => e.getOrElse(t) }
        val sEntry = entry(c ++ r, sPins)
        ports("common") = PortPins(sEntry.take(c.size), Seq.fill(c.size)(pin(state, g.ins(2))))
        ports("rising") = PortPins(if (r.isEmpty) Seq("") else sEntry.drop(c.size),
          Seq.fill(math.max(1, r.size))(if (r.isEmpty) "" else pin(state, g.ins(2))))
        ports("falling") = PortPins(if (f.isEmpty) Seq("") else entry(c ++ f, hPins).drop(c.size),
          Seq.fill(math.max(1, f.size))(if (f.isEmpty) "" else pin(state, g.ins(1))))
        ports("q") = PortPins(Seq(pin(out, outPin)), Seq(pin(state, g.out)))

      case "ChiselAsyncClosingLatch_v1" =>
        val w = p("WIDTH"); val l = tech.latch
        // Transparent while `closed` is 0; reset clears every bit.
        val (enInst, enable) = (l.openLow, l.resetN) match {
          case (true, None) => val (g, y) = and2("closed", rn); (pin(g, tech.and2.ins(0)), y)
          case (false, Some(_)) => val (g, y) = nl.cell(tech.inv, Seq("closed")); (pin(g, tech.inv.ins(0)), y)
          case other => throw new IllegalArgumentException(s"${tech.name}: unsupported latch shape $other")
        }
        val (ds, qs) = (0 until w).map { i =>
          val (dIn, dPin) = l.resetN match {
            case None => val (g, y) = and2(s"d[$i]", rn); (y, pin(g, tech.and2.ins(0)))
            case Some(_) => (s"d[$i]", "")
          }
          val inst = nl.latch(l, dIn, enable, l.resetN.map(_ => rn), s"q[$i]")
          (if (dPin.isEmpty) pin(inst, l.d) else dPin, pin(inst, l.d), pin(inst, l.q))
        }.map { case (path, arc, q) => ((path, arc), q) }.unzip
        ports("d") = PortPins(ds.map(_._1), ds.map(_._2)); ports("q") = PortPins(qs, qs)
        ports("closed") = PortPins(Seq(enInst), Seq(enInst))

      case other => throw new IllegalArgumentException(s"$module: no ${tech.name} adapter for $other")
    }

    val header = required.ports.map { q =>
      s"  ${q.direction} wire [${q.width - 1}:0] ${q.name}"
    }.mkString(",\n")
    val verilog = s"// ${tech.name} trial adapter for ${k.model} ${k.parameters.toSeq.sortBy(_._1).map { case (a, b) => s"$a=$b" }.mkString(" ")}\n" +
      s"module $module (\n$header\n);\n${nl.lines.mkString("\n")}\nendmodule\n"
    ports.keys.foreach(name => require(width.contains(name), s"$module: unknown port $name"))
    Adapter(module, verilog, ports.toMap)
  }
}
