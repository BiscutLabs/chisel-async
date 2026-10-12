// SPDX-License-Identifier: Apache-2.0
package chiselasync.openroad

import chiselasync.metadata.{OpenSta, TimingConstraints}
import chiselasync.metadata.TimingConstraints.ObjectRef
import java.nio.file.{Files, Path, Paths}

/** Check a routed design against the library's own timing contract.
  *
  * Usage: Signoff EXPORT FLAT_JSON NETLIST SPEF SETUP_TCL STA OUTPUT CORNER LIBERTY...
  *
  * EXPORT is the directory Export wrote, FLAT_JSON the mapped RTL flattened by
  * yosys before synthesis, NETLIST and SPEF the routed design. Every endpoint of
  * the contract is bound to one exact pin or port of the routed netlist:
  *
  *  - a primitive's port to the adapter cell pin pins.json names for it, the
  *    state cell's own pin where the contract reads a characterized arc;
  *  - a channel endpoint (a probe, named in the compiler's ref_<top>.sv read-probe
  *    ABI and gone after synthesis) to what drives it
  *    where the contract starts a path there, and to the adapter pin it feeds
  *    where a path ends there, both found in FLAT_JSON. A start driven by
  *    synthesized logic moves to the net's one load if that is an adapter pin,
  *    and an end loaded only by synthesized logic moves to the net's driver. Adapter cells are kept
  *    and dont_touch, so the same instance names exist after routing.
  *
  * Then `TimingConstraints.emit` and `OpenSta.check`, unchanged, at one corner.
  */
object Signoff {
  private final case class Net(bits: Seq[ujson.Value])

