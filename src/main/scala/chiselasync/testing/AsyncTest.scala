// SPDX-License-Identifier: Apache-2.0
package chiselasync.testing

import chisel3._
import chiselasync.core.AsyncModule
import chiselasync.metadata.{DelayBounds, BundledTiming, ExportDesign}
import java.nio.file.{Files, Path}
import java.nio.charset.StandardCharsets.UTF_8
import scala.jdk.CollectionConverters._

/** Event-driven tests shipped in the library JAR. Requires iverilog and vvp on PATH.
  * No Python, cocotb or repository checkout. This is digital testing, not timing closure.
  * Use [[check]] for independent input/output token streams and [[run]] for custom
  * concurrent stimulus or reset scenarios. Both require a clockless design with
  * four-phase, two-phase or RTZ dual-rail top-level channels and an active-high `reset` port.
  *
  * The helper checks protocol and payload behavior; it does not run the repository's
  * structural export validator or qualify analog behavior. Encoding converters
  * retain nominal delays; phase adapters and QDI cells use their
  * declared bounds. Optional pin delays model wire skew and additional closure delay.
  */
object AsyncTest {
  /** One producer's ordered tokens. `port` is the flattened RTL channel name;
    * each map supplies every payload leaf, e.g. `Map("in_bits" -> BigInt(7))`.
    * Values represent unsigned bit patterns, including two's-complement signed data.
    */
  final case class Input(port: String, tokens: Seq[Map[String, BigInt]],
      layout: Map[String, (Int, Boolean)] = Map.empty)
  object Input {
    /** Chisel literals, including Bundle/Vec literals and signed leaves. Width and
      * signedness must match the elaborated port; no flattened signal names needed.
      */
    def literals[T <: Data](port: String, tokens: Seq[T]): Input = {
      val (values, layout) = literalTokens(port, tokens)
      Input(port, values, layout)
    }
  }
  /** One consumer's exact expected sequence, using the same leaf/bit convention as
    * [[Input]]. Derive values from an independent software oracle.
    */
  final case class Output(port: String, tokens: Seq[Map[String, BigInt]],
      layout: Map[String, (Int, Boolean)] = Map.empty)
  object Output {
    /** Expected typed literals, computed from an independent software function. */
    def literals[T <: Data](port: String, tokens: Seq[T]): Output = {
      val (values, layout) = literalTokens(port, tokens)
      Output(port, values, layout)
    }
  }
  private def literalTokens(port: String, tokens: Seq[Data]): (Seq[Map[String, BigInt]], Map[String, (Int, Boolean)]) = {
    def leaves(value: Data, name: String): Seq[(String, Bits)] = value match {
      case r: Record => r.elements.toSeq.flatMap { case (n,v) => leaves(v, s"${name}_$n") }
      case v: Vec[_] => v.zipWithIndex.flatMap { case (x,i) => leaves(x, s"${name}_$i") }.toSeq
      case b: Bits => Seq(name -> b)
      case _ => throw new IllegalArgumentException(s"UNSUPPORTED_TEST_LITERAL: $name")
    }
    require(tokens.nonEmpty, "EMPTY_ASYNC_TEST")
    val fields = tokens.map(leaves(_, s"${port}_bits"))
    val layouts = fields.map(_.map { case (n,b) =>
      require(b.isWidthKnown && b.getWidth > 0 && b.litOption.nonEmpty, s"FULLY_SPECIFIED_LITERAL_REQUIRED: $n")
      n -> (b.getWidth, b.isInstanceOf[SInt])
    }.toMap)
    require(layouts.distinct.size == 1, "TEST_LITERAL_SHAPE_MISMATCH")
    (fields.map(_.map { case (n,b) => n -> (b.litValue & ((BigInt(1) << b.getWidth) - 1)) }.toMap), layouts.head)
  }

