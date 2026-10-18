// SPDX-License-Identifier: Apache-2.0
package chiselasync.metadata

import scala.collection.mutable

/** Generation-time structural checks on CIRCT's typed HW IR, before Verilog.
  * This deliberately accepts a bounded HW/Comb/Seq vocabulary. Unknown value
  * producers fail closed; a compiler upgrade must extend the reviewed vocabulary.
  * It is not a timing, reset-domain-crossing or protocol proof.
  */
object StructureAudit {
  private case class Port(name: String, input: Boolean, clock: Boolean, width: Int)
  private case class Instance(name: String, kind: String, parameters: Map[String, BigInt],
                              inputs: Vector[(String, String)], outputs: Vector[(String, String)])
  private case class Body(name: String, model: String, ports: Vector[Port], external: Boolean,
                          lines: Vector[String])
  private val value = "%[A-Za-z0-9_.$-]+(?:#[0-9]+)?".r
  private val moduleStart = "^(?:hw.module|sv.verbatim.module|hw.module.extern)(?: private| public)? @([A-Za-z0-9_.$-]+).*".r
  private val combinational = Set("hw.wire", "hw.array_get", "hw.array_create", "hw.array_concat",
    "hw.array_slice", "hw.struct_extract", "hw.struct_create", "hw.struct_inject", "hw.bitcast",
    "comb.mux", "comb.and", "comb.or", "comb.xor", "comb.extract", "comb.icmp", "comb.concat",
    "comb.parity", "comb.add", "comb.sub", "comb.mul", "comb.divu", "comb.divs", "comb.modu",
    "comb.mods", "comb.replicate", "comb.shru", "comb.shrs", "comb.shl", "seq.to_clock", "seq.from_clock")
  private val constants = Set("hw.constant", "hw.aggregate_constant")
  private val storagePins = Map("ChiselAsyncLatch_v1" -> Set("enable"),
    "ChiselAsyncClosingLatch_v1" -> Set("closed"), "ChiselAsyncEventRegister_v1" -> Set("trigger"),
    "ChiselAsyncPhaseRegister_v1" -> Set("trigger"), "ChiselAsyncToggle_v1" -> Set("trigger"),
    "ChiselAsyncCElement_v1" -> Set("a", "b"), "ChiselAsyncAsymmetricC_v1" -> Set("common", "rising", "falling"),
    "ChiselAsyncMutex_v1" -> Set("request"), "ChiselAsyncFourPhaseStorage_v1" -> Set("in_req", "out_ack"))
  private val combinationalPrimitives = Set("ChiselAsyncControlGate_v1", "ChiselAsyncPassiveDataAllowance_v1",
    "ChiselAsyncDelayLine_v1", "ChiselAsyncAnd_v1", "ChiselAsyncXor_v1")
  private val markers = Set("ChiselAsyncTimingMarker_v1", "ChiselAsyncProtocolGuard_v1",
    "ChiselAsyncClickMarker_v1", "ChiselAsyncQdiMarker_v1")
  private def need(ok: Boolean, id: String): Unit = require(ok, "STRUCTURE_" + id)

