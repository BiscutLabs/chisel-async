// SPDX-License-Identifier: Apache-2.0
package chiselasync.testing

import java.nio.file.{Files, Path}

/** Creates simulation-only copies of resource bodies. Original export files and
  * contracts remain untouched. Parameters select delays per instance, including
  * instances of the same deduplicated module.
  */
private[testing] object PinDelays {
  final case class Target(spec: AsyncTest.PinDelay, primitive: ujson.Value)
  def inventory(node: ujson.Value, prefix: String = ""): Map[String, ujson.Value] =
    node("primitives").arr.map(p => (prefix + p("id").str) -> p).toMap ++
      node("children").arr.flatMap(c => inventory(c("contract"), prefix + c("id").str + "."))
  def parameter(pin: String): String = s"CA_TEST_${pin}_FS"
  def delayed(pin: String): String = s"ca_test_$pin"
  def instance(p: ujson.Value): String = "dut." + p("rtl_path").str.split('.').drop(1).mkString(".")

  def resolve(design: ujson.Value, specs: Seq[AsyncTest.PinDelay]): Seq[Target] = {
    require(specs.map(s => s.cell -> s.pin).distinct.size == specs.size, "DUPLICATE_PIN_DELAY")
    val cells = inventory(design)
    specs.map { s =>
      val p = cells.getOrElse(s.cell, throw new IllegalArgumentException(s"UNKNOWN_DELAY_CELL: ${s.cell}"))
      require(p("view").str == "behavioral", "PIN_DELAY_REQUIRES_ACTIVE_CELL")
      require(s.pin != "reset" && p("ports").arr.exists(v => v("name").str == s.pin && v("direction").str == "input"),
        s"PIN_DELAY_REQUIRES_INPUT: ${s.cell}.${s.pin}")
      if (s.closure) require(p("model").str == "ChiselAsyncClosingLatch_v1" && s.pin == "closed", "CLOSURE_REQUIRES_CLOSING_LATCH")
      Target(s, p)
    }
  }

  def instrument(targets: Seq[Target], exported: Path, directory: Path): Map[String, String] = {
    if (targets.nonEmpty) Files.createDirectories(directory)
    targets.groupBy(_.primitive("model").str).map { case (model, ts) =>
      val filename = ts.head.primitive("resource").str.split('/').last
      val source = Files.readString(exported.resolve(filename))
      val end = source.indexOf(");") + 2
      require(end > 1 && source.contains("timeprecision 1fs;"), s"UNSUPPORTED_INSTRUMENTATION_MODEL: $model")
      val pins = ts.map(_.spec.pin).distinct.sorted
      val split = "\\)\\s*\\(input".r.findFirstMatchIn(source.take(end))
        .getOrElse(throw new IllegalArgumentException(s"UNSUPPORTED_INSTRUMENTATION_HEADER: $model"))
      val header = source.take(split.start) + pins.map(p => s", parameter time ${parameter(p)}=0").mkString + source.substring(split.start, end)
      var body = source.substring(end)
      pins.foreach(p => body = body.replaceAll("\\b" + p + "\\b", delayed(p)))
      val aliases = pins.map { p =>
        s"wire [$$bits($p)-1:0] ${delayed(p)};\nassign #${parameter(p)} ${delayed(p)} = $p;"
      }.mkString("\n")
      body = body.replace("timeprecision 1fs;", "timeprecision 1fs;\n" + aliases)
      val dest = directory.resolve(filename)
      Files.writeString(dest, header + body)
      exported.resolve(filename).toString -> dest.toString
    }
  }

  /** Observe the actual delayed pins, not the requested test parameters. */
  def checks(design: ujson.Value, targets: Seq[Target]): String = {
    val instrumented = targets.groupBy(_.primitive("model").str).view.mapValues(_.map(_.spec.pin).toSet).toMap
    def pin(p: ujson.Value, name: String): String = instance(p) + "." +
      (if (instrumented.getOrElse(p("model").str, Set.empty[String])(name)) delayed(name) else name)
    var index = 0
    def before(early: String, event: String, active: String, diagnostic: String): String = {
      index += 1
      s"""time ca_early_$index = 0;
always @(posedge $early) ca_early_$index = $$time;
always @($event) begin
  #0;
  if (!reset && ($active) && ($early !== 1'b1 || ca_early_$index >= $$time))
    $$fatal(1,"$diagnostic");
end"""
    }
    def visit(node: ujson.Value): Seq[String] = {
      val cells = node("primitives").arr.map(p => p("id").str -> p).toMap
      val local = node("timing").arr.flatMap { t => t("kind").str match {
        case "long-hold-fork-v1" =>
          val p = cells("long_hold"); val early = pin(p, "b"); val late = pin(p, "a")
          Seq(before(early,s"negedge $late","1'b1",s"TIMING_LONG_HOLD_FORK ${p("rtl_path").str}"))
        case "phase-conversion-v2" if t("direction").str == "four-to-two" =>
          val history = pin(cells("history"), "closed")
          val request = instance(cells("request_guard")) + ".q"
          Seq(before(history,request,"1'b1",s"TIMING_HISTORY_CLOSURE ${node("rtl_path").str}"))
        case _ => Seq.empty
      }}
      local.toSeq ++ node("children").arr.flatMap(c => visit(c("contract")))
    }
    if (targets.isEmpty) "" else visit(design).mkString("\n")
  }
}
