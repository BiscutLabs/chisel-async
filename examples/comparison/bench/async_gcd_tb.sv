`timescale 1ps/1fs
// Gcd, four-phase, eager environment. Reports the time from the first request
// to the last result over the job list, and the subtractions that took.
module tb;
  `include "jobs.svh"
  reg reset = 1, in_req = 0, out_ack = 0;
  reg [7:0] a = 0, b = 0;
  wire in_ack, out_req;
  wire [7:0] out_bits;
  Gcd dut(.reset(reset), .in_req(in_req), .in_bits_a(a), .in_bits_b(b), .in_ack(in_ack),
    .out_req(out_req), .out_bits(out_bits), .out_ack(out_ack));
  integer sent, got = 0, errors = 0, total = 0, i;
  realtime first, last;
  initial begin
    for (i = 0; i < JOBS; i = i + 1) total = total + steps(job_a(i), job_b(i));
    // Long enough for reset to flush the longest matched delay line.
    #2000000 reset = 0; #20000;
    first = $realtime;
    for (sent = 0; sent < JOBS; sent = sent + 1) begin
      a = job_a(sent); b = job_b(sent); in_req = 1; wait (in_ack); in_req = 0; wait (!in_ack);
    end
  end
  always begin
    wait (out_req);
    if (out_bits !== gcd(job_a(got), job_b(got))) errors = errors + 1;
    last = $realtime; got = got + 1;
    out_ack = 1; wait (!out_req); out_ack = 0;
  end
  initial begin
    wait (got == JOBS);
    $display("CA_SIM design=Gcd jobs=%0d subtractions=%0d errors=%0d ps_total=%0.1f", JOBS, total, errors, last - first);
    $finish;
  end
  initial begin #100000000000; $display("CA_SIM TIMEOUT jobs=%0d", got); $finish; end
endmodule
