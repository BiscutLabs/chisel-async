// SPDX-License-Identifier: Apache-2.0
// Zero-delay FUNCTIONAL view. Mandatory coordinated reset; no periodic clock.
// Input acknowledgement returns low when the source returns its request low.
// Further requests wait until the complete output handshake frees storage.
module ChiselAsyncFourPhaseStorage_v1 #(
  parameter integer WIDTH = 1
) (
  input wire reset,
  input wire in_req,
  input wire [WIDTH-1:0] in_bits,
  output reg in_ack,
  output reg out_req,
  output reg [WIDTH-1:0] out_bits,
  input wire out_ack
);
  localparam EMPTY = 0, WAIT_ACK = 1, RETURN_IDLE = 2;
  integer state;

  always @(reset or in_req or out_ack) begin
    if (reset === 1'b1) begin
      state = EMPTY;
      in_ack <= 1'b0;
      out_req <= 1'b0;
      out_bits <= {WIDTH{1'b0}};
    end else if (reset === 1'b0) begin
      if (in_req === 1'b0) in_ack <= 1'b0;
      if (state == WAIT_ACK && out_ack === 1'b1) begin
        out_req <= 1'b0;
        state = RETURN_IDLE;
      end
      if (state == RETURN_IDLE && out_ack === 1'b0) state = EMPTY;
      case (state)
        EMPTY: if (in_req === 1'b1 && in_ack === 1'b0 && out_ack === 1'b0) begin
          out_bits <= in_bits;
          in_ack <= 1'b1;
          out_req <= 1'b1;
          state = WAIT_ACK;
        end
        WAIT_ACK, RETURN_IDLE: begin end
        default: begin
          in_ack <= 1'bx;
          out_req <= 1'bx;
          out_bits <= {WIDTH{1'bx}};
        end
      endcase
    end else begin
      state = -1;
      in_ack <= 1'bx;
      out_req <= 1'bx;
      out_bits <= {WIDTH{1'bx}};
    end
  end
endmodule
