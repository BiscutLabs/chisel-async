// SPDX-License-Identifier: Apache-2.0
// Finite digital arbitration policy, NOT an analog or synthesized MUTEX cell.
// A pending decision restarts when contenders change. Grants never overlap and
// release passes through zero before another grant. Requests persist to service.
module ChiselAsyncMutex_v1 #(parameter time RESOLVE_FS=1, parameter integer POLICY=0)
 (input wire reset, input wire [1:0] request, output wire [1:0] grant);
  timeunit 1fs; timeprecision 1fs;
  reg [1:0] desired;
  reg last_winner;
  initial if (RESOLVE_FS<1 || RESOLVE_FS>64'h7fffffffffffffff || POLICY<0 || POLICY>2)
    $fatal(1,"INVALID_MUTEX_PARAMETERS");
  always @(reset or grant)
    if (reset) last_winner <= 1'b1;
    else if (grant == 2'b01) last_winner <= 1'b0;
    else if (grant == 2'b10) last_winner <= 1'b1;
  always @* begin
    if (reset) desired = 2'b00;
    else if (grant == 2'b01) desired = request[0] ? 2'b01 : 2'b00;
    else if (grant == 2'b10) desired = request[1] ? 2'b10 : 2'b00;
    else if (request == 2'b11)
      desired = (POLICY == 0 || (POLICY == 2 && last_winner)) ? 2'b01 : 2'b10;
    else desired = request;
  end
  assign #RESOLVE_FS grant = desired;
endmodule
