// SPDX-License-Identifier: Apache-2.0
package chiselasync.openroad

import chiselasync.core.AsyncModule
import chiselasync.metadata.{AsicMapping, BundledTiming, ModelTime}
import java.nio.file.{Files, Path, Paths}
import scala.jdk.CollectionConverters._

/** Export a quickstart design for one technology: the library's own
  * `AsicMapping` with structural adapters for every required cell.
  *
  * Usage: Export DESIGN TECHNOLOGY OUTPUT CELL_MIN_PS CELL_MAX_PS DATA_MAX_PS
  *
  * Writes OUTPUT/asic (the library's mapped file list, mapping.json and
  * timing-intent.json), OUTPUT/design.sv (that file list concatenated, for
  * synthesis), OUTPUT/pins.json (where each primitive port lands on a cell) and
  * OUTPUT/cells.v (blackboxes for the cells, to read design.sv without a PDK).
  */
object Export {
  // The quickstart classes live in the empty package, which a named package
  // cannot import; construct them by name with the technology's policy.
  def designs(timing: BundledTiming, cell: ModelTime): Map[String, () => AsyncModule] = {
    def make(name: String, args: (Class[_], AnyRef)*): () => AsyncModule = () =>
      Class.forName(name).getConstructor(args.map(_._1): _*).newInstance(args.map(_._2): _*).asInstanceOf[AsyncModule]
    Map(
      "AddPipeline" -> make("AddPipeline", classOf[BundledTiming] -> timing),
      "Gcd" -> make("Gcd", classOf[BundledTiming] -> timing, classOf[ModelTime] -> cell))
  }

  def main(args: Array[String]): Unit = {
    require(args.length == 6, "Usage: Export DESIGN TECHNOLOGY OUTPUT CELL_MIN_PS CELL_MAX_PS DATA_MAX_PS")
    val Array(design, techName, output, cellMin, cellMax, dataMax) = args
    val tech = Technology.all.getOrElse(techName, throw new IllegalArgumentException(s"unknown technology $techName"))
    val timing = BundledTiming.simulation(ModelTime.ps(cellMin.toLong), ModelTime.ps(cellMax.toLong),
      ModelTime.ps(dataMax.toLong))
    val gen = designs(timing, ModelTime.ps(cellMin.toLong)).getOrElse(design,
      throw new IllegalArgumentException(s"unknown design $design"))
    val out = Paths.get(output).toAbsolutePath
    val plan = AsicMapping.prepare(gen(), out)

    val adapters = plan.required.zipWithIndex.map { case (r, i) =>
      val roles = r.instances.map(_.split('.').last.stripPrefix("ca_primitive_")).distinct
      val role = if (roles.forall(_ == "data_delay")) "data_delay" else roles.head
      val module = s"ca_${tech.name}_${r.key.model.stripPrefix("ChiselAsync").stripSuffix("_v1")}_$i"
      r -> Adapters.generate(r, role, module, tech, ModelTime.ps(cellMax.toLong).fs, ModelTime.ps(dataMax.toLong).fs)
    }
    val source = out.resolve(s"${tech.name}_adapters.v")
    Files.writeString(source, adapters.map(_._2.verilog).mkString("\n"))
    val bindings = adapters.map { case (r, a) =>
      AsicMapping.Binding(r.key, a.module, r.ports.map(p => p.name -> p.name).toMap,
        s"chisel-async openroad trial adapter for ${tech.name}: library gates, not a characterized cell")
    }
    val asic = plan.emit(bindings, Seq(source))

    val files = Files.readAllLines(asic.resolve("filelist.f")).asScala.map(_.trim).filter(_.nonEmpty)
    Files.writeString(out.resolve("design.sv"), files.map(f => Files.readString(asic.resolve(f))).mkString("\n"))
    val pins = ujson.Obj.from(adapters.flatMap { case (r, a) =>
      r.instances.map(inst => inst -> ujson.Obj.from(a.ports.toSeq.sortBy(_._1).map { case (port, pp) =>
        port -> ujson.Obj("path" -> ujson.Arr.from(pp.path), "arc" -> ujson.Arr.from(pp.arc))
      }))
    }.sortBy(_._1))
    Files.writeString(out.resolve("pins.json"), ujson.write(pins, indent = 2) + "\n")
    Files.writeString(out.resolve("cells.v"), Technology.stubs(tech))
    // What each primitive is, for drawing: C-element, latch, delay line or gate.
    val kinds = adapters.flatMap { case (r, _) =>
      val kind = r.key.model match {
        case "ChiselAsyncAsymmetricC_v1" | "ChiselAsyncCElement_v1" => "celement"
        case "ChiselAsyncClosingLatch_v1" | "ChiselAsyncLatch_v1" => "latch"
        case "ChiselAsyncControlGate_v1" if r.key.parameters("OP") == 0 &&
            r.key.parameters("DELAY_FS") > ModelTime.ps(cellMax.toLong).fs &&
            r.key.parameters("DELAY_FS") != ModelTime.ps(dataMax.toLong).fs &&
            !r.instances.forall(_.endsWith("ca_primitive_data_delay")) => "delay"
        case _ => "gate"
      }
      r.instances.map(i => s"{${i.substring(i.indexOf('.') + 1)} $kind}")
    }
    Files.writeString(out.resolve("kinds.tcl"), s"set ca_kinds {\n  ${kinds.sorted.mkString("\n  ")}\n}\n")
    println(s"$design on ${tech.name}: ${plan.required.size} cell specializations -> $asic")
  }
}
