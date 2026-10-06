// SPDX-License-Identifier: Apache-2.0
// Comparison-only digital cells. Time unit 1 ns, precision 1 ps.
// Each +d<ID> value is recorded by the Python runner. No physical cell claim.
`timescale 1ns/1ps
module ComparisonGate #(parameter ID=0, OP=0)(input a, b, output q);
  integer delay_ns = 1;
  initial if (!$value$plusargs($sformatf("d%0d=%%d", ID), delay_ns))
    $fatal(1, "MISSING_CELL_DELAY id=%0d", ID);
  // Primitive inertial delay. OP: inverter, AND, OR.
  assign #(delay_ns) q = OP == 0 ? ~a : OP == 1 ? a & b : a | b;
endmodule

module ComparisonC #(parameter ID=0)(input reset, a, b, output q);
  integer delay_ns = 1;
  initial if (!$value$plusargs($sformatf("d%0d=%%d", ID), delay_ns))
    $fatal(1, "MISSING_CELL_DELAY id=%0d", ID);
  // Named state-cell boundary. Unanimity/hold characteristic equation with
  // inertial output delay. Reset must be held through the stated quiescence time.
  assign #(delay_ns) q = reset ? 1'b0 : ((a & b) | (q & (a | b)));
endmodule

module ComparisonLatch #(parameter ID=0, WIDTH=40, RESET_VALUE=0)(
  input reset, enable, input [WIDTH-1:0] d, output [WIDTH-1:0] q
);
  integer delay_ns = 1;
  reg [WIDTH-1:0] stored;
  initial if (!$value$plusargs($sformatf("d%0d=%%d", ID), delay_ns))
    $fatal(1, "MISSING_CELL_DELAY id=%0d", ID);
  always @(reset or enable or d)
    if (reset) stored <= RESET_VALUE;
    else if (enable) stored <= d;
  // Capture is level-sensitive; propagation from internal state is inertial.
  // This differs from the captured-value NBA model in controller_race.py.
  assign #(delay_ns) q = stored;
endmodule

module ComparisonDelay #(parameter DELAY_NS=1)(input d, output q);
  assign #(DELAY_NS) q = d;
endmodule
