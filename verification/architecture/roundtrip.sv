// SPDX-License-Identifier: Apache-2.0
`timescale 1ns/1ps
module ArchitectureBench;
parameter SOURCE_HALF=7,SINK_HALF=11,SINK_PHASE=3;
reg reset=0,sourceClock=0,sinkClock=0,in_valid=0,out_ready=0;
reg [7:0] in_bits=0;
wire in_ready,out_valid;
wire [7:0] out_bits;
integer accepted=0,delivered=0,aborted=0,resets=0,s=0,t=0,epoch_deliveries=0;
reg [7:0] queue[0:511],held;
reg blocked=0;
BridgeRoundTripExample dut(.reset(reset),.sourceClock(sourceClock),.sinkClock(sinkClock),
  .in_valid(in_valid),.in_ready(in_ready),.in_bits(in_bits),.out_valid(out_valid),.out_ready(out_ready),.out_bits(out_bits));
always #(SOURCE_HALF) sourceClock=~sourceClock;
initial begin #(SINK_PHASE); forever #(SINK_HALF) sinkClock=~sinkClock;end
always @(posedge sourceClock) if(!reset && in_valid && in_ready) begin queue[accepted]=in_bits;accepted=accepted+1;$display("EVENT t=%0t accept word=%h",$time,in_bits);end
always @(posedge sinkClock) if(!reset) begin
  if(blocked && (!out_valid || out_bits!==held)) $fatal(1,"ROUNDTRIP_STALL_HOLD");
  held=out_bits;blocked=out_valid && !out_ready;
  if(out_valid && out_ready) begin
    if(delivered>=accepted || out_bits!==queue[delivered]) $fatal(1,"ROUNDTRIP_PAYLOAD");
    delivered=delivered+1;
    $display("EVENT t=%0t deliver word=%h",$time,out_bits);
  end
end
task initialize;
begin
  reset=1;aborted=aborted+accepted-delivered;epoch_deliveries=epoch_deliveries+delivered;
  $display("EVENT t=%0t reset aborted=%0d",$time,aborted);
  accepted=0;delivered=0;blocked=0;resets=resets+1;
  #1;in_valid=0;out_ready=0;in_bits=0;#1000;
  if(out_valid!==0 || in_ready!==0 || out_bits!==0) $fatal(1,"ROUNDTRIP_RESET");
  reset=0;#1000;
end endtask
task stream(input integer count);
begin
  fork
    begin while(accepted<count) begin
      @(negedge sourceClock);s=s+1;in_valid=(s%5)!=0;in_bits=(s/2)*97;
      @(posedge sourceClock);#0.001;
    end @(negedge sourceClock);in_valid=0;end
    begin while(delivered<count) begin
      @(negedge sinkClock);t=t+1;out_ready=(t%11)>5;
      @(posedge sinkClock);#0.001;
    end @(negedge sinkClock);out_ready=0;end
  join
  #2000;
  if(accepted!=count || delivered!=count || out_valid!==0) $fatal(1,"ROUNDTRIP_ACTIVITY");
end endtask
initial begin
  $dumpfile("trace.vcd");$dumpvars(0,ArchitectureBench);
  #1;initialize();stream(128);
  @(negedge sourceClock);in_valid=1;in_bits=8'hd7;
  wait(accepted==130);@(negedge sourceClock);in_bits=8'he9;
  #2000;
  if(accepted!=130 || in_ready!==0 || out_valid!==1) $fatal(1,"ROUNDTRIP_CAPACITY");
  initialize();stream(16);
  if(aborted!=2 || epoch_deliveries+delivered!=144 || resets!=2) $fatal(1,"ROUNDTRIP_ACCOUNTING");
  $display("ARCH_PASS roundtrip transfers=144 aborted=%0d resets=%0d",aborted,resets);$finish;
end
initial begin #10000000;$fatal(1,"ARCH_DEADLINE");end
endmodule
