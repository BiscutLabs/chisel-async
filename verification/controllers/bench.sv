// SPDX-License-Identifier: Apache-2.0
// Environment/scoreboard only. It has no controller state transition equations.
`timescale 1ns/1ps
module ControllerBench;
  parameter DEPTH=3, MULLER=1, FORWARD_NS=40, ACK_NS=20;
  reg reset=0, source_req=0, sink_ack=0;
  reg [39:0] source_bits=0;
  wire [DEPTH:0] req, ack;
  wire [39:0] bits [0:DEPTH];
  assign req[0]=source_req;
  assign ack[DEPTH]=sink_ack;
  assign bits[0]=source_bits;
  genvar k;
  generate for (k=0; k<DEPTH; k=k+1) begin: stages
    if (MULLER) begin
      MullerComparisonStage #(.BASE(k*100), .FORWARD_NS(FORWARD_NS), .ACK_NS(ACK_NS)) dut(
        .reset(reset), .in_req(req[k]), .in_bits(bits[k]), .in_ack(ack[k]),
        .out_req(req[k+1]), .out_bits(bits[k+1]), .out_ack(ack[k+1]));
    end else begin
      ControllerComparisonExample #(.BASE(k*100)) dut(
        .reset(reset), .in_req(req[k]), .in_bits(bits[k]), .in_ack(ack[k]),
        .out_req(req[k+1]), .out_bits(bits[k+1]), .out_ack(ack[k+1]));
    end
  end endgenerate

  integer accepted=0, delivered=0, aborted=0, returned=0, offered=0;
  integer head=0, tail=0, epoch=0, serial=0, scenario=0, reset_cases=0;
  integer source_pause=1, sink_pause=1, source_return=1, sink_return=1;
  integer i, j, before_accept, before_delivery, before_abort;
  reg [39:0] queue [0:1023];
  integer phase [0:DEPTH];
  reg [39:0] held [0:DEPTH];
  reg holding [0:DEPTH];
  integer peak=0;
  wire [31:0] outstanding = tail-head;

  always @(posedge reset) begin
    aborted=aborted+tail-head;
    head=0; tail=0; epoch=epoch+1;
    $display("EVENT t=%0t epoch=%0d reset=1 accepted=%0d delivered=%0d aborted=%0d", $time,epoch,accepted,delivered,aborted);
  end
  generate for (k=0; k<=DEPTH; k=k+1) begin: observe
    initial begin phase[k]=0; holding[k]=0; end
    always @(posedge reset) begin phase[k]=0; holding[k]=0; end
    always @(bits[k]) begin
      if (!reset && holding[k] && bits[k] !== held[k])
        $fatal(1, "DATA_HOLD channel=%0d", k);
    end
    always @(posedge req[k]) if (!reset) begin
      if (phase[k] != 0) $fatal(1, "PROTOCOL_REQ_RISE channel=%0d", k);
      phase[k]=1; held[k]=bits[k]; holding[k]=1;
      // Event trace retains transaction identities as well as values.
      $display("EVENT t=%0t epoch=%0d channel=%0d req=1 word=%h", $time, epoch, k, bits[k]);
      if (k==DEPTH) offered=offered+1;
    end
    always @(posedge ack[k]) if (!reset) begin
      if (phase[k] != 1) $fatal(1, "PROTOCOL_ACK_RISE channel=%0d", k);
      phase[k]=2;
      // Early validity: data must hold through the accepting acknowledgement.
      if (bits[k] !== held[k]) $fatal(1, "DATA_HOLD channel=%0d", k);
      holding[k]=0;
      if (k==0) begin
        queue[tail]=bits[k]; tail=tail+1; accepted=accepted+1;
        if (tail-head > peak) peak=tail-head;
        if (tail-head > (MULLER ? (DEPTH+1)/2 : DEPTH)) $fatal(1,"CAPACITY_EXCEEDED");
      end
      if (k==DEPTH) begin
        if (head>=tail) $fatal(1, "UNEXPECTED_TOKEN");
        if (bits[k] !== queue[head]) $fatal(1, "PAYLOAD_MISMATCH expected=%h actual=%h", queue[head], bits[k]);
        head=head+1; delivered=delivered+1;
      end
      $display("EVENT t=%0t epoch=%0d channel=%0d ack=1 word=%h", $time, epoch, k, bits[k]);
    end
    always @(negedge req[k]) if (!reset && epoch>0) begin
      if (phase[k] != 2) $fatal(1, "PROTOCOL_REQ_FALL channel=%0d", k);
      phase[k]=3;
      $display("EVENT t=%0t epoch=%0d channel=%0d req=0", $time,epoch,k);
    end
    always @(negedge ack[k]) if (!reset && epoch>0) begin
      if (phase[k] != 3) $fatal(1, "PROTOCOL_ACK_FALL channel=%0d", k);
      phase[k]=0;
      $display("EVENT t=%0t epoch=%0d channel=%0d ack=0", $time,epoch,k);
      if (k==DEPTH) returned=returned+1;
    end
  end endgenerate

  task initialize;
    begin
      reset=1;
      #1 source_req=0; sink_ack=0; source_bits=0;
      // Greater than every bounded cell/buffer propagation through the pipeline.
      #1000;
      if (req[DEPTH] !== 0 || ack[0] !== 0 || bits[DEPTH] !== 0)
        $fatal(1, "RESET_NOT_QUIESCENT");
      reset=0;
      #1000;
      if (req[DEPTH] !== 0 || ack[0] !== 0) $fatal(1, "STALE_AFTER_RESET");
    end
  endtask
  task send_word(input integer value);
    begin
      serial=serial+1;
      source_bits={serial[31:0],value[7:0]};
      #2 source_req=1;
      wait(ack[0] === 1);
      #(source_return) source_req=0;
      wait(ack[0] === 0);
      #(source_pause);
    end
  endtask
  task receive_word;
    begin
      wait(req[DEPTH] === 1);
      #(sink_pause) sink_ack=1;
      wait(req[DEPTH] === 0);
      #(sink_return) sink_ack=0;
      #1;
    end
  endtask
  task idle_check;
    begin
      #500;
      if (head!=tail || req[DEPTH]!==0 || ack[0]!==0 || accepted!=delivered+aborted)
        $fatal(1, "INCOMPLETE_OR_DUPLICATE");
      for (j=0; j<=DEPTH; j=j+1)
        if (phase[j]!=0) $fatal(1, "INCOMPLETE_CHANNEL channel=%0d", j);
    end
  endtask
  initial begin
    if (!$value$plusargs("source_pause=%d",source_pause)) source_pause=1;
    if (!$value$plusargs("sink_pause=%d",sink_pause)) sink_pause=1;
    if (!$value$plusargs("source_return=%d",source_return)) source_return=1;
    if (!$value$plusargs("sink_return=%d",sink_return)) sink_return=1;
    if ($test$plusargs("waves")) begin $dumpfile("trace.vcd"); $dumpvars(0,ControllerBench); end
    #1 initialize();
    // Frozen 40-token stream, repeated low payload bytes with distinct identities.
    fork
      begin for (i=0;i<40;i=i+1) send_word((i/2)%2 ? 8'hA5 : 8'h5A); end
      begin repeat(40) receive_word(); end
    join
    idle_check();
    if (accepted!=40 || delivered!=40 || returned!=40 || offered!=40 || aborted!=0)
      $fatal(1,"STREAM_COUNTS");
    // Reset at idle, immediately after offer, accepted/backpressured, output
    // offered, output acknowledged, and return-to-zero. Restart each time.
    for (scenario=0;scenario<6;scenario=scenario+1) begin
      initialize();
      before_abort=aborted;
      if (scenario>0) begin
        serial=serial+1; source_bits={serial[31:0],8'hCC};
        #2 source_req=1;
        if (scenario>1) wait(ack[0]===1);
        if (scenario>2) begin wait(req[DEPTH]===1); #1; end
        if (scenario>3) begin sink_ack=1; #1; end
        if (scenario>4) begin
          source_req=0;
          wait(req[DEPTH]===0);
          #1;
        end
      end
      #1 initialize();
      reset_cases=reset_cases+1;
      fork send_word(8'h3C); receive_word(); join
      idle_check();
    end
    // Exact saturation with no sink acknowledgements. A pending offer must
    // remain unaccepted; reset must account for every queued token.
    initialize();
    before_accept=accepted; before_delivery=delivered; before_abort=aborted;
    fork: filling
      begin forever send_word(8'h77); end
    join_none
    #5000;
    disable filling;
    if (accepted-before_accept != (MULLER ? (DEPTH+1)/2 : DEPTH)) $fatal(1,"CAPACITY_COUNT");
    if (delivered!=before_delivery) $fatal(1,"DELIVERY_WITHOUT_SINK");
    initialize();
    if (aborted-before_abort != (MULLER ? (DEPTH+1)/2 : DEPTH)) $fatal(1,"RESET_ABORT_COUNT");
    fork send_word(8'h81); receive_word(); join
    idle_check();
    $display("RESULT PASS accepted=%0d delivered=%0d aborted=%0d returned=%0d offered=%0d peak=%0d resets=%0d",
      accepted,delivered,aborted,returned,offered,peak,reset_cases+1);
    $finish;
  end
  initial begin #200000; $fatal(1,"SIM_DEADLINE scenario=%0d accepted=%0d delivered=%0d",scenario,accepted,delivered); end
endmodule