  def main(args: Array[String]): Unit = {
    require(args.length >= 9, "Usage: Signoff EXPORT FLAT_JSON NETLIST SPEF SETUP_TCL STA OUTPUT CORNER LIBERTY...")
    val Array(export, flatJson, netlist, spef, setup, sta, output, corner) = args.take(8).map(identity)
    val liberty = args.drop(8).map(Paths.get(_)).toSeq
    val base = Paths.get(export)
    val intent = base.resolve("asic/timing-intent.json")
    val plan = TimingConstraints.prepare(intent)
    val manifest = ujson.read(Files.readString(intent))("manifest")
    val top = manifest("top").str
    val pins = ujson.read(Files.readString(base.resolve("pins.json"))).obj
    val flat = ujson.read(Files.readString(Paths.get(flatJson)))("modules")(top)
    val routed = Files.readString(Paths.get(netlist))

    // Contract paths: endpoint key -> probe rtl_path, primitive key -> rtl_path.
    val probes = scala.collection.mutable.Map.empty[String, String]
    val cells = scala.collection.mutable.Map.empty[String, String]
    def visit(node: ujson.Value, prefix: String): Unit = {
      node("endpoints").arr.foreach(e => probes(prefix + e("id").str) = e("probe").str)
      node("primitives").arr.foreach(p => cells(prefix + p("id").str) = p("rtl_path").str)
      node("children").arr.foreach(c => visit(c("contract"), prefix + c("id").str + "."))
    }
    visit(manifest("design"), "")
    def local(rtlPath: String): String = rtlPath.stripPrefix(top + ".")
    // The compiler's read-probe ABI names the RTL signal behind every probe.
    val define = ("`define ref_" + top + "_(\\S+) (\\S+)").r
    val signals = scala.io.Source.fromFile(base.resolve(s"simulation/ref_$top.sv").toFile).getLines()
      .flatMap(l => define.findFirstMatchIn(l).map(m => m.group(1) -> m.group(2))).toMap

    // How the contract uses each endpoint.
    val arcs = plan.rules.filter(_.measure == "arc").flatMap(r => Seq(r.from, r.to)).toSet
    val sources = plan.rules.filter(_.measure != "arc").map(_.from).toSet
    val sinks = plan.rules.filter(_.measure != "arc").map(_.to).toSet

    // Flattened mapped RTL: cell connectivity by bit, and the top-level ports.
    val flatCells = flat("cells").obj.toSeq
    val portBits = flat("ports").obj.toSeq.flatMap { case (name, p) =>
      val bits = p("bits").arr.toSeq
      bits.zipWithIndex.map { case (b, i) => b.toString -> (if (bits.size == 1) name else s"$name[$i]", p("direction").str) }
    }.toMap
    // Continuous assignments survive flattening as $buf cells: a bit and every bit
    // joined to it through $buf cells are one electrical net.
    val bufs = flatCells.collect { case (_, c) if c("type").str == "$buf" =>
      c("connections")("A").arr.toSeq.zip(c("connections")("Y").arr.toSeq)
    }.flatten
    def through(bit: ujson.Value, direction: String): Seq[ujson.Value] = {
      var net = Set(bit); var grown = true
      while (grown) {
        val next = net ++ bufs.collect { case (a, y) if net(a) || net(y) => Seq(a, y) }.flatten
        grown = next.size > net.size; net = next
      }
      net.toSeq
    }
    def connected(bit: ujson.Value, direction: String): Seq[String] =
      through(bit, direction).flatMap(direct(_, direction)).distinct
    def direct(bit: ujson.Value, direction: String): Seq[String] = flatCells.filter(_._2("type").str != "$buf").flatMap { case (inst, c) =>
      c("connections").obj.toSeq.flatMap { case (port, bits) =>
        bits.arr.zipWithIndex.collect { case (b, i) if b == bit && c("port_directions")(port).str == direction =>
          if (bits.arr.size == 1) s"$inst/$port" else s"$inst/$port[$i]"
        }
      }
    }
    def preserved(pin: String): Boolean = pin.contains(".mapped.")
    def instance(prefix: String, cell: String): String = {
      val pattern = (java.util.regex.Pattern.quote(prefix) + "\\.variant_[0-9]+\\.mapped\\." + java.util.regex.Pattern.quote(cell)).r
      val found = flatCells.map(_._1).filter(n => pattern.matches(n))
      require(found.size == 1, s"ADAPTER_CELL_UNRESOLVED: $prefix ... $cell (${found.size} matches)")
      found.head
    }

    val bindings: Map[String, Seq[ObjectRef]] = plan.required.map { e =>
      val refs: Seq[ObjectRef] = if (e.description != "channel/internal endpoint") {
        // cell.port of a primitive: key is <prefix><cell>.<port>.
        val cellKey = e.id.substring(0, e.id.lastIndexOf('.'))
        val port = e.id.substring(e.id.lastIndexOf('.') + 1)
        val rtl = cells.getOrElse(cellKey, throw new IllegalArgumentException(s"PRIMITIVE_UNKNOWN: ${e.id}"))
        val entry = pins.getOrElse(rtl, throw new IllegalArgumentException(s"NO_ADAPTER_PINS: $rtl"))(port)
        require(!(arcs(e.id) && (sources(e.id) || sinks(e.id))), s"ENDPOINT_USED_AS_ARC_AND_PATH: ${e.id}")
        val chosen = entry(if (arcs(e.id)) "arc" else "path").arr.map(_.str).toSeq
        require(chosen.forall(_.nonEmpty), s"ADAPTER_PIN_MISSING: ${e.id}")
        chosen.map { p =>
          val Array(cell, pin) = p.split('/')
          ObjectRef("pin", s"${instance(local(rtl), cell)}/$pin")
        }
      } else {
        val probe = probes.getOrElse(e.id, throw new IllegalArgumentException(s"PROBE_UNKNOWN: ${e.id}"))
        val signal = signals.getOrElse(probe, throw new IllegalArgumentException(s"PROBE_NOT_IN_REF_ABI: $probe"))
        val net = flat("netnames").obj.getOrElse(signal, throw new IllegalArgumentException(s"PROBE_NET_MISSING: $signal"))
        require(!(sources(e.id) && sinks(e.id)), s"ENDPOINT_IS_SOURCE_AND_SINK: ${e.id}")
        net("bits").arr.toSeq.map { bit =>
          val ends = through(bit, if (sources(e.id)) "output" else "input")
          ends.flatMap(b => portBits.get(b.toString)).headOption match {
            case Some((name, "input")) if sources(e.id) => ObjectRef("port", name)
            case Some((name, "output")) if sinks(e.id) => ObjectRef("port", name)
            case _ if sources(e.id) && !connected(bit, "output").exists(preserved) =>
              // Driven by synthesized logic, whose names do not survive. If the
              // net feeds nothing but one preserved cell, the path starts there:
              // only the wire is left out, never logic.
              val loads = connected(bit, "input")
              require(loads.size == 1 && loads.forall(preserved),
                s"CHANNEL_ENDPOINT_UNBOUND: ${e.id} bit $bit: synthesized driver, loads ${loads.mkString(" ")}")
              ObjectRef("pin", loads.head)
            case _ if sinks(e.id) && !connected(bit, "input").exists(preserved) =>
              // Loaded only by synthesized logic: the path ends where the net
              // starts, at its driver, if that is an adapter pin.
              val drivers = connected(bit, "output")
              require(drivers.size == 1 && drivers.forall(preserved),
                s"CHANNEL_ENDPOINT_UNBOUND: ${e.id} bit $bit: synthesized loads, driver ${drivers.mkString(" ")}")
              ObjectRef("pin", drivers.head)
            case _ =>
              val candidates = connected(bit, if (sources(e.id)) "output" else "input").filter(preserved)
              require(candidates.size == 1,
                s"CHANNEL_ENDPOINT_UNBOUND: ${e.id} bit $bit: ${if (sources(e.id)) "driver" else "loads"} ${candidates.mkString(" ")}")
              ObjectRef("pin", candidates.head)
          }
        }
      }
      require(refs.size == e.width, s"BINDING_WIDTH: ${e.id}")
      refs.filter(_.kind == "pin").foreach { r =>
        val inst = r.name.substring(0, r.name.lastIndexOf('/'))
        require(routed.contains(inst), s"BOUND_INSTANCE_NOT_IN_ROUTED_NETLIST: $inst")
      }
      e.id -> refs
    }.toMap

    // Pins on a path the contract measures: a loop is never cut there. A pin is
    // on a path if its net is reachable from the path's start and its cell's
    // outputs reach the path's end (nets joined through $buf are one net).
    def net(b: ujson.Value): String = through(b, "input").map(_.toString).min
    val forward = scala.collection.mutable.Map.empty[String, Seq[String]]   // net -> output nets
    val backward = scala.collection.mutable.Map.empty[String, Seq[String]]  // net -> input nets
    val inputPins = scala.collection.mutable.Map.empty[String, Seq[(String, Seq[String])]] // net -> (pin, cell output nets)
    flatCells.filter(_._2("type").str != "$buf").foreach { case (inst, c) =>
      val conns = c("connections").obj.toSeq
      def dir(port: String) = c("port_directions")(port).str
      val outs = conns.filter(x => dir(x._1) == "output").flatMap(_._2.arr).filter(_.isInstanceOf[ujson.Num]).map(net).distinct
      conns.filter(x => dir(x._1) == "input").foreach { case (port, bits) =>
        bits.arr.zipWithIndex.filter(_._1.isInstanceOf[ujson.Num]).foreach { case (b, i) =>
          val n = net(b)
          val pin = if (bits.arr.size == 1) s"$inst/$port" else s"$inst/$port[$i]"
          forward(n) = forward.getOrElse(n, Seq()) ++ outs
          outs.foreach(o => backward(o) = backward.getOrElse(o, Seq()) :+ n)
          inputPins(n) = inputPins.getOrElse(n, Seq()) :+ (pin -> outs)
        }
      }
    }
    def closure(start: Seq[String], edges: collection.Map[String, Seq[String]]): Set[String] = {
      val seen = scala.collection.mutable.Set.empty[String]
      var frontier = start
      while (frontier.nonEmpty) {
        val next = frontier.filterNot(seen).distinct
        seen ++= next
        frontier = next.flatMap(n => edges.getOrElse(n, Seq()))
      }
      seen.toSet
    }
    def netsOf(o: ObjectRef): Seq[String] = {
      val bits = if (o.kind == "port") portBits.collect { case (bit, (name, _)) if name == o.name => ujson.read(bit) }.toSeq
        else flatCells.find(_._1 == o.name.substring(0, o.name.lastIndexOf('/'))).toSeq.flatMap { case (_, c) =>
          val pin = o.name.substring(o.name.lastIndexOf('/') + 1)
          val port = pin.takeWhile(_ != '['); val index = pin.drop(port.length).stripPrefix("[").stripSuffix("]")
          val bits = c("connections")(port).arr
          if (index.isEmpty) bits.toSeq else Seq(bits(index.toInt))
        }
      bits.filter(_.isInstanceOf[ujson.Num]).map(net)
    }
    // Breadth-first path from `from` to any of `to`, avoiding `blocked`; the nets on it.
    def path(from: Seq[String], to: Set[String], edges: collection.Map[String, Seq[String]],
        blocked: Set[String]): Option[Seq[String]] = {
      val parent = scala.collection.mutable.Map.empty[String, String]
      var frontier = from.filterNot(blocked).distinct
      frontier.foreach(n => parent(n) = n)
      while (frontier.nonEmpty) {
        frontier.find(to).foreach { hit =>
          return Some(Iterator.iterate(hit)(parent).takeWhile(n => parent(n) != n).toSeq :+ from.find(f => parent.get(f).contains(f)).getOrElse(hit))
        }
        frontier = frontier.flatMap(n => edges.getOrElse(n, Seq()).filterNot(m => blocked(m) || parent.contains(m)).distinct
          .map { m => parent(m) = n; m })
      }
      None
    }
    // Breadth-first distances in nets from `start` along `edges`.
    def distances(start: Seq[String], edges: collection.Map[String, Seq[String]]): Map[String, Int] = {
      val d = scala.collection.mutable.Map.empty[String, Int]
      var frontier = start.distinct; var k = 0
      while (frontier.nonEmpty) {
        frontier.foreach(n => d(n) = k)
        k += 1
        frontier = frontier.flatMap(n => edges.getOrElse(n, Seq())).distinct.filterNot(d.contains)
      }
      d.toMap
    }
    // A measured path's direct route: the fewest cells from its start to its end.
    // A loop is never cut there. A longer route between the same points passes
    // through further C-element transitions, which are other events of the
    // handshake; cutting one can only remove paths, so a measured minimum cannot
    // fall, and the direct route keeps the maximum.
    val protectedBy: Map[String, Seq[String]] = plan.rules.filter(_.measure != "arc").flatMap { r =>
      val starts = bindings(r.from).flatMap(netsOf).distinct
      val ends = bindings(r.to).flatMap(netsOf).distinct
      val df = distances(starts, forward); val db = distances(ends, backward)
      val direct = ends.flatMap(df.get).minOption
      direct.toSeq.flatMap { d =>
        df.toSeq.flatMap { case (n, k) => inputPins.getOrElse(n, Seq()).collect {
          case (pin, outs) if outs.exists(o => db.get(o).exists(k + 1 + _ == d)) => pin -> r.id
        } }
      } ++ bindings(r.to).map(o => o.name -> r.id)
    }.groupMap(_._1)(_._2)
    val protectedPins = protectedBy.keySet
    val out = Paths.get(output).toAbsolutePath
    Files.createDirectories(out)
    val analysis = cuts(pins, flatCells.map(_._1).toSet, liberty, Paths.get(netlist), top, Paths.get(setup), Paths.get(sta), out,
      protectedPins, p => protectedBy.getOrElse(p, Seq()))
    val constraints = plan.emit(bindings, out.resolve("constraints"))
    val result = OpenSta.check(constraints, OpenSta.Corner(corner, liberty, analysis, Paths.get(setup),
      Some(Paths.get(spef))), out.resolve("sta"), Seq(Paths.get(sta).toAbsolutePath.toString))
    println(s"$top: ${plan.rules.size} paths, ${plan.orderings.size} orderings checked at $corner -> $result")
  }

