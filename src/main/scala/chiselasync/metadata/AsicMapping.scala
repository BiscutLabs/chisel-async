// SPDX-License-Identifier: Apache-2.0
package chiselasync.metadata

import chiselasync.core.AsyncModule
import java.nio.file.{Files, Path, StandardCopyOption}
import java.security.MessageDigest
import scala.jdk.CollectionConverters._

/** Explicit ASIC technology binding. No generic RTL replacement can guarantee the
  * analog behavior of a MUTEX, hazard-free C-element, or characterized delay.
  * A technology adapter must implement the complete atomic cell and reset contract.
  */
object AsicMapping {
  /** Exact primitive specialization, including width, reset, inversion and delay.
    * A model name alone is never sufficient to select a technology implementation.
    */
  final case class Key(model: String, parameters: Map[String, BigInt])
  /** Logical primitive port and its elaborated width/direction. */
  final case class Port(name: String, width: Int, direction: String)
  /** One required specialization, its complete port interface and affected RTL paths. */
  final case class RequiredCell(key: Key, ports: Seq[Port], instances: Seq[String])
  /** Technology adapter for one exact specialization.
    *
    * @param key key copied from [[Plan.required]]
    * @param module fixed-interface technology module supplied in the source inventory
    * @param pins complete one-to-one map from logical primitive ports to technology pins
    * @param provenance nonempty implementation/characterization reference; recording
    *   it does not prove electrical equivalence or timing closure
    */
  final case class Binding(key: Key, module: String, pins: Map[String, String], provenance: String)
  private def identifier(value: String): Boolean = value.matches("[A-Za-z_][A-Za-z0-9_$]*")
  private def sha(path: Path): String = MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(path))
    .map(b => f"${b & 0xff}%02x").mkString
  private def nodes(n: ujson.Value): Seq[ujson.Value] = Seq(n) ++ n("children").arr.toSeq.flatMap(c => nodes(c("contract")))
  private def key(p: ujson.Value): Key = Key(p("model").str, p("parameters").obj.toMap.map { case (k,v) => k -> BigInt(v.str) })
  private def passive(p: ujson.Value): Boolean = p("view").str == "constraint-marker" || p("model").str == "ChiselAsyncProtocolGuard_v1"
  private def jsonKey(k: Key): ujson.Value = ujson.Obj("model" -> k.model,
    "parameters" -> ujson.Obj.from(k.parameters.toSeq.sortBy(_._1).map { case (n,v) => n -> ujson.Str(v.toString) }))

  /** Emit a fresh design and inventory every parameter specialization before binding.
    * Inspect the returned [[Plan.required]] and `required-cells.json`, then supply
    * exhaustive technology bindings to [[Plan.emit]]. No default cells are inferred.
    *
    * @param gen fresh design whose async children and primitives are registered for export
    * @param directory workspace for the `simulation` export and later `asic` output;
    *   an existing `asic` directory is rejected
    */
  def prepare(gen: => AsyncModule, directory: Path): Plan = {
    val base = directory.toAbsolutePath
    require(!Files.exists(base.resolve("asic")), "ASIC_OUTPUT_ALREADY_EXISTS")
    ExportDesign.emit(gen, base.resolve("simulation"))
    new Plan(base)
  }

  /** Inventory tied to an unchanged generated design. Prepare a new plan after edits. */
  final class Plan private[AsicMapping] (base: Path) {
    private val simulation = base.resolve("simulation")
    private val manifest = ujson.read(Files.readString(simulation.resolve("contract.json")))("manifest")
    private val primitives = nodes(manifest("design")).flatMap(_("primitives").arr)
    /** Every active cell specialization requiring a binding; passive markers and
      * simulation protocol diagnostics are handled separately by [[emit]].
      */
    val required: Seq[RequiredCell] = primitives.filterNot(passive).groupBy(key).toSeq.sortBy {
      case (k,_) => k.model + k.parameters.toSeq.sortBy(_._1).mkString
    }.map { case (k, cells) =>
      val ports = cells.head("ports").arr.toSeq.map(p => Port(p("name").str, p("width").num.toInt, p("direction").str))
      require(cells.forall(_("ports") == cells.head("ports")), "INCONSISTENT_CELL_PORTS")
      RequiredCell(k, ports, cells.map(_("rtl_path").str))
    }
    private val sourceFiles = Files.readAllLines(simulation.resolve("filelist.f")).asScala
      .filter(_.trim.nonEmpty).map(s => simulation.resolve(s.trim)).toSeq
    private val declaredNodes = nodes(manifest("design"))
    private val declaredFiles = (declaredNodes.map(_("module").str) ++ primitives.map(_("model").str)).map(_ + ".sv").toSet
    require(sourceFiles.forall(p => declaredFiles(p.getFileName.toString)), "UNREGISTERED_ASIC_SOURCE")
    // Inspect generated module bodies as well as the registry: an unregistered
    // instance of an otherwise registered model must not inherit a binding silently.
    declaredNodes.foreach { node =>
      val file = simulation.resolve(node("module").str + ".sv")
      if (Files.exists(file)) {
        val rtl = Files.readString(file).linesIterator.map(_.split("\t//",2)(0)).mkString("\n")
        val observed = primitives.map(_("model").str).distinct.flatMap { model =>
          val pattern = ("(?s)\\b" + java.util.regex.Pattern.quote(model) + "\\s*(?:#\\s*\\(.*?\\)\\s*)?([A-Za-z_][A-Za-z0-9_$]*)\\s*\\(").r
          pattern.findAllMatchIn(rtl).map(m => model -> m.group(1)).toSeq
        }.toSet
        val declared = node("primitives").arr.map(p => p("model").str -> p("rtl_path").str.split('.').last).toSet
        require(observed == declared, "UNREGISTERED_ASIC_PRIMITIVE")
        val actualChildren = declaredNodes.map(_("module").str).distinct.flatMap { model =>
          val pattern = ("(?s)\\b" + java.util.regex.Pattern.quote(model) + "\\s+([A-Za-z_][A-Za-z0-9_$]*)\\s*\\(").r
          pattern.findAllMatchIn(rtl).map(_.group(1)).toSeq
        }.toSet
        val expectedChildren = node("children").arr.map(_("contract")("rtl_path").str.split('.').last).toSet
        require(actualChildren == expectedChildren, "UNREGISTERED_ASIC_CHILD")
      }
    }
    private val originalHashes = (sourceFiles ++ Seq(simulation.resolve("contract.json"), simulation.resolve("ports.json")))
      .map(p => p -> sha(p)).toMap
    Files.writeString(base.resolve("required-cells.json"), ujson.write(ujson.Arr.from(required.map { r =>
      ujson.Obj("cell" -> jsonKey(r.key), "instances" -> ujson.Arr.from(r.instances),
        "ports" -> ujson.Arr.from(r.ports.map(p => ujson.Obj("name" -> p.name, "width" -> p.width, "direction" -> p.direction))))
    }), indent=2) + "\n")

    /** Emit only mapped wrappers, ordinary design RTL and supplied technology sources.
      * Bindings are exhaustive and exact, including delay, inversion and reset parameters.
      * Passive constraint markers remain in the netlist until constraints are extracted;
      * protocol diagnostics are explicitly omitted in this synthesis-only file list.
      *
      * The output is marked `mapped-unqualified`. The caller remains responsible for
      * technology behavior, timing constraints, preservation, synthesis and physical
      * validation. Never mix this file list with the simulation model list.
      *
      * @param bindings exactly one binding for every member of [[required]], with no extras
      * @param technologySources complete RTL/black-box source set for the bound adapters;
      *   each source is copied by filename, so filenames must be distinct
      * @return new `asic` directory containing `filelist.f`, `mapping.json` with hashes,
      *   and `timing-intent.json`; refuses overwrite or changed prepared inputs
      */
    def emit(bindings: Seq[Binding], technologySources: Seq[Path]): Path = {
      require(originalHashes.forall { case(p,h) => sha(p) == h }, "MAPPING_INPUT_CHANGED")
      require(bindings.map(_.key).distinct.size == bindings.size, "DUPLICATE_CELL_BINDING")
      require(bindings.map(_.key).toSet == required.map(_.key).toSet, "INCOMPLETE_OR_EXTRA_CELL_BINDINGS")
      require(technologySources.nonEmpty && technologySources.forall(Files.isRegularFile(_)), "MISSING_TECHNOLOGY_SOURCES")
      val texts = technologySources.map(Files.readString(_)).mkString("\n")
      bindings.foreach { b =>
        val r = required.find(_.key == b.key).get
        require(identifier(b.module) && !b.module.startsWith("ChiselAsync") && b.pins.values.forall(identifier), "INVALID_TECHNOLOGY_IDENTIFIER")
        require(b.pins.keySet == r.ports.map(_.name).toSet && b.pins.values.toSet.size == b.pins.size, "INCOMPLETE_CELL_PIN_MAP")
        require(b.provenance.trim.nonEmpty, "MISSING_MAPPING_PROVENANCE")
        require(("(?m)\\bmodule\\s+" + java.util.regex.Pattern.quote(b.module) + "\\b").r.findFirstIn(texts).nonEmpty, "MISSING_TECHNOLOGY_MODULE")
      }
      val dest = base.resolve("asic")
      require(!Files.exists(dest), "ASIC_OUTPUT_ALREADY_EXISTS")
      val primitiveNames = primitives.map(_("model").str + ".sv").toSet
      // Resource emission can put the model in filelist.f. Never copy a behavioral body.
      val rtl = sourceFiles.filterNot(p => primitiveNames(p.getFileName.toString))
      val wrapperNames = primitiveNames.toSeq
      val names = rtl.map(_.getFileName.toString) ++ technologySources.map(_.getFileName.toString) ++ wrapperNames
      require(names.distinct.size == names.size, "MAPPING_SOURCE_NAME_COLLISION")
      Files.createDirectories(dest)
      (rtl ++ technologySources).foreach(p => Files.copy(p, dest.resolve(p.getFileName), StandardCopyOption.REPLACE_EXISTING))
      primitives.groupBy(_("model").str).toSeq.sortBy(_._1).foreach { case (model, cells) =>
        val stream = getClass.getResourceAsStream("/" + cells.head("resource").str)
        val resource = try new String(stream.readAllBytes(), java.nio.charset.StandardCharsets.UTF_8) finally stream.close()
        val start = resource.indexOf("module " + model)
        val end = resource.indexOf(");", start)
        require(start >= 0 && end > start, "UNSUPPORTED_PRIMITIVE_HEADER")
        val header = resource.substring(start, end+2)
        val implementation = if (passive(cells.head)) "// Passive marker or simulation-only protocol diagnostic.\n" else {
          val variants = bindings.filter(_.key.model == model)
          variants.zipWithIndex.map { case (b,i) =>
            val condition = b.key.parameters.toSeq.sortBy(_._1).map { case (n,v) =>
              require(v >= 0, "UNSUPPORTED_NEGATIVE_CELL_PARAMETER")
              s"($n == ${math.max(64,v.bitLength)}'d$v)"
            }.mkString(" && ")
            s"${if(i == 0) "if" else "else if"} ($condition) begin : variant_$i\n" +
              s"  (* dont_touch = \"yes\", keep_hierarchy = \"yes\" *) ${b.module} mapped (${b.pins.toSeq.sortBy(_._1).map { case (logical,pin) => s".$pin($logical)" }.mkString(",")});\nend"
          }.mkString("\n") + "\nelse begin : unmapped\n  CHISEL_ASYNC_UNMAPPED_PARAMETERIZATION reject();\nend\n"
        }
        Files.writeString(dest.resolve(model + ".sv"), "// ASIC mapping view; generated from explicit technology bindings.\n" + header + "\n" + implementation + "endmodule\n")
      }
      Files.writeString(dest.resolve("filelist.f"), names.sorted.mkString("\n") + "\n")
      Files.copy(simulation.resolve("contract.json"), dest.resolve("timing-intent.json"))
      val record = ujson.Obj("schema" -> "chisel-async-asic-mapping-v1", "top" -> manifest("top"),
        "status" -> "mapped-unqualified", "timing_closure" -> "required; no physical validation performed",
        "bindings" -> ujson.Arr.from(bindings.map(b => ujson.Obj("cell" -> jsonKey(b.key), "module" -> b.module,
          "pins" -> ujson.Obj.from(b.pins.toSeq.sortBy(_._1).map { case(k,v) => k -> ujson.Str(v) }), "provenance" -> b.provenance))),
        "files_sha256" -> ujson.Obj.from((names :+ "timing-intent.json").sorted.map(n => n -> ujson.Str(sha(dest.resolve(n))))))
      Files.writeString(dest.resolve("mapping.json"), ujson.write(record, indent=2) + "\n")
      dest
    }
  }
}
