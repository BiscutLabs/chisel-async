// SPDX-License-Identifier: Apache-2.0
package chiselasync.testing

import java.nio.file.{Files, Path, Paths}
import java.util.concurrent.TimeUnit

/** Icarus executables used by the public test helper. Explicit paths take
  * precedence over CA_IVERILOG/CA_VVP, then PATH. No shell is used.
  */
final case class Simulator(iverilog: String = sys.env.getOrElse("CA_IVERILOG", "iverilog"),
    vvp: String = sys.env.getOrElse("CA_VVP", "vvp")) {
  private[testing] def command(args: Seq[String], cwd: Path, log: String): Unit = {
    val file = cwd.resolve(log)
    val process = try new ProcessBuilder(args: _*).directory(cwd.toFile).redirectErrorStream(true).redirectOutput(file.toFile).start()
      catch { case e: java.io.IOException => throw new IllegalStateException(
        s"SIMULATOR_NOT_FOUND: ${args.head}. Install Icarus or set CA_IVERILOG and CA_VVP to its executables. Log: $file", e) }
    if (!process.waitFor(90, TimeUnit.SECONDS)) {
      process.destroyForcibly(); process.waitFor(5, TimeUnit.SECONDS)
      throw new IllegalStateException(s"SIMULATOR_TIMEOUT: $file")
    }
    require(process.exitValue() == 0, s"SIMULATOR_FAILED: $file\n${Files.readString(file)}")
  }

  /** Compile and execute a capability check for 1 fs timing, four-state values,
    * delayed assignments and event scheduling. This is an installation check,
    * not qualification of every library model on an untested simulator version.
    */
  def check(directory: Path = Files.createTempDirectory("chisel-async-simulator-")): Path = {
    Files.createDirectories(directory)
    command(Seq(iverilog, "-V"), directory, "iverilog-version.log")
    command(Seq(vvp, "-V"), directory, "vvp-version.log")
    val qualified = Seq("iverilog-version.log","vvp-version.log").forall(n => Files.readString(directory.resolve(n)).contains("version 13.0 "))
    if (!qualified) System.err.println("chisel-async: this Icarus version is unqualified; the installation probe does not replace the Icarus 13 regression suite.")
    Files.writeString(directory.resolve("capabilities.sv"), """module Capabilities;
timeunit 1fs; timeprecision 1fs;
reg a=0; wire q; reg [3:0] unknown=4'bx10z;
assign #5 q=a;
initial begin
  if (unknown[3] !== 1'bx || unknown[0] !== 1'bz) $fatal(1,"FOUR_STATE_REQUIRED");
  #10; if (q !== 0) $fatal(1,"DELAY_INITIALIZATION");
  a=1; #4; if (q !== 0) $fatal(1,"EARLY_DELAY");
  #2; if (q !== 1 || $time != 16) $fatal(1,"FEMTOSECOND_DELAY");
  $display("CA_SIMULATOR_CAPABILITIES_PASS"); $finish;
end
initial begin #100; $fatal(1,"CAPABILITY_TIMEOUT"); end
endmodule
""")
    command(Seq(iverilog, "-g2012", "-s", "Capabilities", "-o", "capabilities.vvp", "capabilities.sv"), directory, "compile.log")
    command(Seq(vvp, "capabilities.vvp"), directory, "simulation.log")
    require(Files.readString(directory.resolve("simulation.log")).linesIterator.count(_ == "CA_SIMULATOR_CAPABILITIES_PASS") == 1,
      "SIMULATOR_CAPABILITY_CHECK_FAILED")
    Files.writeString(directory.resolve("simulator.json"), ujson.write(ujson.Obj(
      "status" -> "CAPABILITIES_PASS", "qualified_version" -> qualified, "iverilog" -> iverilog, "vvp" -> vvp,
      "iverilog_version" -> Files.readString(directory.resolve("iverilog-version.log")),
      "vvp_version" -> Files.readString(directory.resolve("vvp-version.log"))), indent=2))
    directory
  }
}

/** Run from any consumer build: sbt "runMain chiselasync.testing.CheckSimulator". */
object CheckSimulator {
  def main(args: Array[String]): Unit = {
    require(args.length <= 1, "Usage: CheckSimulator [new-report-directory]")
    val output = if (args.nonEmpty) Paths.get(args(0)).toAbsolutePath else Files.createTempDirectory("chisel-async-simulator-")
    println(s"Icarus capability check passed: ${Simulator().check(output)}")
  }
}
