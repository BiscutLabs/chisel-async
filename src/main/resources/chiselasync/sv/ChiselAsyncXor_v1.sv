// SPDX-License-Identifier: Apache-2.0
module ChiselAsyncXor_v1 #(parameter time DELAY_FS=0)
 (input wire reset, a, b, output wire q);
  timeunit 1fs; timeprecision 1fs;
  initial if (DELAY_FS>64'h7fffffffffffffff) $fatal(1,"INVALID_XOR_PARAMETERS");
  assign #DELAY_FS q = reset ? 1'b0 : a ^ b;
endmodule
