// SPDX-License-Identifier: Apache-2.0
`timescale 1ns/1ps
module ComparisonCellBench;
  parameter D=10;
  reg reset=0, gate_a=0, c_a=0, c_b=0, enable=0;
  reg [39:0] d=0;
  wire gate_q, c_q;
  wire [39:0] q;
  realtime started;
  integer gate_edges=0, before_edges;
  ComparisonGate #(.ID(0),.OP(0)) inv(.a(gate_a),.b(1'b0),.q(gate_q));
  ComparisonC #(.ID(1)) c(.reset(reset),.a(c_a),.b(c_b),.q(c_q));
  ComparisonLatch #(.ID(2)) latch(.reset(reset),.enable(enable),.d(d),.q(q));
  always @(gate_q) gate_edges=gate_edges+1;
  initial begin
    #1 reset=1;
    #(D+1);
    if (gate_q!==1 || c_q!==0 || q!==0) $fatal(1,"CELL_RESET");
    reset=0;
    // Configured delay must actually affect the simulation.
    started=$realtime; gate_a=1;
    wait(gate_q===0);
    if ($realtime-started!=D) $fatal(1,"CELL_GATE_DELAY");
    gate_a=0; #(D+1);
    before_edges=gate_edges;
    gate_a=1; #(D/2.0); gate_a=0; #(D+1);
    if (gate_edges!=before_edges || gate_q!==1) $fatal(1,"CELL_INERTIAL_PULSE");
    c_a=1; #(D+1);
    if (c_q!==0) $fatal(1,"CELL_C_HOLD_LOW");
    started=$realtime; c_b=1; wait(c_q===1);
    if ($realtime-started!=D) $fatal(1,"CELL_C_RISE_DELAY");
    c_a=0; #(D+1);
    if (c_q!==1) $fatal(1,"CELL_C_HOLD_HIGH");
    started=$realtime; c_b=0; wait(c_q===0);
    if ($realtime-started!=D) $fatal(1,"CELL_C_FALL_DELAY");
    started=$realtime; enable=1; d=40'hABCDEF1234; wait(q===d);
    if ($realtime-started!=D) $fatal(1,"CELL_LATCH_DELAY");
    enable=0; d=0; #(D+1);
    if (q!==40'hABCDEF1234) $fatal(1,"CELL_LATCH_HOLD");
    reset=1; #(D+1);
    if (q!==0 || c_q!==0) $fatal(1,"CELL_RESET_RESTART");
    $display("CELL_PASS delay=%0d",D);
    $finish;
  end
  initial begin #1000; $fatal(1,"CELL_DEADLINE"); end
endmodule
