// SPDX-License-Identifier: Apache-2.0
// Atomic inertial AND, including its input bubbles. Ideal digital wires only.
module ChiselAsyncAnd_v1 #(
  parameter integer INPUTS=2,
  parameter time DELAY_FS=0,
  parameter [INPUTS-1:0] INVERT=0
)(input wire reset, input wire [INPUTS-1:0] d, output wire q);
  timeunit 1fs;
  timeprecision 1fs;
  initial if (INPUTS<1 || DELAY_FS>64'h7fffffffffffffff)
    $fatal(1,"INVALID_AND_PARAMETERS");
  assign #DELAY_FS q = reset ? 1'b0 : &(d ^ INVERT);
endmodule