  /** Extra inertial propagation at one primitive input. `cell` uses registered
    * child/primitive IDs, e.g. "add.long_hold", never compiler-generated names.
    * Delays are added to the nominal path, not absorbed into its existing budget.
    */
  final case class PinDelay(cell: String, pin: String, delay: DelayBounds, closure: Boolean = false)
  object PinDelay {
    /** Additional time until a ClosingLatch stops tracking input. This bounded
      * digital closure experiment does not model analog setup/hold or metastability.
      * Both edges of `closed` are delayed, including subsequent reopening.
      */
    def closingAperture(cell: String, delay: DelayBounds): PinDelay = PinDelay(cell, "closed", delay, closure = true)
  }
  /** Installation and explicit nonideal-wire experiments. Default wires stay ideal. */
  final case class Options(pinDelays: Seq[PinDelay] = Seq.empty, simulator: Simulator = Simulator())
  /** A completed seed. The directory contains the testbench, selected delays,
    * compiler/simulator logs, and `result.json` with observed transfer counts.
    * `variedCells` counts cells assigned a delay for this seed, including corner seeds.
    */
  final case class Result(seed: Long, directory: Path, variedCells: Int)
  private def nodes(node: ujson.Value): Seq[ujson.Value] =
    Seq(node) ++ node("children").arr.toSeq.flatMap(c => nodes(c("contract")))
  private def flat(source: String): String = source.split(">").last.replace('.', '_').replace('[', '_').replace("]", "")

  /** Independent source/sink streams with randomized pauses and exact payload checks.
    * Token maps name every flattened data leaf, e.g. Map("in_bits_a" -> 3, "in_bits_b" -> 5).
    * Values are unsigned bit patterns (encode signed payloads in two's complement).
    * All channels must appear once, and every stream must contain at least one token.
    * Held data, handshake order, extra output and bounded completion are monitored.
    *
    * @param gen fresh design to elaborate once for the entire call
    * @param inputs independent producer streams, driven concurrently
    * @param outputs independent expected consumer streams, checked concurrently
    * @param seeds distinct seeds; 1 selects all-minimum delays, 2 all-maximum,
    *   and others draw per-cell delays and pauses deterministically
    * @param directory evidence root; use a fresh directory to retain each campaign
    * @param options explicit simulator paths and optional additional primitive input delays
    * @return one result per successful seed; a failed seed throws with its log path
    */
  def check(gen: => AsyncModule, inputs: Seq[Input], outputs: Seq[Output],
      seeds: Seq[Long] = Seq(1, 2, 3), directory: Path = Files.createTempDirectory("chisel-async-test-"),
      options: Options = Options()): Seq[Result] = {
    require(inputs.nonEmpty && outputs.nonEmpty && inputs.forall(_.tokens.nonEmpty) && outputs.forall(_.tokens.nonEmpty), "EMPTY_ASYNC_TEST")
    run(gen, seeds, directory, options = options) { context => ProtocolTest.stimulus(context, inputs, outputs) }
  }

  /** Reflected flattened top-level port; `input` means driven by the testbench. */
  final case class Port(name: String, width: Int, input: Boolean, signed: Boolean = false)
  /** Names/widths available to a custom SV body, after automatic reset initialization. */
  final case class Context(seed: Long, ports: Seq[Port], channels: Seq[String],
      protocols: Map[String, String] = Map.empty)

