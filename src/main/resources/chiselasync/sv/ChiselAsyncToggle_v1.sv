// SPDX-License-Identifier: Apache-2.0
module ChiselAsyncToggle_v1 #(parameter time DELAY_FS=1)
 (input wire reset, trigger, output wire q);
  timeunit 1fs; timeprecision 1fs;
  reg phase;
  initial if (DELAY_FS<1 || DELAY_FS>64'h7fffffffffffffff) $fatal(1,"INVALID_TOGGLE_PARAMETERS");
  always @(posedge reset or posedge trigger)
    if (reset) phase <= 1'b0;
    else phase <= ~phase;
  assign #DELAY_FS q = phase;
endmodule
