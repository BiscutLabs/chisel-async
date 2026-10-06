// SPDX-License-Identifier: Apache-2.0
// Simulation diagnostics only. Not an arbiter or a synthesized safety circuit.
module ChiselAsyncProtocolGuard_v1 #(
  parameter integer LANES=2, MODE=0
)(input wire reset, input wire [LANES-1:0] request, acknowledge,
  input wire valid);
  timeunit 1fs;
  timeprecision 1fs;
  initial if (LANES<1 || MODE<0 || MODE>1) $fatal(1,"INVALID_GUARD_PARAMETERS");
`ifndef SYNTHESIS
`ifndef CHISEL_ASYNC_MAPPING
  integer i,j;
  always @(reset or request or acknowledge or valid) begin
    if (!reset) begin
      // Explicit bounded bit pairs avoid simulator-dependent sizing of a
      // temporary expression passed to the population-count system function.
      if (MODE==0)
        for (i=0;i<LANES;i=i+1)
          for (j=i+1;j<LANES;j=j+1)
            if ((request[i] || acknowledge[i]) && (request[j] || acknowledge[j]))
              $fatal(1,"EXCLUSIVE_MERGE_CONTENTION req=%b ack=%b", request, acknowledge);
      if (MODE==1 && (|request) && !valid)
        $fatal(1,"SELECT_INDEX_OUT_OF_RANGE");
    end
  end
`endif
`endif
endmodule
