// SPDX-License-Identifier: Apache-2.0
package chiselasync.metadata

import java.nio.file.{Files, Path}
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

/** Execute generated path checks against a supplied mapped design in OpenSTA.
  * OpenSTA and the technology files are optional external tools, not dependencies
  * of the library. A result covers the declared paths at this operating corner;
  * it does not establish hazard freedom, analog behavior or physical sign-off.
  */
object OpenSta {
  /** Complete, caller-owned input inventory for one operating corner.
    * `setup` establishes input slew, output load and any reviewed arc cuts/case
    * analysis. Its contents and all other files are hashed into the result.
    * Supply extracted SPEF for interconnect analysis; omission means cell-only STA.
    */
  final case class Corner(name: String, liberty: Seq[Path], netlist: Path,
      setup: Path, spef: Option[Path] = None)
  private def sha(path: Path): String = MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(path))
    .map(b => f"${b & 255}%02x").mkString
  private def quote(value: String): String = {
    require(!value.exists(c => "{}\\\n\r".contains(c)), "UNSAFE_STA_PATH")
    "{" + value + "}"
  }
  private def path(p: Path): String = quote(p.toAbsolutePath.normalize().toString.replace('\\','/'))

  /** Run an isolated OpenSTA process and retain its input hashes and complete log.
    * Missing paths, incomplete result inventories, altered generated scripts and
    * nonzero tool exits fail. The output directory must be fresh. Use a separate
    * call for each required PVT corner; the caller determines that corner set.
    */
  def check(constraints: Path, corner: Corner, directory: Path, command: Seq[String] = Seq("sta")): Path = {
    require(command.nonEmpty && command.head.nonEmpty, "EMPTY_STA_COMMAND")
    val manifest = constraints.resolve("constraints.json")
    val record = ujson.read(Files.readString(manifest))
    require(record("schema").str == "chisel-async-timing-constraints-v1", "UNSUPPORTED_CONSTRAINT_SCHEMA")
    require(record("files_sha256").obj.keySet == Set("constraints.sdc","preserve.tcl","check-timing.tcl"), "INCOMPLETE_CONSTRAINT_FILES")
    record("files_sha256").obj.foreach { case(n,h) => require(sha(constraints.resolve(n)) == h.str, "CONSTRAINT_FILE_CHANGED") }
    val rules = record("paths").arr.map(_.str).toSeq; val orders = record("orderings").arr.map(_.str).toSeq
    require(rules.nonEmpty && rules.distinct.size == rules.size && orders.distinct.size == orders.size, "EMPTY_OR_DUPLICATE_TIMING_INVENTORY")
    require(corner.name.matches("[A-Za-z0-9_.-]+") && corner.liberty.nonEmpty, "INVALID_STA_CORNER")
    require(record("top").str.matches("[A-Za-z_][A-Za-z0-9_$]*"), "INVALID_STA_TOP")
    val inputs = Seq(manifest, constraints.resolve("check-timing.tcl")) ++ corner.liberty ++ Seq(corner.netlist,corner.setup) ++ corner.spef.toSeq
    require(inputs.forall(Files.isRegularFile(_)), "STA_INPUT_MISSING")
    val hashes = inputs.map(p => p.toAbsolutePath.normalize().toString -> sha(p)).toMap
    require(!Files.exists(directory), "STA_OUTPUT_ALREADY_EXISTS")
    Files.createDirectories(directory)
    val output = directory.toAbsolutePath
    val result = ujson.Obj("schema" -> "chisel-async-sta-result-v1", "status" -> "RUNNING", "corner" -> corner.name,
      "scope" -> (if(corner.spef.nonEmpty) "declared paths with supplied SPEF" else "declared paths; cell-only, no extracted wires"),
      "command" -> ujson.Arr.from(command), "input_sha256" -> ujson.Obj.from(hashes.toSeq.sortBy(_._1).map { case(k,v) => k -> ujson.Str(v) }))
    def save(): Unit = { Files.writeString(output.resolve("result.json"),ujson.write(result,indent=2)+"\n"); () }
    save()
    try {
      val load = corner.liberty.map(p => s"read_liberty ${path(p)}").mkString("\n") +
        s"\nread_verilog ${path(corner.netlist)}\nlink_design -no_black_boxes ${quote(record("top").str)}\n" +
        s"set_cmd_units -time ns\nsource ${path(corner.setup)}\n" + corner.spef.map(p => s"read_spef ${path(p)}\nreport_parasitic_annotation -report_unannotated\n").getOrElse("") +
        s"source ${path(constraints.resolve("check-timing.tcl"))}\n"
      Files.writeString(output.resolve("run.tcl"),"if {[catch {\n"+load+
        "} message options]} {puts stderr \"CA_STA_FAILURE: $message\"; exit 1}\nexit 0\n")
      val log = output.resolve("opensta.log")
      val process = new ProcessBuilder((command ++ Seq("-exit",output.resolve("run.tcl").toString)): _*)
        .directory(output.toFile).redirectErrorStream(true).redirectOutput(log.toFile).start()
      if (!process.waitFor(120,TimeUnit.SECONDS)) {
        process.destroyForcibly(); process.waitFor(5,TimeUnit.SECONDS)
        throw new IllegalStateException("STA_TIMEOUT")
      }
      val text = Files.readString(log)
      require(process.exitValue()==0 && !text.linesIterator.exists(l => l.startsWith("Error:") || l.contains("CA_STA_FAILURE:")),
        s"STA_FAILED: $log\n$text")
      def inventory(prefix: String): Seq[String] = text.linesIterator.filter(_.startsWith(prefix))
        .map(_.stripPrefix(prefix).takeWhile(_ != ' ')).toSeq
      require(inventory("CA_TIMING_PATH id=") == rules && inventory("CA_TIMING_ORDER id=") == orders,
        "STA_INCOMPLETE_RESULT_INVENTORY")
      require(text.linesIterator.count(_ == s"CA_TIMING_PASS paths=${rules.size} orderings=${orders.size}")==1, "STA_MISSING_COMPLETION")
      require(inputs.forall(p => sha(p)==hashes(p.toAbsolutePath.normalize().toString)), "STA_INPUT_CHANGED")
      result("status") = "CHECKED_DECLARED_PATHS"
      result("paths") = record("paths"); result("orderings") = record("orderings")
      result("log_sha256") = sha(log)
      save(); output
    } catch { case error: Exception => result("status")="ERROR"; result("error")=error.toString; save(); throw error }
  }
}
