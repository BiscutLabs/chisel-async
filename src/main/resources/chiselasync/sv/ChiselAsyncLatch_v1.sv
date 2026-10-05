// SPDX-License-Identifier: Apache-2.0
// Functional view. Timing obligations are checked independently at observed ports.
module ChiselAsyncLatch_v1 #(
  parameter integer WIDTH = 1,
  parameter [WIDTH-1:0] RESET_VALUE = 0
) (
  input wire reset,
  input wire enable,
  input wire [WIDTH-1:0] d,
  output reg [WIDTH-1:0] q
);
  always @(reset or enable or d) begin
    if (reset === 1'b1) q <= RESET_VALUE;
    else if (reset !== 1'b0) q <= {WIDTH{1'bx}};
    else if (enable === 1'b1) q <= d;
    else if (enable !== 1'b0 && d !== q) q <= {WIDTH{1'bx}};
  end
endmodule
