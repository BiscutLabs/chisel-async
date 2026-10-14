// SPDX-License-Identifier: Apache-2.0
// Digital held-bus transport checks; not metastability or physical timing signoff.
module CaptureReceiptBench;
  timeunit 1ps; timeprecision 1ps;
  parameter WIDTH = @WIDTH@, CLICK = @CLICK@, STAGES = @STAGES@;
  parameter SETTLING = @SETTLING@, MASK = @MASK@, QUALIFIED = 0;
  reg base_clock = 0, clock_enable = 1, reset = 0;
  always #5000 base_clock = ~base_clock;
  wire consumer_clock = base_clock && clock_enable;
  wire receipt_clock = QUALIFIED ? base_clock : consumer_clock;
  reg in_req = 0, copy_ack = 0, want_ready = 0;
  reg [WIDTH-1:0] in_bits = 0;
  wire in_ack, source_ack, out_valid;
  wire [WIDTH-1:0] out_bits;
  wire out_ready = want_ready && (!QUALIFIED || clock_enable);
  @TOP@ dut(.clock(receipt_clock), .reset(reset), .in_req(in_req), .in_ack(in_ack),
    .in_bits(in_bits), .out_ready(out_ready), .out_valid(out_valid), .out_bits(out_bits));
  ChiselAsyncCElement_v1 join_ack(.reset(reset), .a(in_ack), .b(copy_ack), .q(source_ack));
  reg offered = 0;
  reg [WIDTH-1:0] expected = 0, captured = 0;
  integer accepted = 0, receipts = 0, delivered = 0, resets = 0, stopped = 0;
  integer pending_before, i, bit_index, snap, old_count;
  reg old_ack, next_phase;
  always @(posedge receipt_clock) if (!reset && out_valid && out_ready) begin
    if (!offered) $fatal(1,"CAPTURE_UNSOLICITED");
    receipts = receipts + 1;
  end
  always @(posedge consumer_clock) if (!reset && out_valid && want_ready) begin
    if (!offered) $fatal(1,"CAPTURE_CONSUMER_UNSOLICITED");
    if (out_bits !== expected) $fatal(1,"CAPTURE_CONSUMER_PAYLOAD");
    captured = out_bits;
    accepted = accepted + 1;
    $display("CAPTURE D %0h",out_bits);
  end
  always @(negedge base_clock) if (!reset) begin
    if (receipts != accepted) $fatal(1,"CAPTURE_CLOCK_MISMATCH");
    if (MASK && !out_valid && out_bits !== {WIDTH{1'b0}}) $fatal(1,"CAPTURE_INVALID_MASK");
  end

  task automatic restart;
    begin
      // Coordinated reset precedes any producer withdrawal.
      #17; reset=1; #17; offered=0; in_req=0; copy_ack=0; want_ready=0; in_bits=0;
      clock_enable=1; repeat(2) @(negedge base_clock); reset=0;
      repeat(STAGES+3) @(negedge base_clock);
      if (out_valid || in_ack || source_ack) $fatal(1,"CAPTURE_RESET_IDLE");
      resets=resets+1;
    end
  endtask

  task automatic offer(input [WIDTH-1:0] value);
    begin
      if (CLICK && delivered > 0) #17;
      else begin @(negedge base_clock); #17; end
      expected=value; in_bits=value; offered=1;
      #17; in_req=CLICK ? !in_req : 1'b1;
    end
  endtask

  task automatic wait_valid;
    integer edges;
    begin
      edges=0;
      while(!out_valid && edges < STAGES+SETTLING+5) begin
        @(posedge receipt_clock); #2; edges=edges+1;
      end
      if (!out_valid) $fatal(1,"CAPTURE_VALID_MISSING");
    end
  endtask

  task automatic finish_source;
    begin
      if (CLICK) begin
        if (source_ack !== in_req) $fatal(1,"CAPTURE_JOIN_MISSING");
        offered=0; delivered=delivered+1;
        // Immediate legal payload reuse after completion; the consumer has
        // already captured, and the next offer need not wait for a clock edge.
        #1; in_bits=~in_bits;
      end else begin
        if (!source_ack) $fatal(1,"CAPTURE_JOIN_MISSING");
        // Hold source request after ACK: never duplicate the transaction.
        snap=accepted; repeat(3) @(negedge base_clock);
        if (accepted != snap || out_valid) $fatal(1,"CAPTURE_DUPLICATE");
        #17; in_req=0; copy_ack=0;
        repeat(STAGES+4) @(negedge base_clock);
        if (source_ack || in_ack || out_valid) $fatal(1,"CAPTURE_RETURN_MISSING");
        offered=0; delivered=delivered+1;
      end
      want_ready=0;
    end
  endtask

  task automatic transfer(input [WIDTH-1:0] value, input integer order);
    integer start_count;
    reg prior_ack;
    begin
      start_count=accepted; prior_ack=in_ack;
      want_ready=0; offer(value);
      if (order == 0) copy_ack=in_req;
      wait_valid();
      repeat(3) begin
        @(negedge base_clock);
        if (!out_valid || out_bits !== value || in_ack !== prior_ack)
          $fatal(1,"CAPTURE_BACKPRESSURE");
      end
      // Both actual gated-clock and parent-clock/qualified-ready arrangements.
      @(negedge base_clock); clock_enable=0; want_ready=1; stopped=stopped+1;
      repeat(5) @(negedge base_clock);
      if (accepted != start_count || receipts != start_count || in_ack !== prior_ack)
        $fatal(1,"CAPTURE_STOPPED_CLOCK");
      clock_enable=1;
      @(posedge consumer_clock); #2;
      if (accepted != start_count+1 || in_ack !== in_req || captured !== value)
        $fatal(1,"CAPTURE_ACCEPT_ACK");
      if (order != 0) begin
        if (source_ack !== prior_ack) $fatal(1,"CAPTURE_JOIN_EARLY");
        // The second sink completes and the native join progresses with no
        // receipt/consumer edge. It has no synchronized-copy feedback loop.
        @(negedge base_clock); clock_enable=0; #719; copy_ack=in_req; #2;
        if (source_ack !== in_req) $fatal(1,"CAPTURE_JOIN_CLOCK_DEPENDENCE");
        if (accepted != start_count+1) $fatal(1,"CAPTURE_DUPLICATE");
        clock_enable=1;
      end
      finish_source();
    end
  endtask

  initial begin
    restart();
    // Invalid payload is permitted to change; masked mode must block it.
    #17; in_bits={WIDTH{1'b1}}; #19;
    if (MASK && out_bits !== {WIDTH{1'b0}}) $fatal(1,"CAPTURE_INVALID_MASK_INITIAL");
    if (!MASK && out_bits !== in_bits) $fatal(1,"CAPTURE_DIRECT_BUS");
    // Exact synchronizer plus settling edge count, independently of DUT state.
    offer({WIDTH{1'b1}}); copy_ack=in_req;
    for(i=1;i<=STAGES+1+SETTLING;i=i+1) begin
      @(posedge receipt_clock); #2;
      if (out_valid !== (i==STAGES+1+SETTLING)) $fatal(1,"CAPTURE_LATENCY");
      if (in_ack) $fatal(1,"CAPTURE_ACK_EARLY");
    end
    @(negedge base_clock); want_ready=1;
    @(posedge consumer_clock); #2;
    if (accepted != 1 || in_ack !== in_req) $fatal(1,"CAPTURE_ACCEPT_ACK");
    finish_source();

    // Every payload bit sees both values; identical adjacent words remain tokens.
    transfer(0,0); transfer(0,1); transfer({WIDTH{1'b1}},0);
    for(bit_index=0;bit_index<WIDTH;bit_index=bit_index+1) begin
      transfer({{(WIDTH-1){1'b0}},1'b1} << bit_index, bit_index%2);
      transfer(~({{(WIDTH-1){1'b0}},1'b1} << bit_index), (bit_index+1)%2);
    end

    // Reset interrupts request synchronizing, settling, stalled valid, accepted
    // join wait, and (BD) request return. Reuse then exercises the fresh epoch.
    offer(1); restart();
    offer(1); repeat(STAGES+1) @(negedge base_clock); restart();
    offer(1); wait_valid(); restart();
    offer(1); wait_valid(); @(negedge base_clock); want_ready=1;
    @(posedge consumer_clock); #2; restart();
    if (!CLICK) begin
      offer(1); copy_ack=1; wait_valid(); @(negedge base_clock); want_ready=1;
      @(posedge consumer_clock); #2; in_req=0; copy_ack=0; restart();
    end else begin
      // Falling-parity resets also restart coherently, both before receipt
      // acceptance and after that acceptance while the other sink is pending.
      transfer({WIDTH{1'b1}},0); offer(0); wait_valid(); restart();
      transfer({WIDTH{1'b1}},1); offer(0); wait_valid();
      @(negedge base_clock); want_ready=1;
      @(posedge consumer_clock); #2; restart();
    end
    transfer(0,1); transfer({WIDTH{1'b1}},0);
    if (receipts != accepted || delivered != 2*WIDTH+6+2*CLICK || stopped != 2*WIDTH+5+2*CLICK)
      $fatal(1,"CAPTURE_ACTIVITY");
    $display("CAPTURE_PASS delivered=%0d accepted=%0d resets=%0d stopped=%0d",delivered,accepted,resets,stopped);
    $finish;
  end
  initial begin #1000000000; $fatal(1,"CAPTURE_DEADLINE"); end
endmodule