  // Remove string contents before recognizing SSA operands, braces or comments.
  private def unquoted(s: String): String = {
    val out = new StringBuilder; var quoted = false; var escaped = false
    s.foreach { c =>
      if (quoted) { out += ' '; if (escaped) escaped = false else if (c == '\\') escaped = true else if (c == '"') quoted = false }
      else if (c == '"') { quoted = true; out += ' ' } else out += c
    }; out.toString
  }
  private def group(s: String, start: Int, open: Char, close: Char): (String, Int) = {
    need(start >= 0 && s(start) == open, "GROUP")
    val clean = unquoted(s); var depth = 1; var end = start + 1
    while (end < s.length && depth > 0) {
      if (clean(end) == open) depth += 1
      if (clean(end) == close) depth -= 1
      end += 1
    }
    need(depth == 0, "UNBALANCED_GROUP"); (s.substring(start + 1, end - 1), end)
  }
  private def split(s: String): Vector[String] = {
    val clean = unquoted(s); val out = mutable.ArrayBuffer.empty[String]
    var depth = 0; var start = 0
    clean.indices.foreach { i =>
      if ("(<[{".contains(clean(i))) depth += 1
      else if (")>]}".contains(clean(i))) depth -= 1
      else if (clean(i) == ',' && depth == 0) { out += s.substring(start, i).trim; start = i + 1 }
    }
    out += s.substring(start).trim; out.filter(_.nonEmpty).toVector
  }
  private def parse(text: String): Map[String, Body] = {
    val lines = text.linesIterator.toVector; val result = mutable.Map.empty[String, Body]; var i = 0
    while (i < lines.size) {
      val line = lines(i).trim
      line match {
        case moduleStart(name) =>
          val external = !line.startsWith("hw.module ")
          val (header, after) = group(line, line.indexOf('('), '(', ')')
          val ports = split(header).map { p =>
            val pattern = "^(in|out) %?([A-Za-z0-9_.$-]+)\\s*:\\s*(.*)$".r
            p match {
              case pattern(direction, port, typ) =>
                val width = "^i([0-9]+)\\b".r.findFirstMatchIn(typ).map(_.group(1).toInt).getOrElse(0)
                Port(port, direction == "in", typ.startsWith("!seq.clock"), width)
              case _ => throw new IllegalArgumentException("STRUCTURE_PORT_SYNTAX:" + p)
            }
          }
          val model = "verilogName = \"([^\"]+)\"".r.findFirstMatchIn(line).map(_.group(1)).getOrElse(name)
          val body = mutable.ArrayBuffer.empty[String]
          if (!external) {
            need(line.substring(after).trim.endsWith("{"), "MODULE_BODY")
            var depth = 1
            while (depth > 0 && i + 1 < lines.size) {
              i += 1; val l = lines(i); val clean = unquoted(l).takeWhile(_ != '\n')
              depth += clean.count(_ == '{') - clean.count(_ == '}')
              if (depth > 0) body += l.trim
            }
            need(depth == 0, "MODULE_TERMINATION")
          }
          need(!result.contains(name), "DUPLICATE_MODULE"); result(name) = Body(name, model, ports, external, body.toVector)
        case _ => ()
      }
      i += 1
    }; result.toMap
  }

  private def instance(line: String): Instance = {
    val start = line.indexOf("hw.instance ")
    val rest = line.substring(start)
    val name = "^hw.instance \"([^\"]+)\"".r.findFirstMatchIn(rest).getOrElse(
      throw new IllegalArgumentException("STRUCTURE_INSTANCE_NAME")).group(1)
    val begin = rest.indexOf('('); val prefix = rest.substring(0, begin)
    val refs = "@([A-Za-z0-9_.$-]+)".r.findAllMatchIn(prefix).toVector
    need(refs.nonEmpty, "INSTANCE_MODULE"); val kind = refs.last.group(1)
    val suffix = prefix.substring(refs.last.end).trim
    val entries = if (suffix.isEmpty) Vector.empty else {
      val (contents, end) = group(suffix, 0, '<', '>')
      need(suffix.substring(end).trim.isEmpty, "PARAMETER_SYNTAX")
      split(contents).map { entry =>
        val parameter = "^([A-Za-z0-9_]+): (?:u?i[0-9]+) = (-?[0-9]+)$".r
        entry match {
          case parameter(key, number) => key -> BigInt(number)
          case _ => throw new IllegalArgumentException("STRUCTURE_PARAMETER_SYNTAX:" + entry)
        }
      }
    }
    need(entries.map(_._1).distinct.size == entries.size, "DUPLICATE_PARAMETER")
    val params = entries.toMap
    val (args, end) = group(rest, begin, '(', ')')
    val incoming = split(args).map { a =>
      val colon = a.indexOf(':'); val operands = value.findAllIn(unquoted(a.substring(colon + 1))).toVector
      need(colon > 0 && operands.size == 1, "INSTANCE_INPUT"); a.substring(0, colon).trim -> operands.head
    }
    val (returns, _) = group(rest, rest.indexOf('(', end), '(', ')')
    val names = split(returns).map(_.takeWhile(_ != ':').trim)
    val lhs = if (start == 0) Vector.empty else value.findAllIn(line.substring(0, line.indexOf('='))).toVector
    need(lhs.size == names.size, "INSTANCE_RESULTS")
    Instance(name, kind, params, incoming, names.zip(lhs))
  }

