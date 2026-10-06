// SPDX-License-Identifier: Apache-2.0
module MutexReview;
timeunit 1fs; timeprecision 1fs;
parameter logic [31:0] SEED=1;
parameter integer NOISE=0;
localparam time LO=10, HI=100;
reg reset=0;
reg [1:0] request=0;
wire [1:0] grant;
integer epoch, mode, round, winner, loser, events=0;
integer random_noise;
reg [1:0] previous=0;
time start, zero_at;
ChiselAsyncMutex_v1 #(.POLICY(3),.RESOLVE_FS(LO),.RESOLVE_MAX_FS(HI),.SEED(SEED)) dut(reset,request,grant);
generate if (NOISE) initial forever begin #1; random_noise=$urandom(); end endgenerate
always @(grant) begin
  if (!reset) begin
    if ($isunknown(grant) || grant===3) $fatal(1,"UNKNOWN_OR_OVERLAP");
    if (previous!=0 && grant!=0 && previous!=grant) $fatal(1,"NO_ZERO_HANDOVER");
    if (previous==0 && grant!=0 && (grant & request)!=grant) $fatal(1,"GRANTED_WITHDRAWN_REQUEST");
    events=events+1;
  end
  previous=grant;
end
task automatic restart;
begin
  reset=1; request=0; #2;
  if (grant !== 0) $fatal(1,"RESET_FAILED");
  reset=0; #(HI+2);
  if (grant !== 0) $fatal(1,"STALE_AFTER_RESET");
end endtask
initial begin
  // Repeat the exact complete traffic sequence after reset to test reseeding.
  for(epoch=0;epoch<2;epoch=epoch+1) begin
    restart();
    for(mode=0;mode<3;mode=mode+1) begin
      for(round=0;round<8;round=round+1) begin
        if(mode==0) request=3;
        else begin request=(mode==1 ? 1 : 2); #1; request=3; end
        start=$time;
        wait(grant!=0);
        if ($time-start<LO || $time-start>HI) $fatal(1,"CHOICE_LATENCY_BOUNDS");
        winner=grant;loser=3-winner;
        $display("CHOICE|%0d|%0d|%0d|%0d|%0d|%0d",epoch,mode,round,winner,$time-start,$time);
        request=winner; #(HI+2);
        if(grant!==winner) $fatal(1,"LOST_HELD_WINNER");
        request=3; #(HI+2);
        if(grant!==winner) $fatal(1,"PREEMPTED_HELD_WINNER");
        request=loser;start=$time;
        wait(grant==0); zero_at=$time;
        if($time-start<LO || $time-start>HI) $fatal(1,"RELEASE_LATENCY_BOUNDS");
        wait(grant==loser);
        if($time-zero_at<LO || $time-zero_at>HI) $fatal(1,"HANDOVER_LATENCY_BOUNDS");
        #1;request=0;wait(grant==0);#1;
      end
    end
  end
  // Change/cancel pending contender sets before their minimum delay.
  restart(); request=1;#1;request=3;#1;request=2;#1;request=0;
  #(HI+2); if(grant!==0) $fatal(1,"CANCELLED_DECISION_SURVIVED");
  request=1;#1;request=2;start=$time;
  wait(grant==2);
  if($time-start<LO || $time-start>HI) $fatal(1,"CONTENDER_RESTART_BOUNDS");
  #1;request=0;wait(grant==0);#1;
  // Winner re-entry cancels a still-pending release; it cannot pulse low later.
  request=1;wait(grant==1);#1;request=0;#1;request=1;
  #(HI+2);if(grant!==1) $fatal(1,"CANCELLED_RELEASE_SURVIVED");
  request=0;wait(grant==0);#1;
  // A short reset finishes before delayed old decisions would have arrived.
  request=3;#1;reset=1;request=0;#1;reset=0;
  #(HI+2);if(grant!==0) $fatal(1,"RESET_CANCELLATION_FAILED");
  request=1;wait(grant==1);reset=1;request=0;#1;
  if(grant!==0) $fatal(1,"HELD_RESET_FAILED");
  reset=0;#(HI+2);
  if(grant!==0 || events<100) $fatal(1,"FINAL_STATE_OR_ACTIVITY");
  $display("RANDOM_MUTEX_PASS");$finish;
end
initial begin #1000000;$fatal(1,"PROGRESS_TIMEOUT");end
endmodule
