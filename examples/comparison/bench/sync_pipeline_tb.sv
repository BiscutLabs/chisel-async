`timescale 1ps/1fs
// SyncAddPipeline at PERIOD ps: inputs always valid, output always ready.
module tb;
  `include "jobs.svh"
  reg clock = 0, reset = 1, in_valid = 0;
  reg [7:0] a = 0, b = 0;
  wire in_ready, out_valid;
  wire [8:0] out_bits;
  SyncAddPipeline dut(.clock(clock), .reset(reset), .in_ready(in_ready), .in_valid(in_valid), .in_bits_a(a),
    .in_bits_b(b), .out_ready(1'b1), .out_valid(out_valid), .out_bits(out_bits));
  always #(`PERIOD / 2.0) clock = !clock;
  integer sent = 0, got = 0, errors = 0;
  realtime first, last;
  initial begin
    repeat (4) @(posedge clock); #1 reset = 0;
    while (sent < TOKENS) begin
      a = op_a(sent); b = op_b(sent); in_valid = 1;
      @(posedge clock); if (in_ready) sent = sent + 1; #1;
    end
    in_valid = 0;
  end
  always @(posedge clock) if (!reset && out_valid) begin
    if (out_bits !== op_a(got) + op_b(got)) errors = errors + 1;
    if (got == 0) first = $realtime;
    last = $realtime; got = got + 1;
  end
  initial begin
    wait (got == TOKENS);
    $display("CA_SIM design=SyncAddPipeline tokens=%0d errors=%0d ps_per_token=%0.1f", TOKENS, errors, (last - first) / (TOKENS - 1));
    $finish;
  end
endmodule
