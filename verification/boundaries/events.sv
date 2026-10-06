// SPDX-License-Identifier: Apache-2.0
`timescale 1ns/1ps
module BoundaryBench;
parameter HALF=5, PHASE=1;
reg clock=0, reset=0, out_ack=0;
reg [3:0] levels=0;
wire out_req;
wire [3:0] out_bits;
integer deliveries=0, snapshots=0, resets=0, i;
PendingEventsExample dut(.*);
wire snapshot=SNAPSHOT;
always #(HALF) clock=~clock;
always @(posedge clock) if(!reset && snapshot) begin
  snapshots=snapshots+1; $display("BND S");
end
task restart;
begin
  #(PHASE+0.137); reset=1; resets=resets+1; $display("BND R");
  #0.1; levels=0; out_ack=0; #(HALF*9+PHASE);
  if(out_req!==0) $fatal(1,"EVENT_RESET");
  reset=0; #(HALF*12+PHASE);
end endtask
task pulse(input integer bits);
begin
  #(PHASE+0.173); levels=bits; #(HALF*10); levels=0; #(HALF*10);
end endtask
task receive(input integer expected);
reg [3:0] held;
integer waited;
begin
  waited=0;
  while(out_req!==1 && waited<32) begin @(negedge clock); waited=waited+1; end
  if(out_req!==1) $fatal(1,"EVENT_MISSING"); held=out_bits;
  if(out_bits!==expected) $fatal(1,"EVENT_PAYLOAD");
  #(HALF*9+PHASE);
  if(!out_req || out_bits!==held) $fatal(1,"EVENT_HOLD");
  out_ack=1; deliveries=deliveries+1; $display("BND D %0d",out_bits);
  wait(out_req===0); #(HALF*9+PHASE);
  if(out_bits!==held) $fatal(1,"EVENT_HOLD");
  out_ack=0; #(HALF*12+PHASE);
end endtask
initial begin
  $dumpfile("trace.vcd"); $dumpvars(0,BoundaryBench);
  #0.3; restart();
  for(i=1;i<=15;i=i+1) begin pulse(i); receive(i); end
  // Held high is one rising event; it cannot continually refill the pending bank.
  levels=5; #(HALF*20); receive(5); #(HALF*25);
  if(out_req) $fatal(1,"EVENT_LEVEL_RETRIGGER"); levels=0; #(HALF*10);
  // Two repeated events coalesce in the pending bank, but an already offered
  // snapshot does not absorb a later event on that same bit.
  pulse(1); wait(out_req); pulse(1); pulse(1); pulse(6);
  receive(1); receive(7); #(HALF*20);
  if(out_req) $fatal(1,"EVENT_COALESCING");
  // New event coincident with acknowledging the current batch survives.
  pulse(2); wait(out_req);
  levels=8; out_ack=1; deliveries=deliveries+1; $display("BND D %0d",out_bits);
  if(out_bits!==2) $fatal(1,"EVENT_PAYLOAD");
  wait(out_req===0); #(HALF*10); levels=0; out_ack=0; receive(8);
  // Set and snapshot on the SAME clock edge: force the second synchronized rise
  // one cycle after the first. Pin transitions are timed, no internal force.
  @(negedge clock); levels=1;
  @(negedge clock); levels=3;
  #(HALF*12); levels=0; receive(1); receive(2);
  // Reset discards both offered and pending banks, then traffic restarts.
  pulse(4); pulse(8); restart();
  #(HALF*30); if(out_req) $fatal(1,"EVENT_RESET_LEAK");
  pulse(15); receive(15);
  // A level retained high across reset is deliberately captured as a new event.
  @(negedge clock); levels=4; #0.1; reset=1; resets=resets+1; $display("BND R");
  #(HALF*10+PHASE); reset=0; receive(4); levels=0;
  if(deliveries!=24 || snapshots!=25 || resets!=3) $fatal(1,"EVENT_ACTIVITY");
  $display("BOUNDARY_PASS events delivered=%0d snapshots=%0d resets=%0d",deliveries,snapshots,resets);
  $finish;
end
initial begin #5000000; $fatal(1,"BOUNDARY_DEADLINE"); end
endmodule
