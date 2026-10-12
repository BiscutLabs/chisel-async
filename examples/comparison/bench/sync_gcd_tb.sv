`timescale 1ps/1fs
// SyncGcd at PERIOD ps over the same jobs, output always ready.
module tb;
  `include "jobs.svh"
  reg clock = 0, reset = 1, in_valid = 0;
  reg [7:0] a = 0, b = 0;
  wire in_ready, out_valid;
  wire [7:0] out_bits;
  SyncGcd dut(.clock(clock), .reset(reset), .in_ready(in_ready), .in_valid(in_valid), .in_bits_a(a),
    .in_bits_b(b), .out_ready(1'b1), .out_valid(out_valid), .out_bits(out_bits));
  always #(`PERIOD / 2.0) clock = !clock;
  integer sent = 0, got = 0, errors = 0, total = 0, i;
  realtime first, last;
  initial begin
    for (i = 0; i < JOBS; i = i + 1) total = total + steps(job_a(i), job_b(i));
    repeat (4) @(posedge clock); #1 reset = 0;
    first = $realtime;
    while (sent < JOBS) begin
      a = job_a(sent); b = job_b(sent); in_valid = 1;
      @(posedge clock); if (in_ready) sent = sent + 1; #1;
    end
    in_valid = 0;
  end
  always @(posedge clock) if (!reset && out_valid) begin
    if (out_bits !== gcd(job_a(got), job_b(got))) errors = errors + 1;
    last = $realtime; got = got + 1;
  end
  initial begin
    wait (got == JOBS);
    $display("CA_SIM design=SyncGcd jobs=%0d subtractions=%0d errors=%0d ps_total=%0.1f", JOBS, total, errors, last - first);
    $finish;
  end
endmodule