  /** Custom concurrent SV stimulus, with automatic top-level handshake/hold monitors.
    * Composition cells without a tighter exported envelope use routingCells.
    * Guard delays are held fixed; per-cell delays are independently drawn inside bounds.
    * Seed 1/2 select all-min/all-max corners; other seeds use java.util.Random.
    *
    * The body runs after a 1 us reset and 1 us settling interval. It must implement
    * its own payload oracle and return after useful traffic. Automatic monitors
    * observe states after 1 fs: leave every handshake phase visible longer than 1 fs.
    * A 10 ms simulated deadline and 90 s host timeout bound each simulation.
    *
    * @param gen fresh clockless design with only four-phase, two-phase or RTZ dual-rail top-level channels
    * @param seeds nonempty sequence of unique experiment seeds
    * @param directory export and per-seed evidence root
    * @param routingCells envelope for routing cells without a tighter exported bound;
    *   the `model` member does not override the seeded min/max selection
    * @param options explicit simulator paths and optional additional primitive input delays
    * @param body SystemVerilog statements using femtoseconds and [[Context]] port names;
    *   use `fork`/`join` for concurrent drivers and let the helper finish the simulation
    * @return results only after simulator success, observed output activity and the
    *   helper's completion marker; otherwise throws and retains available logs
    */
  def run(gen: => AsyncModule, seeds: Seq[Long], directory: Path,
      routingCells: DelayBounds = BundledTiming.Simulation.controls.a,
      options: Options = Options())(body: Context => String): Seq[Result] = {
    require(seeds.nonEmpty && seeds.distinct.size == seeds.size, "EMPTY_OR_DUPLICATE_SEEDS")
    val base = directory.toAbsolutePath
    Files.createDirectories(base)
    options.simulator.check(base.resolve("simulator"))
    val exported = base.resolve("export")
    ExportDesign.emit(gen, exported)
    val manifest = ujson.read(Files.readString(exported.resolve("contract.json")))("manifest")
    val allNodes = nodes(manifest("design"))
    val primitives = allNodes.flatMap(_("primitives").arr)
    val sources = Files.readAllLines(exported.resolve("filelist.f")).asScala.filter(_.trim.nonEmpty)
      .map(s => exported.resolve(s.trim).normalize().toString).toSeq
    val models = primitives.map(_("resource").str).distinct.map { resource =>
      val target = exported.resolve(resource.split('/').last)
      if (!Files.exists(target)) {
        val stream = Option(getClass.getResourceAsStream("/" + resource)).getOrElse(throw new IllegalArgumentException(s"Missing model $resource"))
        try Files.write(target, stream.readAllBytes()) finally stream.close()
      }
      target.toString
    }
    val topPorts = ujson.read(Files.readString(exported.resolve("ports.json")))("nodes")(0)
    val ports = topPorts("ports").arr.toSeq.map(p => Port(flat(p("source").str), p("width").num.toInt, p("direction").str == "input", p("signed").bool))
    require(!topPorts("ports").arr.exists(_("clock").bool), "ASYNC_TEST_REQUIRES_CLOCKLESS_TOP")
    val protocols = topPorts("channels").arr.toSeq.map(c => flat(c("source").str) -> c("protocol").str).toMap
    val descriptions = ProtocolTest.channels(ports, protocols)
    val channels = descriptions.map(_.name)
    require(channels.nonEmpty, "NO_ASYNC_CHANNELS")
    val outputChannels = descriptions.filter(!_.leaves.head.input).map(_.name)
    require(outputChannels.nonEmpty, "NO_ASYNC_OUTPUTS")
    val declarations = ports.map(p => s"${if(p.input) "reg" else "wire"} [${p.width-1}:0] ${p.name};").mkString("\n")
    val monitors = descriptions.map(ProtocolTest.monitor).mkString("\n")
    val pinTargets = PinDelays.resolve(manifest("design"), options.pinDelays)
    val instrumented = PinDelays.instrument(pinTargets, exported, base.resolve("instrumented"))
    val timingChecks = PinDelays.checks(manifest("design"), pinTargets)
    val simulationSources = (sources ++ models).distinct.map(s => instrumented.getOrElse(s, s))
    seeds.map { seed =>
      val dest = base.resolve(s"seed-$seed"); Files.createDirectories(dest)
      Files.deleteIfExists(dest.resolve("result.json"))
      val rng = new scala.util.Random(seed)
      val varied = allNodes.flatMap { node =>
        val stage = node("timing").arr.find(_("kind").str == "long-hold-bundling-v2")
        val phase = node("timing").arr.find(_("kind").str == "phase-conversion-v2")
        val qdi = node("timing").arr.find(_("kind").str == "qdi-digital-v1")
        val fixedBoundary = node("timing").arr.exists(_("kind").str == "encoding-boundary-v1")
        node("primitives").arr.filter(p => !fixedBoundary && p("parameters").obj.contains("DELAY_FS") &&
          !Set("request_delay", "output_delay", "request_guard", "return_guard").contains(p("id").str)).map { p =>
          var lo = routingCells.min.fs; var hi = routingCells.max.fs
          def use(b: ujson.Value): Unit = { lo = b("min_fs").str.toLong; hi = b("max_fs").str.toLong }
          qdi.foreach(t => use(t("cells")))
          phase.foreach(t => use(if (p("id").str == "history_close") t("history_closure") else t("cells")))
          stage.foreach { t =>
            p("id").str match {
              case "data_delay" => use(t("data_delay"))
              case "payload" => use(t("latch_delay"))
              case id if t("control_delays").obj.contains(id) => use(t("control_delays")(id))
              case _ =>
            }
          }
          node("timing").arr.filter(t => t("kind").str == "bundled-data-path-v1" &&
            t("delay_owner").arr.isEmpty && t("delay_cell").str == p("id").str).foreach(t => use(t("budget")))
          val delay = if(seed == 1) lo else if(seed == 2) hi else lo + (BigInt(rng.nextLong()).abs % (BigInt(hi) - lo + 1)).toLong
          (p("rtl_path").str, delay)
        }
      }
      val selectedPins = pinTargets.map { target =>
        val b = target.spec.delay
        val delay = if(seed == 1) b.min.fs else if(seed == 2) b.max.fs else
          b.min.fs + (BigInt(rng.nextLong()).abs % (BigInt(b.max.fs)-b.min.fs+1)).toLong
        target -> delay
      }
      val pinOverrides = selectedPins.map { case (t,d) =>
        s"defparam ${PinDelays.instance(t.primitive)}.${PinDelays.parameter(t.spec.pin)}=$d;"
      }.mkString("\n")
      val overrides = varied.map { case (path, delay) => s"defparam dut.${path.split('.').drop(1).mkString(".")}.DELAY_FS=$delay;" }.mkString("\n")
      Files.writeString(dest.resolve("delays.json"), ujson.write(ujson.Obj("seed" -> seed.toString,
        "algorithm" -> "java.util.Random; 1=min,2=max", "pins_fs" -> ujson.Obj.from(selectedPins.map { case (t,d) => s"${t.spec.cell}.${t.spec.pin}" -> ujson.Str(d.toString) }), "cells_fs" -> ujson.Obj.from(varied.map { case (p,d) => p -> ujson.Str(d.toString) })), indent=2))
      val stimulus = body(Context(seed, ports, channels, protocols))
      val tb = s"""module Testbench;
timeunit 1fs; timeprecision 1fs;
$declarations
${manifest("top").str} dut (${ports.map(p => s".${p.name}(${p.name})").mkString(",")});
$overrides
$pinOverrides
$monitors
$timingChecks
initial begin #10000000000000; $$fatal(1,"ASYNC_DEADLINE"); end
initial begin
${ports.filter(_.input).map(p => s"${p.name}=0;").mkString("\n")}
reset=1; #1000000000; reset=0; #1000000000;
$stimulus
${outputChannels.map(c => s"delivered_$c").mkString("if ((", " + ", ") == 0) $fatal(1,\"ASYNC_NO_ACTIVITY\");")}
${channels.map(c => s"$$display(\"CA_ACTIVITY channel=$c delivered=%0d\", delivered_$c);").mkString("\n")}
$$display("CA_TEST_PASS seed=$seed"); $$finish;
end
endmodule
"""
      Files.writeString(dest.resolve("testbench.sv"), tb, UTF_8)
      options.simulator.command(Seq(options.simulator.iverilog, "-g2012", "-s", "Testbench", "-o", "sim.vvp") ++ simulationSources ++ Seq("testbench.sv"), dest, "compile.log")
      options.simulator.command(Seq(options.simulator.vvp, "sim.vvp"), dest, "simulation.log")
      require(Files.readString(dest.resolve("simulation.log")).linesIterator.count(_ == s"CA_TEST_PASS seed=$seed") == 1, "MISSING_TEST_COMPLETION")
      Files.writeString(dest.resolve("result.json"), ujson.write(ujson.Obj("status" -> "PASS", "seed" -> seed.toString,
        "varied_cells" -> varied.size, "activity" -> ujson.Arr.from(Files.readString(dest.resolve("simulation.log"))
          .linesIterator.filter(_.startsWith("CA_ACTIVITY ")).toSeq)), indent=2))
      Result(seed, dest, varied.size)
    }
  }
}
