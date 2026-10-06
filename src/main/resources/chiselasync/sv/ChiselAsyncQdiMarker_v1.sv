// SPDX-License-Identifier: Apache-2.0
// Passive bounded-digital QDI-family contract. MODE: 1=strong indication,
// 2=forwarding, 3=selected-strong indication. COMPONENT: 1=storage, 2=DIMS,
// 3=fork, 4=join, 5=demux, 6=exclusive merge.
// Every mode assumes atomic digital cells, ideal zero-skew wire forks,
// monotonic 1-of-2 RTZ rails, and coordinated reset held until quiescent.
// Component 6 additionally assumes serialized complete input handshakes.
// CELL_*_FS record local model bounds in fs, not physical timing closure.
// values packs each input channel followed by each output channel, in listed
// order; each channel packs zero rails, one rails, acknowledgement (LSB first).
// No output, state, delay or behavioral effect. Consume/preserve before removal.
// This marker is not a proof of circuit indication, hazard freedom or physical QDI.
module ChiselAsyncQdiMarker_v1 #(
  parameter MODE=1, COMPONENT=1, WIDTH=1,
  parameter [63:0] CELL_MIN_FS=1, CELL_MAX_FS=1, CELL_MODEL_FS=1
) (input reset, input [WIDTH-1:0] values);
endmodule
