// SPDX-License-Identifier: Apache-2.0
// Passive timing intent, in fs. KIND 1=setup/hold, 2=long-hold bundling.
// `values` packs the obligation's endpoint list from least to most significant.
// No output, state, delay or behavioral effect. Extract constraints before
// synthesis removes this empty module; no physical implementation is implied.
module ChiselAsyncTimingMarker_v1 #(
  parameter KIND=0, WIDTH=1,
  parameter [63:0] SETUP_FS=0, HOLD_FS=0, MATCHED_FS=0, OUTPUT_FS=0,
  parameter [63:0] A_MIN_FS=0, A_MAX_FS=0, A_MODEL_FS=0,
  parameter [63:0] B_MIN_FS=0, B_MAX_FS=0, B_MODEL_FS=0,
  parameter [63:0] ACKNOWLEDGE_MIN_FS=0, ACKNOWLEDGE_MAX_FS=0, ACKNOWLEDGE_MODEL_FS=0,
  parameter [63:0] LONG_HOLD_MIN_FS=0, LONG_HOLD_MAX_FS=0, LONG_HOLD_MODEL_FS=0,
  parameter [63:0] DATA_MIN_FS=0, DATA_MAX_FS=0, DATA_MODEL_FS=0,
  parameter [63:0] LATCH_MIN_FS=0, LATCH_MAX_FS=0, LATCH_MODEL_FS=0
) (input reset, input [WIDTH-1:0] values);
endmodule
