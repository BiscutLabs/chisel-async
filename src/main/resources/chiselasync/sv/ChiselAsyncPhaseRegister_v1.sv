// SPDX-License-Identifier: Apache-2.0
module ChiselAsyncPhaseRegister_v1 #(
  parameter time DELAY_FS=1, parameter bit RESET_VALUE=0
)(input wire reset, trigger, output wire q);
  timeunit 1fs; timeprecision 1fs;
  reg phase;
  initial if (DELAY_FS<1 || DELAY_FS>64'h7fffffffffffffff)
    $fatal(1,"INVALID_PHASE_REGISTER_PARAMETERS");
  always @(posedge reset or posedge trigger)
    if (reset) phase <= RESET_VALUE;
    else phase <= ~phase;
  assign #DELAY_FS q = phase;
endmodule
