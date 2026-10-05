// SPDX-License-Identifier: Apache-2.0
// Simulation-only view. Every scheduled packet captures its value and reset epoch.
module ChiselAsyncDelayLine_v1 #(
  parameter integer WIDTH = 1,
  parameter time DELAY_FS = 1,
  parameter integer POLICY = 0
) (
  input wire reset,
  input wire [WIDTH-1:0] d,
  output reg [WIDTH-1:0] q
);
  timeunit 1fs;
  timeprecision 1fs;
  reg initialized = 0;
  reg [63:0] epoch = 0;
  reg [63:0] serial = 0;
  reg [63:0] before_timestamp = 0;
  time last_change = 0;
  reg [WIDTH+127:0] delivery;

  initial begin
    if (WIDTH <= 0 || DELAY_FS == 0 || DELAY_FS > 64'h7fffffffffffffff || (POLICY != 0 && POLICY != 1))
      $fatal(1, "INVALID_DELAY_PARAMETERS");
  end

  always @(reset or d) begin
    if (reset === 1'b1) begin
      initialized = 1;
      epoch = epoch + 1;
      serial = serial + 1;
      q <= {WIDTH{1'b0}};
    end else if (reset === 1'b0) begin
      if (!initialized) $fatal(1, "DELAY_REQUIRES_RESET");
      if ($time > 64'h7fffffffffffffff - DELAY_FS) $fatal(1, "MODEL_TIME_OVERFLOW");
      if (last_change != $time) before_timestamp = serial;
      last_change = $time;
      serial = serial + 1;
      delivery <= #(DELAY_FS) {epoch, serial, d};
    end else begin
      epoch = epoch + 1;
      initialized = 0;
      q <= {WIDTH{1'bx}};
    end
  end

  always @(delivery) begin
    if (reset === 1'b0 && initialized && delivery[WIDTH+127:WIDTH+64] == epoch) begin
      if (POLICY == 0 || delivery[WIDTH+63:WIDTH] == serial ||
          (last_change == $time && delivery[WIDTH+63:WIDTH] == before_timestamp))
        q <= delivery[WIDTH-1:0];
    end
  end
endmodule
