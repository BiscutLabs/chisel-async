// SPDX-License-Identifier: Apache-2.0
module ChiselAsyncResetlessClosingLatch_v1 #(
  parameter integer WIDTH=1,
  parameter time DELAY_FS=0
)(input wire closed, input wire [WIDTH-1:0] d, output wire [WIDTH-1:0] q);
  timeunit 1fs;
  timeprecision 1fs;
  reg [WIDTH-1:0] stored;
  initial if (WIDTH<1 || DELAY_FS>64'h7fffffffffffffff)
    $fatal(1,"INVALID_RESETLESS_CLOSING_LATCH_PARAMETERS");
  always @(closed or d)
    if (closed === 1'b0) stored <= d;
    else if (closed !== 1'b1 && d !== stored) stored <= 'x;
  assign #DELAY_FS q = stored;
endmodule
