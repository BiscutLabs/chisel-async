// SPDX-License-Identifier: Apache-2.0
// Behavioral view: unanimity changes q; disagreement retains state. Reset dominates.
module ChiselAsyncCElement_v1 (
  input wire reset,
  input wire a,
  input wire b,
  output reg q
);
  always @(reset or a or b) begin
    if (reset === 1'b1) q <= 1'b0;
    else if (reset !== 1'b0) q <= 1'bx;
    else if ((a === 1'b1) && (b === 1'b1)) q <= 1'b1;
    else if ((a === 1'b0) && (b === 1'b0)) q <= 1'b0;
    // An unknown input can only be ignored when either resolution preserves q.
    else if (!((q === 1'b0 && (a === 1'b0 || b === 1'b0)) ||
               (q === 1'b1 && (a === 1'b1 || b === 1'b1)) ||
               (a === 1'b0 && b === 1'b1) || (a === 1'b1 && b === 1'b0))) q <= 1'bx;
  end
endmodule
