// SPDX-License-Identifier: Apache-2.0
// Atomic inertial digital cell. Delay is a model parameter, not physical timing.
module ChiselAsyncControlGate_v1 #(
  parameter integer WIDTH=1, OP=0,
  parameter time DELAY_FS=0,
  parameter [WIDTH-1:0] RESET_VALUE=0
)(input wire reset, input wire [WIDTH-1:0] a,b, output wire [WIDTH-1:0] q);
  timeunit 1fs;
  timeprecision 1fs;
  initial if (WIDTH<1 || OP<0 || OP>2 || DELAY_FS>64'h7fffffffffffffff)
    $fatal(1,"INVALID_CONTROL_GATE_PARAMETERS");
  assign #DELAY_FS q = reset ? RESET_VALUE : OP==0 ? a : OP==1 ? ~a : a|b;
endmodule
