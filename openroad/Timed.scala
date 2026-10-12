// SPDX-License-Identifier: Apache-2.0
package chiselasync.openroad

import java.nio.file.{Files, Paths}

/** A routed netlist with its delays in it, for event simulation without SDF.
  *
  * Usage: Timed NETLIST DELAYS OUTPUT
  *
  * DELAYS is delays.tcl's table: per cell output, the worst rise and fall
  * delay in ps, wire to its loads included. Each such output now drives a
  * fresh net, and `assign #(rise, fall)` drives the original net from it: one
  * inertial delay per cell output rather than per arc, which is what an event
  * simulator without SDF can carry.
  */
object Timed {
  def main(args: Array[String]): Unit = {
    require(args.length == 3, "Usage: Timed NETLIST DELAYS OUTPUT")
    var text = Files.readString(Paths.get(args(0)))
    val rows = Files.readAllLines(Paths.get(args(1))).toArray(Array.empty[String]).toSeq
      .map(_.split('\t')).filter(_.length == 4)
    val assigns = new StringBuilder
    val wires = new StringBuilder
    var n = 0
    rows.foreach { case Array(inst, pin, rise, fall) =>
      val start = Seq(s"\\$inst ", s" $inst (", s" $inst(").map(text.indexOf).filter(_ >= 0).minOption
        .getOrElse(throw new IllegalArgumentException(s"TIMED_INSTANCE_NOT_FOUND: $inst"))
      val end = text.indexOf(");", start)
      val body = text.substring(start, end)
      val conn = ("\\." + java.util.regex.Pattern.quote(pin) + "\\s*\\(\\s*([^()]*?)\\s*\\)").r
      conn.findFirstMatchIn(body).filter(_.group(1).nonEmpty).foreach { m =>
        val net = m.group(1)
        val raw = s"ca_timed_$n"; n += 1
        text = text.substring(0, start) + body.substring(0, m.start) + s".$pin($raw)" + body.substring(m.end) + text.substring(end)
        def ps(v: String) = BigDecimal(v).setScale(3, BigDecimal.RoundingMode.HALF_UP).toString
        wires ++= s"  wire $raw;\n"
        assigns ++= s"  assign #(${ps(rise)}, ${ps(fall)}) ${if (net.startsWith("\\")) net + " " else net} = $raw;\n"
      }
    }
    val close = text.lastIndexOf("endmodule")
    text = text.substring(0, close) + assigns + text.substring(close)
    val header = text.indexOf(");", text.indexOf("module ")) + 2
    text = "`timescale 1ps/1fs\n" + text.substring(0, header) + "\n" + wires + text.substring(header)
    Files.writeString(Paths.get(args(2)), text)
    println(s"Timed: $n cell outputs delayed")
  }
}
