// SPDX-License-Identifier: Apache-2.0
package chiselasync.openroad

/** The standard cells a technology adapter is built from, by role.
  *
  * Every adapter is ordinary structural Verilog over these cells. The state
  * gate of a C-element is the one cell whose output feeds back to its own
  * input: `q = S | q & H` (AO21) or `qn = ~(q & H | S)` followed by an
  * inverter where the library has only the inverting form (AOI21).
  */
final case class Technology(
    name: String,
    inv: Technology.Cell,
    and2: Technology.Cell,
    or2: Technology.Cell,
    stateGate: Technology.Cell,
    stateGateInverting: Boolean,
    latch: Technology.Latch,
    delay: Technology.Cell,
    /** A fast-corner lower bound on one `delay` cell's propagation, used only to
      * size a chain: a matched delay must hold where cells are quickest. The
      * routed check, not this number, decides whether a chain is long enough.
      */
    delayStageFs: Long)

object Technology {
  /** Blackbox declarations of every cell an adapter can use, so the mapped RTL
    * can be read and flattened without the technology's Verilog models.
    */
  def stubs(t: Technology): String = {
    val cells = Seq(t.inv, t.and2, t.or2, t.stateGate, t.delay).map(c => c.module -> (c.ins.map("input " + _) :+ s"output ${c.out}")) :+
      (t.latch.module -> (Seq(t.latch.d, t.latch.enable).map("input " + _) ++ t.latch.resetN.map("input " + _) :+ s"output ${t.latch.q}"))
    cells.distinct.map { case (m, ports) => s"(* blackbox *) module $m (${ports.mkString(", ")}); endmodule" }.mkString("\n") + "\n"
  }

  /** `ins` are the input pin names in order, `out` the output pin. */
  final case class Cell(module: String, ins: Seq[String], out: String)
  /** A transparent latch. `enable` is open-low when `openLow`, else open-high;
    * `resetN` names an active-low reset pin if the cell has one.
    */
  final case class Latch(module: String, d: String, enable: String, q: String, openLow: Boolean,
      resetN: Option[String])

  val asap7 = Technology(
    name = "asap7",
    inv = Cell("INVx1_ASAP7_75t_R", Seq("A"), "Y"),
    and2 = Cell("AND2x2_ASAP7_75t_R", Seq("A", "B"), "Y"),
    or2 = Cell("OR2x2_ASAP7_75t_R", Seq("A", "B"), "Y"),
    // Y = A1 & A2 | B
    stateGate = Cell("AO21x1_ASAP7_75t_R", Seq("A1", "A2", "B"), "Y"),
    stateGateInverting = false,
    latch = Latch("DLLx1_ASAP7_75t_R", "D", "CLK", "Q", openLow = true, resetN = None),
    delay = Cell("HB4xp67_ASAP7_75t_R", Seq("A"), "Y"),
    delayStageFs = 25000L)

  private def gf(cell: String) = "gf180mcu_fd_sc_mcu7t5v0__" + cell
  val gf180 = Technology(
    name = "gf180",
    inv = Cell(gf("inv_1"), Seq("I"), "ZN"),
    and2 = Cell(gf("and2_1"), Seq("A1", "A2"), "Z"),
    or2 = Cell(gf("or2_1"), Seq("A1", "A2"), "Z"),
    // ZN = ~(A1 & A2 | B)
    stateGate = Cell(gf("aoi21_1"), Seq("A1", "A2", "B"), "ZN"),
    stateGateInverting = true,
    latch = Latch(gf("latrnq_1"), "D", "E", "Q", openLow = false, resetN = Some("RN")),
    delay = Cell(gf("dlyd_1"), Seq("I"), "Z"),
    delayStageFs = 1000000L)

  val all: Map[String, Technology] = Seq(asap7, gf180).map(t => t.name -> t).toMap
}
