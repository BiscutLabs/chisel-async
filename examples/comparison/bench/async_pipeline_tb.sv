`timescale 1ps/1fs
// AddPipeline, four-phase, with an eager environment: the producer raises the
// next request as soon as the last one is acknowledged, the consumer
// acknowledges at once. Reports the steady-state time per token.
module tb;
  `include "jobs.svh"
  reg reset = 1, in_req = 0, out_ack = 0;
  reg [7:0] a = 0, b = 0;
  wire in_ack, out_req;
  wire [8:0] out_bits;
  AddPipeline dut(.reset(reset), .in_req(in_req), .in_bits_a(a), .in_bits_b(b), .in_ack(in_ack),
    .out_req(out_req), .out_bits(out_bits), .out_ack(out_ack));
  integer sent, got = 0, errors = 0;
  realtime first, last;
  initial begin
    // Long enough for reset to flush the longest matched delay line.
    #2000000 reset = 0; #20000;
    for (sent = 0; sent < TOKENS; sent = sent + 1) begin
      a = op_a(sent); b = op_b(sent); in_req = 1; wait (in_ack); in_req = 0; wait (!in_ack);
    end
  end
  always begin
    wait (out_req);
    if (out_bits !== op_a(got) + op_b(got)) errors = errors + 1;
    if (got == 0) first = $realtime;
    last = $realtime; got = got + 1;
    out_ack = 1; wait (!out_req); out_ack = 0;
  end
  initial begin
    wait (got == TOKENS);
    $display("CA_SIM design=AddPipeline tokens=%0d errors=%0d ps_per_token=%0.1f", TOKENS, errors, (last - first) / (TOKENS - 1));
    $finish;
  end
  initial begin #100000000000; $display("CA_SIM TIMEOUT tokens=%0d", got); $finish; end
endmodule