  def check(text: String, top: String, contract: ujson.Value): ujson.Value = {
    val modules = parse(text); need(modules.contains(top), "TOP")
    val expected = mutable.Map.empty[String, ujson.Value]
    val owners = mutable.Set.empty[String]
    def inventory(node: ujson.Value): Unit = {
      node.obj.get("rtl_path").foreach(p => owners += p.str)
      node("primitives").arr.foreach { p =>
        val path = p("rtl_path").str
        need(!expected.contains(path), "DUPLICATE_PRIMITIVE"); expected(path) = p
      }
      node("children").arr.foreach(c => inventory(c("contract")))
    }; inventory(contract)
    val actual = mutable.Set.empty[String]; val roots = mutable.Set.empty[String]
    val graph = mutable.Map.empty[String, mutable.Set[String]]
    val sinks = mutable.ArrayBuffer.empty[(String, String)]
    val opaque = mutable.Set.empty[String]
    val observations = mutable.Set.empty[String]
    val ownerModules = mutable.Map.empty[String, String]
    def edge(from: String, to: String): Unit = graph.getOrElseUpdate(from, mutable.Set.empty) += to
    def walk(kind: String, path: String, incoming: Map[String, String], stack: Set[String],
             inheritedClockedBoundary: Boolean): Map[String, String] = {
      need(!stack(kind), "RECURSIVE_HIERARCHY"); val body = modules(kind)
      need(!body.external, "EXTERNAL_TOP")
      if (owners(path)) ownerModules(path) = kind
      val clockedBoundary = if (owners(path) || path == top) body.ports.exists(p => p.input && p.clock)
        else inheritedClockedBoundary
      // CIRCT extracts assertions into portless observer instances. XMR is
      // allowed only in these closed, output-free diagnostic bodies; it is
      // never a safe cut for a functional value or arbitrary Verilog text.
      if (body.lines.exists(_.contains("sv.xmr.ref")) && body.ports.isEmpty) {
        val observerOps = Set("sv.xmr.ref", "sv.read_inout", "sv.macro.ref.expr", "sv.always",
          "seq.firreg", "sv.if", "sv.ifdef", "sv.error.procedural", "sv.fatal.procedural", "hw.output", "}")
        body.lines.filter(_.nonEmpty).foreach { line =>
          val rhs = if (line.startsWith("%")) line.substring(line.indexOf('=') + 1).trim else line
          val op = rhs.takeWhile(c => !c.isWhitespace)
          need(observerOps(op) || combinational(op) || constants(op), "OBSERVER_SIDE_EFFECT:" + op)
        }
        observations += path
        return Map.empty
      }
      def local(v: String): String = path + ":" + v
      val defined = mutable.Set.empty[String]; val used = mutable.Set.empty[String]
      body.ports.filter(_.input).foreach { p =>
        val id = local("%" + p.name); defined += "%" + p.name
        incoming.get(p.name).foreach(edge(_, id))
        if (p.clock && path == top) roots += id
      }
      var outputs = Vector.empty[String]
      var diagnosticDepth = 0
      body.lines.foreach { line =>
        if (diagnosticDepth > 0 || line.startsWith("sv.ifdef ") || line.startsWith("sv.always ")) {
          val rhs = if (line.startsWith("%")) line.substring(line.indexOf('=') + 1).trim else line
          val op = rhs.takeWhile(c => !c.isWhitespace)
          need(Set("sv.ifdef", "sv.always", "sv.if", "sv.error.procedural", "sv.fatal.procedural",
            "sv.macro.ref.expr", "}")(op) || combinational(op) || constants(op), "DIAGNOSTIC_SIDE_EFFECT:" + op)
          val clean = unquoted(line)
          diagnosticDepth += clean.count(_ == '{') - clean.count(_ == '}')
        } else if (line.startsWith("hw.output")) outputs = value.findAllIn(unquoted(line)).toVector
        else if (line.contains("hw.instance ")) {
          val inst = instance(line); need(modules.contains(inst.kind), "UNKNOWN_MODULE:" + inst.kind)
          val target = modules(inst.kind); val at = path + "." + inst.name
          used ++= inst.inputs.map(_._2); defined ++= inst.outputs.map(_._2)
          need(inst.inputs.map(_._1).toSet == target.ports.filter(_.input).map(_.name).toSet, "INPUT_PORTS:" + at)
          need(inst.outputs.map(_._1).toSet == target.ports.filterNot(_.input).map(_.name).toSet, "OUTPUT_PORTS:" + at)
          if (!target.external) {
            val result = walk(inst.kind, at, inst.inputs.map { case (p, v) => p -> local(v) }.toMap, stack + kind, clockedBoundary)
            inst.outputs.foreach { case (p, v) => edge(result(p), local(v)) }
          } else {
            if (target.model.startsWith("ChiselAsync")) {
              need(storagePins.contains(target.model) || combinationalPrimitives(target.model) || markers(target.model),
                "UNKNOWN_PRIMITIVE_KIND:" + target.model)
              need(expected.contains(at), "UNREGISTERED_PRIMITIVE:" + at)
              val declared = expected(at); actual += at
              need(declared("model").str == target.model, "PRIMITIVE_MODEL:" + at)
              need(declared("parameters").obj.map { case (k, v) => k -> BigInt(v.str) }.toMap == inst.parameters,
                "PRIMITIVE_PARAMETERS:" + at)
              val ports = declared("ports").arr.map(p => (p("name").str, p("direction").str == "input", p("width").num.toInt)).toSet
              need(ports == target.ports.map(p => (p.name, p.input, p.width)).toSet, "PRIMITIVE_PORTS:" + at)
              // A transparent latch is no barrier for a periodic clock on D.
              // Check all native storage inputs, not only its capture pin.
              val checked = if (storagePins.contains(target.model)) inst.inputs.map(_._1).toSet else Set.empty[String]
              checked.foreach { pin =>
                val input = inst.inputs.toMap; need(input.contains(pin), "STORAGE_PIN:" + at)
                sinks += at -> local(input(pin))
              }
            } else opaque += target.model
            // Native storage ends combinational clock propagation; its capture
            // pin is checked above. Unknown external modules are conservative:
            // every input may affect every output, never an implicit safe cut.
            if (!storagePins.contains(target.model))
              for ((_, in) <- inst.inputs; (_, out) <- inst.outputs) edge(local(in), local(out))
          }
        } else if (line.startsWith("%")) {
          val eq = line.indexOf('='); need(eq > 0, "SSA_SYNTAX")
          val lhs = value.findAllIn(line.substring(0, eq)).toVector
          val rhs = line.substring(eq + 1).trim; val op = rhs.takeWhile(c => !c.isWhitespace)
          val args = value.findAllIn(unquoted(rhs)).toVector
          need(lhs.size == 1, "SSA_RESULTS:" + op); defined ++= lhs; used ++= args
          if (combinational(op)) args.foreach(a => edge(local(a), local(lhs.head)))
          else if (constants(op)) ()
          else if (op == "seq.firmem") {
            need("^seq.firmem [1-9][0-9]*, [1-9][0-9]*,".r.findFirstIn(rhs).nonEmpty, "MEMORY_LATENCY")
            need(clockedBoundary, "CLOCKED_NATIVE_OWNER:" + path)
          } else if (Set("seq.firreg", "seq.compreg", "seq.compreg.ce", "seq.firmem.read_write_port", "seq.firmem.read_port")(op)) {
            need(clockedBoundary, "CLOCKED_NATIVE_OWNER:" + path)
          }
          else throw new IllegalArgumentException("STRUCTURE_UNSUPPORTED_PRODUCER:" + op)
        } else need(line.isEmpty || line.startsWith("//"), "UNSUPPORTED_OPERATION:" + line.take(80))
      }
      need(diagnosticDepth == 0, "DIAGNOSTIC_REGION")
      used ++= outputs
      need(used.subsetOf(defined), "UNDRIVEN_VALUE:" + path + ":" + (used -- defined).toVector.sorted.mkString(","))
      val outPorts = body.ports.filterNot(_.input)
      need(outputs.size == outPorts.size, "DRIVEN_OUTPUTS:" + path)
      outPorts.map(_.name).zip(outputs.map(local)).toMap
    }
    walk(top, top, Map.empty, Set.empty, false)
    need(ownerModules.keySet == owners, "OWNER_INVENTORY:" + (owners -- ownerModules.keySet).toVector.sorted.mkString(","))
    need(actual == expected.keySet, "PRIMITIVE_INVENTORY:" + (expected.keySet -- actual).toVector.sorted.mkString(","))
    val seen = mutable.Set.empty[String]; val pending = mutable.Queue.empty[String]; pending ++= roots
    while (pending.nonEmpty) { val n = pending.dequeue(); if (seen.add(n)) graph.get(n).foreach(pending ++= _) }
    val violations = sinks.filter { case (_, input) => seen(input) }
    need(violations.isEmpty, "CLOCK_REACHES_NATIVE_STORAGE:" + violations.map(_._1).mkString(","))
    ujson.Obj("schema" -> "chisel-async-structure-v1", "top" -> top, "status" -> "pass",
      "primitive_paths" -> ujson.Arr.from(actual.toVector.sorted), "native_storage" -> sinks.map(_._1).distinct.size,
      "checked_storage_inputs" -> sinks.size,
      "clock_roots" -> ujson.Arr.from(roots.toVector.sorted), "opaque_external_models" -> ujson.Arr.from(opaque.toVector.sorted),
      "observation_modules" -> ujson.Arr.from(observations.toVector.sorted),
      "owner_modules" -> ujson.Obj.from(ownerModules.toVector.sortBy(_._1).map { case (p, m) => p -> ujson.Str(m) }),
      "scope" -> "typed generation graph; no timing/RDC/protocol or mapped-cell qualification")
  }
}
