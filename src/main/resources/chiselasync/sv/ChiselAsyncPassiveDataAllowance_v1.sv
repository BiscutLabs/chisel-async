// SPDX-License-Identifier: Apache-2.0
// Whole-transform inertial simulation allowance, NOT a physical delay line.
// No reset/valid mask. X/Z and invalid payload propagate. Physical view: q=a.
module ChiselAsyncPassiveDataAllowance_v1 #(
  parameter integer WIDTH=1,
  parameter time DELAY_FS=0
)(input wire [WIDTH-1:0] a, output wire [WIDTH-1:0] q);
  timeunit 1fs;
  timeprecision 1fs;
  initial if (WIDTH<1 || DELAY_FS>64'h7fffffffffffffff)
    $fatal(1,"INVALID_PASSIVE_ALLOWANCE_PARAMETERS");
  assign #DELAY_FS q = a;
endmodule
