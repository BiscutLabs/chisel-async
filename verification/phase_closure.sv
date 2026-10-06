// SPDX-License-Identifier: Apache-2.0
// Adversarial schedules; controller comes from emitted production RTL.
module ReviewAdapterBench;
  timeunit 1fs; timeprecision 1fs;
  parameter time C=10000000,T=1000000,H=1000000,X=1000000,G=40000000;
  parameter integer MODE=0;
  localparam time QUIET=10*(C+T+H+X+G+1);
  reg reset=0, req4=0, ack2=0;
  wire closed, history, phase, req2, ack4, guarded_input;
  integer transfers=0,window_id,i;
  // The runner inserts the actual emitted ToTwoPhase and declared-cell overrides.
  // DUT_INSERT

  task automatic recover;
    begin
      reset=1; #1; req4=0; ack2=0; #QUIET;
      if(req2!==0 || ack4!==0 || closed!==0 || history!==0) $fatal(1,"RESET_NOT_QUIESCENT");
      reset=0; #QUIET;
      if(req2!==0 || ack4!==0 || closed!==0 || history!==0) $fatal(1,"RESET_PHANTOM_EDGE");
    end
  endtask
  task automatic receive(input time hold_time);
    begin
      wait(req2!=ack2); #hold_time;
      if(closed!==1 || history!==ack2) $fatal(1,"HISTORY_NOT_ISOLATED_BEFORE_ACK");
      ack2=req2;
    end
  endtask
  task automatic transaction(input time source_hold,input time sink_hold);
    reg previous;
    begin
      previous=req2;
      fork
        begin req4=1; wait(ack4); #source_hold; req4=0; wait(!ack4); end
        receive(sink_hold);
        begin
          #(2*(C+T+H+X+G+1)+sink_hold);
          if(req2===previous) $fatal(1,"REQUEST_PHASE_LOST");
        end
      join
      if(req2!==ack2 || history!==ack2 || closed!==0) $fatal(1,"RETURN_NOT_COMPLETE");
      transfers=transfers+1;
    end
  endtask
  // Fast source path with a per-request propagation assertion.
  task automatic burst_offer;
    reg old_phase;
    begin
      old_phase=req2;
      fork
        begin req4=1; wait(ack4); req4=0; wait(!ack4); end
        begin
          // A persistent request must produce the opposite output phase after
          // exactly the modeled toggle + guard path, irrespective of the sink.
          #(T+G+1);
          if(req2!==!old_phase) $fatal(1,"REQUEST_PHASE_LOST");
        end
      join
    end
  endtask
  task automatic burst;
    begin
      fork
        begin
          for(i=0;i<8;i=i+1) begin
            burst_offer();
          end
        end
        begin repeat(8) begin receive(0); wait(!ack4); end end
        begin
          #(100*(C+T+H+X+G+1));
          if(req4 || ack4 || req2!==ack2) $fatal(1,"BURST_PROGRESS_DEADLINE");
        end
      join
      transfers=transfers+8;
    end
  endtask
  initial begin
    recover(); burst();
    transaction(500000000,0); transaction(0,500000000);
    for(window_id=0;window_id<6;window_id=window_id+1) begin
      recover();
      req4=1;
      case(window_id)
        0: #1;
        1: begin wait(closed); #1; end
        2: begin wait(req2!=ack2); #1; end
        3: begin receive(0); wait(ack4); #1; end
        4: begin receive(0); wait(ack4); req4=0; #1; end
        5: begin receive(0); wait(ack4); req4=0; wait(!closed); #1; end
      endcase
      recover();
      transaction(0,0); transaction(0,0);
    end
    $display("ADAPTER_REVIEW_PASS transfers=%0d reset_windows=6",transfers);$finish;
  end
  initial begin #1000000000000; $fatal(1,"PROGRESS_DEADLINE"); end
endmodule
