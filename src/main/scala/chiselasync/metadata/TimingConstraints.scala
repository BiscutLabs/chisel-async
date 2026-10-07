// SPDX-License-Identifier: Apache-2.0
package chiselasync.metadata

import java.nio.file.{Files, Path}
import java.security.MessageDigest
import scala.collection.mutable.ArrayBuffer

/** Translate registered timing obligations into explicit mapped-netlist checks.
  * Bind semantic endpoints to exact mapped pins/ports after implementation. Empty,
  * partial or unsupported contracts fail; emitting files is not timing closure.
  * The OpenSTA checker runs in a fresh analysis context for one corner at a time.
  */
object TimingConstraints {
  final case class Endpoint(id: String, width: Int, description: String)
  /** One exact netlist bit. No wildcards or Tcl commands are accepted. */
  final case class ObjectRef(kind: String, name: String) {
    require(Set("pin", "port")(kind), "TIMING_OBJECT_KIND")
    require(name.matches("[A-Za-z0-9_./\\[\\]$:-]+"), "TIMING_OBJECT_NAME")
  }
  final case class PathRule(id: String, from: String, to: String, minFs: Long = 0,
      maxFs: Option[Long] = None, fromEdge: String = "both", toEdge: String = "both", measure: String = "path")
  final case class Ordering(id: String, early: String, late: String)
  private def sha(path: Path): String = MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(path)).map(b => f"${b & 255}%02x").mkString
  private def literal(value: String): String = {
    require(!value.exists(c => "{}\\\n\r".contains(c)), "UNSAFE_TIMING_LITERAL")
    "{" + value + "}"
  }
  private def ns(fs: Long): String = (BigDecimal(fs) / BigDecimal(1000000)).bigDecimal.toPlainString
  private def resource(name: String): String = {
    val stream = getClass.getResourceAsStream("/chiselasync/" + name)
    try new String(stream.readAllBytes(),java.nio.charset.StandardCharsets.UTF_8) finally stream.close()
  }

  /** Read a contract.json or the timing-intent.json from an ASIC export. Functional
    * zero-delay policies and obligations without a supported lowering are rejected.
    */
  def prepare(contract: Path): Plan = new Plan(contract)

  final class Plan private[TimingConstraints] (contract: Path) {
    private val originalHash = sha(contract)
    private val manifest = ujson.read(Files.readString(contract))("manifest")
    private val endpoints = scala.collection.mutable.LinkedHashMap.empty[String, Endpoint]
    private val paths = ArrayBuffer.empty[PathRule]
    private val order = ArrayBuffer.empty[Ordering]
    private val preserved = ArrayBuffer.empty[String]
    private val covered = ArrayBuffer.empty[String]
    private def visit(node: ujson.Value, prefix: String): Unit = {
      val eps = node("endpoints").arr.map(e => e("id").str -> e).toMap
      val cells = node("primitives").arr.map(p => p("id").str -> p).toMap
      def endpoint(id: String): String = {
        require(eps.contains(id), s"TIMING_ENDPOINT_MISSING: $prefix$id")
        val key = prefix + id
        endpoints.getOrElseUpdate(key, Endpoint(key, eps(id)("width").num.toInt, "channel/internal endpoint"))
        key
      }
      def pin(cell: String, port: String): String = {
        val p = cells.getOrElse(cell, throw new IllegalArgumentException(s"TIMING_CELL_MISSING: $prefix$cell"))
        val width = p("ports").arr.find(_("name").str == port).getOrElse(
          throw new IllegalArgumentException(s"TIMING_PIN_MISSING: $prefix$cell.$port"))("width").num.toInt
        val key = s"$prefix$cell.$port"
        endpoints.getOrElseUpdate(key, Endpoint(key,width,s"${p("rtl_path").str}.$port"))
        key
      }
      def cellPath(id: String, cell: String, input: String, min: Long, max: Option[Long], arc: Boolean = false): String = {
        val key = prefix + id
        paths += PathRule(key,pin(cell,input),pin(cell,"q"),min,max,measure=if(arc) "arc" else "path")
        key
      }
      def phaseCells(t: ujson.Value, skip: Set[String]): Unit = {
        cells.toSeq.sortBy(_._1).filter { case(id,p) => p("view").str=="behavioral" && !skip(id) }.foreach { case(id,p) =>
          val (ports,arc) = p("model").str match {
            case "ChiselAsyncClosingLatch_v1" => (Seq("d"),true)
            case "ChiselAsyncToggle_v1" => (Seq("trigger"),true)
            case "ChiselAsyncControlGate_v1" => (if(p("parameters")("OP").str=="2") Seq("a","b") else Seq("a"),false)
            case "ChiselAsyncXor_v1" => (Seq("a","b"),false)
            case other => throw new IllegalArgumentException(s"UNSUPPORTED_PHASE_CELL: $prefix$id ($other)")
          }
          ports.foreach(port => cellPath(s"${t("id").str}.$id.$port",id,port,
            t("cells")("min_fs").str.toLong,Some(t("cells")("max_fs").str.toLong),arc))
        }
      }
      cells.values.filter(_("view").str == "behavioral").filterNot(_("model").str == "ChiselAsyncProtocolGuard_v1")
        .foreach(p => preserved += p("rtl_path").str.split('.').drop(1).mkString("/"))
      node("timing").arr.foreach { t =>
        val id = prefix + t("id").str
        t("kind").str match {
          case "long-hold-bundling-v2" =>
            require(t("mode").str == "digital-model", s"TIMING_REQUIRES_POSITIVE_POLICY: $id")
            cellPath(t("id").str + ".admission", "request_delay", "a", t("matched_delay_fs").str.toLong, None)
            cellPath(t("id").str + ".offer", "output_delay", "a", t("output_delay_fs").str.toLong, None)
            val latch = t("latch_delay")
            cellPath(t("id").str + ".latch", "payload", "d", latch("min_fs").str.toLong, Some(latch("max_fs").str.toLong),arc=true)
            t("control_delays").obj.foreach { case (role,b) =>
              val cell = if (role == "long_hold") "long_hold" else role
              val ports = if (cell == "long_hold") Seq("a","b") else Seq("common","rising","falling").filter { port =>
                cells(cell)("parameters")(port.toUpperCase).str.toInt > 0
              }
              ports.foreach(p => cellPath(s"${t("id").str}.$cell.$p",cell,p,b("min_fs").str.toLong,Some(b("max_fs").str.toLong),arc=cell!="long_hold"))
            }
            require(t("matched_delay_fs").str.toLong > t("data_delay")("max_fs").str.toLong, "TIMING_INVALID_ADMISSION")
            val worst = t("control_delays").obj.values.map(_("max_fs").str.toLong).max
            require(BigInt(t("output_delay_fs").str) > 2*BigInt(worst)+BigInt(latch("max_fs").str), "TIMING_INVALID_OUTPUT_GUARD")
          case "bundled-data-path-v1" =>
            // This is the entire transform/glue path. The simulation allowance is
            // replaced by mapped logic, never inserted again as physical delay.
            paths += PathRule(id,endpoint(t("source").str),endpoint(t("sink").str),0,Some(t("budget")("max_fs").str.toLong))
          case "long-hold-fork-v1" =>
            val early = id + ".ack_branch"; val late = id + ".state_branch"
            paths += PathRule(early,endpoint(t("aout").str),pin("long_hold","b"),fromEdge="rise",toEdge="rise")
            paths += PathRule(late,endpoint(t("aout").str),pin("long_hold","a"),fromEdge="rise",toEdge="fall")
            order += Ordering(id,early,late)
          case "phase-conversion-v2" if t("direction").str == "four-to-two" =>
            val close = id + ".closure"; val request = id + ".request"
            paths += PathRule(close,endpoint(t("input_request").str),pin("history","closed"),0,
              Some(t("history_closure")("max_fs").str.toLong),"rise","rise")
            paths += PathRule(request,endpoint(t("input_request").str),endpoint(t("output_request").str),
              t("request_delay_fs").str.toLong,None,"rise","both")
            order += Ordering(id,close,request)
            phaseCells(t,Set("history_close","request_guard"))
          case "phase-conversion-v2" if t("direction").str == "two-to-four" =>
            cellPath(t("id").str + ".return", "return_guard", "a",t("return_delay_fs").str.toLong,None)
            phaseCells(t,Set("return_guard"))
          case other => throw new IllegalArgumentException(s"UNSUPPORTED_TIMING_OBLIGATION: $id ($other)")
        }
        covered += id
      }
      node("children").arr.foreach(c => visit(c("contract"),prefix+c("id").str+"."))
    }
    visit(manifest("design"), "")
    require(paths.nonEmpty && covered.nonEmpty, "EMPTY_TIMING_CONTRACT")
    require(paths.map(_.id).distinct.size == paths.size, "DUPLICATE_TIMING_RULE")
    val required: Seq[Endpoint] = endpoints.values.toSeq
    val rules: Seq[PathRule] = paths.toSeq
    val orderings: Seq[Ordering] = order.toSeq

    /** Emit SDC, preservation rules and an OpenSTA checker. Bind state-cell arc
      * endpoints to the actual characterized macro pins. These propagation checks
      * do not establish latch setup/hold, reset recovery or hazard freedom.
      * Bind every endpoint
      * bit exactly once and supply additional characterized closure/setup margin
      * through `closureMargins` for each four-to-two phase ordering. A zero margin
      * is allowed only when the bound already includes the technology aperture.
      * Run every required operating corner; a pass covers only the loaded corner.
      */
    def emit(bindings: Map[String, Seq[ObjectRef]], directory: Path,
        closureMargins: Map[String, ModelTime] = Map.empty): Path = {
      require(sha(contract) == originalHash, "TIMING_CONTRACT_CHANGED")
      require(bindings.keySet == endpoints.keySet, "INCOMPLETE_OR_EXTRA_TIMING_BINDINGS")
      required.foreach { e => require(bindings(e.id).size == e.width && bindings(e.id).distinct.size == e.width,
        s"TIMING_BINDING_WIDTH: ${e.id}") }
      val closures = orderings.filter(_.early.endsWith(".closure")).map(_.id).toSet
      require(closureMargins.keySet == closures, "MISSING_OR_EXTRA_CLOSURE_MARGINS")
      require(!Files.exists(directory), "TIMING_OUTPUT_ALREADY_EXISTS")
      Files.createDirectories(directory)
      val names = required.zipWithIndex.map { case(e,i) => e.id -> s"ca_ep_$i" }.toMap
      val prelude = "# Generated mapped-netlist constraints; emission is not timing closure.\n" +
        resource("timing-endpoints.tcl") + "\n" + required.map { e =>
        s"set ${names(e.id)} [concat ${bindings(e.id).map(o => s"[ca_exact ${o.kind} ${literal(o.name)}]").mkString(" ")}]"
      }.mkString("\n") + "\n"
      def args(r: PathRule): String = {
        val from = if(r.fromEdge=="both") "-from" else s"-${r.fromEdge}_from"
        val to = if(r.toEdge=="both") "-to" else s"-${r.toEdge}_to"
        s"$from $$${names(r.from)} $to $$${names(r.to)}"
      }
      val sdc = rules.map(r => if(r.measure=="arc") s"# ${r.id}: characterized state-cell arc; checked by ca_arc, not a clock path exception.\n" else s"# ${r.id}\nset_min_delay ${ns(r.minFs)} ${args(r)}\n" +
        r.maxFs.map(v => s"set_max_delay ${ns(v)} ${args(r)}\n").getOrElse("")).mkString
      Files.writeString(directory.resolve("constraints.sdc"),prelude+sdc)
      val preserve = preserved.distinct.sorted.map(p =>
        s"set ca_cell [get_cells -quiet ${literal(p)}]\nif {[llength $$ca_cell] != 1} { error ${literal("PRESERVATION_CELL_UNRESOLVED: "+p)} }\nset_dont_touch $$ca_cell true").mkString("\n")
      Files.writeString(directory.resolve("preserve.tcl"),"# Run in the synthesis/implementation tool before optimization.\n"+preserve+"\n")
      val helper = resource("timing-checks.tcl")
      val measurements = rules.zipWithIndex.map { case(r,i) =>
        val call = if(r.measure=="arc") s"ca_arc ${literal(r.id)} $$${names(r.from)} $$${names(r.to)}" else s"ca_measure ${literal(r.id)} [list ${args(r)}]"
        s"set ca_bound_$i [$call ${ns(r.minFs)} ${r.maxFs.map(ns).getOrElse("none")}]"
      }.mkString("\n")
      val index = rules.zipWithIndex.map { case(r,i) => r.id -> i }.toMap
      val relative = orderings.map { r =>
        s"ca_order ${literal(r.id)} $$ca_bound_${index(r.early)} $$ca_bound_${index(r.late)} ${ns(closureMargins.getOrElse(r.id,ModelTime(0)).fs)}"
      }.mkString("\n")
      Files.writeString(directory.resolve("check-timing.tcl"),prelude+helper+"\n"+measurements+"\n"+relative+
        s"\nputs {CA_TIMING_PASS paths=${rules.size} orderings=${orderings.size}}\n")
      val record = ujson.Obj("schema" -> "chisel-async-timing-constraints-v1", "status" -> "emitted-unchecked",
        "contract_sha256" -> originalHash, "top" -> manifest("top"), "covered_obligations" -> ujson.Arr.from(covered),
        "paths" -> ujson.Arr.from(rules.map(_.id)), "orderings" -> ujson.Arr.from(orderings.map(_.id)),
        "bindings" -> ujson.Obj.from(required.map(e => e.id -> ujson.Arr.from(bindings(e.id).map(o => ujson.Obj("kind"->o.kind,"name"->o.name))))),
        "closure_margins_fs" -> ujson.Obj.from(closureMargins.toSeq.sortBy(_._1).map { case(k,v) => k -> ujson.Str(v.fs.toString) }),
        "files_sha256" -> ujson.Obj.from(Seq("constraints.sdc","preserve.tcl","check-timing.tcl").map(n => n -> ujson.Str(sha(directory.resolve(n))))))
      Files.writeString(directory.resolve("constraints.json"),ujson.write(record,indent=2)+"\n")
      directory
    }
  }
}
