// SPDX-License-Identifier: Apache-2.0
// Finite digital arbitration policy, NOT an analog or synthesized MUTEX cell.
// A pending decision restarts when contenders change. Grants never overlap and
// release passes through zero before another grant. Requests persist to service.
module ChiselAsyncMutex_v1 #(parameter time RESOLVE_FS=1, parameter integer POLICY=0,
 parameter time RESOLVE_MAX_FS=RESOLVE_FS, parameter logic [31:0] SEED=1)
 (input wire reset, input wire [1:0] request, output wire [1:0] grant);
  timeunit 1fs; timeprecision 1fs;
  reg [1:0] desired;
  reg last_winner;
  initial if (RESOLVE_FS<1 || RESOLVE_MAX_FS<RESOLVE_FS ||
              RESOLVE_MAX_FS>64'h7fffffffffffffff || POLICY<0 || POLICY>3 || SEED==0)
    $fatal(1,"INVALID_MUTEX_PARAMETERS");
  generate if (POLICY != 3) begin : deterministic
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
  end else begin : randomized
    // Local xorshift32 stream: independent of simulator-global RNG call order.
    // A changed contender set cancels an unresolved decision. Generation tags
    // prevent a scheduled grant surviving cancellation or an intervening reset.
    reg [31:0] state = SEED;
    reg [63:0] generation = 0;
    reg [65:0] scheduled = 0;
    reg [65:0] ticket = 0;
    reg [1:0] held = 0;
    reg [1:0] candidate;
    reg [63:0] draw;
    time latency;
    function automatic [31:0] advance(input [31:0] value);
      reg [31:0] x;
      begin x=value ^ (value << 13); x=x ^ (x >> 17); advance=x ^ (x << 5); end
    endfunction
    assign grant = held;
    always @(reset or request or held) begin
      generation = generation + 1;
      if (reset) begin held <= 0; state = SEED; end
      else begin
        if (held == 1) candidate = request[0] ? 1 : 0;
        else if (held == 2) candidate = request[1] ? 2 : 0;
        else if (request == 3) begin
          state = advance(state); candidate = state[0] ? 1 : 2;
        end else candidate = request;
        if (candidate != held) begin
          state = advance(state); draw[63:32] = state;
          state = advance(state); draw[31:0] = state;
          latency = RESOLVE_FS + draw % (RESOLVE_MAX_FS - RESOLVE_FS + 1);
          scheduled <= #(latency) {generation, candidate};
`ifdef CHISEL_ASYNC_MUTEX_TRACE
          $display("MUTEX_SCHEDULE|%m|%0t|%0d|%0d|%0d", $time, generation, candidate, latency);
`endif
        end
      end
    end
    // Recheck after conventional same-timestamp NBA input updates have settled.
    always @(scheduled) ticket <= scheduled;
    always @(ticket) if (!reset && ticket[65:2] == generation) begin
      held <= ticket[1:0];
`ifdef CHISEL_ASYNC_MUTEX_TRACE
      $display("MUTEX_COMMIT|%m|%0t|%0d|%0d", $time, generation, ticket[1:0]);
`endif
    end
  end endgenerate
endmodule
