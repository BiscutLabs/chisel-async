// SPDX-License-Identifier: Apache-2.0
// Independently written reference for Sparso/Furber Fig. 2.8/2.9:
// c = C(in_req, !out_ack), opaque when c=1, req/ack derived from c.
// Two explicit output buffers provide the declared bundled-data forward/hold
// margins. They are model assumptions, not a delay-insensitive datapath claim.
`timescale 1ns/1ps
module MullerComparisonStage #(parameter BASE=0, FORWARD_NS=40, ACK_NS=20)(
  input reset, in_req, input [39:0] in_bits, output in_ack,
  output out_req, output [39:0] out_bits, input out_ack
);
  wire back, c, enable;
  ComparisonGate #(.ID(BASE), .OP(0)) invert_ack(.a(out_ack), .b(1'b0), .q(back));
  ComparisonC #(.ID(BASE+1)) control(.reset(reset), .a(in_req), .b(back), .q(c));
  ComparisonGate #(.ID(BASE+2), .OP(0)) invert_enable(.a(c), .b(1'b0), .q(enable));
  ComparisonLatch #(.ID(BASE+3)) data(.reset(reset), .enable(enable), .d(in_bits), .q(out_bits));
  ComparisonDelay #(.DELAY_NS(FORWARD_NS)) forward_margin(.d(c), .q(out_req));
  ComparisonDelay #(.DELAY_NS(ACK_NS)) hold_margin(.d(c), .q(in_ack));
endmodule
