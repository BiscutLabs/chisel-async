// SPDX-License-Identifier: Apache-2.0
// Digital propagation model. Bind to characterized edge-triggered cells for hardware.
module ChiselAsyncEventRegister_v1 #(
  parameter integer WIDTH=1, parameter time DELAY_FS=1,
  parameter [WIDTH-1:0] RESET_VALUE=0
)(input wire reset, trigger, input wire [WIDTH-1:0] d, output wire [WIDTH-1:0] q);
  timeunit 1fs; timeprecision 1fs;
  reg [WIDTH-1:0] state;
  initial if (WIDTH<1 || DELAY_FS<1 || DELAY_FS>64'h7fffffffffffffff)
    $fatal(1,"INVALID_EVENT_REGISTER_PARAMETERS");
  always @(posedge reset or posedge trigger)
    if (reset) state <= RESET_VALUE;
    else state <= d;
  assign #DELAY_FS q = state;
endmodule
