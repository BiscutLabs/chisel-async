// SPDX-License-Identifier: Apache-2.0
module ChiselAsyncClosingLatch_v1 #(
  parameter integer WIDTH=1,
  parameter time DELAY_FS=0
)(input wire reset, closed, input wire [WIDTH-1:0] d, output wire [WIDTH-1:0] q);
  timeunit 1fs;
  timeprecision 1fs;
  reg [WIDTH-1:0] stored;
  initial if (WIDTH<1 || DELAY_FS>64'h7fffffffffffffff)
    $fatal(1,"INVALID_CLOSING_LATCH_PARAMETERS");
  always @(reset or closed or d)
    if (reset === 1'b1) stored <= 0;
    else if (reset !== 1'b0) stored <= 'x;
    else if (closed === 1'b0) stored <= d;
    else if (closed !== 1'b1 && d !== stored) stored <= 'x;
  assign #DELAY_FS q = stored;
endmodule