  /** A loop-free analysis netlist: the routed netlist with the handshake loops cut.
    *
    * OpenSTA breaks every combinational loop it finds at an arc of its own
    * choosing and computes no delay for that arc; on these controllers it picks
    * C-element set arcs, which the contract measures, and they read 0. Arc cuts
    * through set_disable_timing do not help: loops are found on the unconstrained
    * graph. So the loops are cut in the netlist, the usual practice for
    * asynchronous STA: a cut input pin is disconnected from its net and driven
    * from a new top-level input instead. First each C-element's own feedback
    * (its state gate's first input, which its output drives), then, while loops
    * remain, the C-element input-decode pin on the most remaining loops that
    * lies on no path the contract measures. State
    * gate outputs and set/hold inputs, latches, delay lines and control gates are
    * never cut. Removing a cut pin from its net drops that pin's input capacitance
    * from the net's load, a fraction of a femtofarad. The cuts are listed in
    * arc-cuts.txt for review.
    */
  private def cuts(pins: collection.Map[String, ujson.Value], cells: Set[String], liberty: Seq[Path], netlist: Path,
      top: String, setup: Path, sta: Path, out: Path, measured: Set[String], why: String => Seq[String]): Path = {
    // C-elements: the primitives with common/rising/falling ports. Their state
    // gate drives q's arc pin; everything else inside them is input decode.
    val elements = pins.toSeq.collect { case (rtl, ports) if ports.obj.contains("common") =>
      rtl.substring(rtl.indexOf('.') + 1) -> ports("q")("arc").arr.head.str.split('/')(0)
    }
    def full(prefix: String, cell: String): String =
      cells.find(c => c.startsWith(prefix + ".variant_") && c.endsWith(".mapped." + cell))
        .getOrElse(throw new IllegalArgumentException(s"STATE_GATE_UNRESOLVED: $prefix $cell"))
    val stateGates = elements.map { case (prefix, cell) => full(prefix, cell) }.toSet
    def instOf(pin: String) = pin.substring(0, pin.lastIndexOf('/'))
    def decode(pin: String): Boolean =
      elements.exists { case (prefix, _) => instOf(pin).startsWith(prefix + ".variant_") } && !stateGates(instOf(pin))

    var text = Files.readString(netlist)
    val cutList = scala.collection.mutable.ArrayBuffer.empty[String]
    def cut(pin: String): Unit = {
      val inst = instOf(pin); val port = pin.substring(pin.lastIndexOf('/') + 1)
      val at = text.indexOf("\\" + inst + " ")
      require(at >= 0, s"CUT_INSTANCE_NOT_FOUND: $inst")
      val end = text.indexOf(");", at)
      val body = text.substring(at, end)
      val conn = ("\\." + java.util.regex.Pattern.quote(port) + "\\(([^()]*)\\)").r
      val m = conn.findFirstMatchIn(body).getOrElse(throw new IllegalArgumentException(s"CUT_PIN_NOT_FOUND: $pin"))
      val net = s"ca_cut_${cutList.size}"
      text = text.substring(0, at) + body.substring(0, m.start) + s".$port($net)" + body.substring(m.end) + text.substring(end)
      val header = text.indexOf(");", text.indexOf("module " + top))
      text = text.substring(0, header) + s", $net);\n input $net;" + text.substring(header + 2)
      cutList += s"$pin (was ${m.group(1).trim})"
    }
    stateGates.toSeq.sorted.foreach(g => cut(s"$g/A1"))

    def loops(round: Int): Seq[Seq[String]] = {
      val v = out.resolve(s"analysis_$round.v"); Files.writeString(v, text)
      val finder = out.resolve(s"loops_$round.tcl")
      Files.writeString(finder, liberty.map(l => s"read_liberty {${l.toAbsolutePath}}").mkString("\n") +
        s"\nread_verilog {$v}\nlink_design $top\nsource {${setup.toAbsolutePath}}\n" +
        "report_checks -unconstrained -group_path_count 1 > /dev/null\nputs CA_LOOPS_BEGIN\nsta::report_loops\nputs CA_LOOPS_END\n")
      val log = out.resolve(s"loops_$round.log")
      val process = new ProcessBuilder(sta.toAbsolutePath.toString, "-no_splash", "-exit", finder.toString)
        .redirectErrorStream(true).redirectOutput(log.toFile).start()
      require(process.waitFor() == 0, s"LOOP_FINDER_FAILED: $log")
      val t = Files.readString(log)
      require(t.contains("CA_LOOPS_END"), s"LOOP_FINDER_INCOMPLETE: $log")
      t.substring(t.indexOf("CA_LOOPS_BEGIN") + 14, t.indexOf("CA_LOOPS_END")).split("\n\\s*\n")
        .map(_.linesIterator.map(_.trim).filter(_.contains("/")).toSeq).filter(_.size > 1).toSeq
    }
    var round = 0
    var remaining = loops(round)
    while (remaining.nonEmpty) {
      require(round < 64, s"LOOP_CUTTING_DID_NOT_CONVERGE: ${remaining.size} loops left")
      // Input pins of decode gates, where a loop enters one.
      val candidates = remaining.map(l => l.zip(l.tail).collect {
        case (a, b) if instOf(a) == instOf(b) && decode(a) && !measured(a) => a }.toSet)
      remaining.zip(candidates).find(_._2.isEmpty).foreach { case (l, _) =>
        throw new IllegalArgumentException("LOOP_UNCUTTABLE: every C-element decode input on this loop lies on a " +
          "measured path:\n  " + l.map(p => p + (if (decode(p)) " [decode]" else "") + (if (measured(p)) " [measured]" else "")).mkString("\n  ") +
          "\nprotected by:\n  " + l.filter(measured).distinct.map(p => s"$p: ${why(p).mkString(", ")}").mkString("\n  "))
      }
      val best = candidates.flatten.groupBy(identity).maxBy { case (p, hits) => (hits.size, p) }._1
      cut(best)
      round += 1
      remaining = loops(round)
    }
    Files.writeString(out.resolve("arc-cuts.txt"), "# Input pins cut to make the handshake loops analysable. No cut lies\n" +
      "# on the direct (fewest-cell) route of a measured path.\n" +
      cutList.mkString("\n") + "\n")
    val analysis = out.resolve("analysis.v")
    Files.writeString(analysis, text)
    analysis
  }
}
