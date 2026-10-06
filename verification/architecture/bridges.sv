// SPDX-License-Identifier: Apache-2.0
`timescale 1ns/1ps
module ArchitectureBench;
parameter TO_ASYNC=1;
reg reset=0,clock=0,in_valid=0,out_ready=0,in_req=0,out_ack=0;
reg [7:0] in_bits=0;
wire in_ready,out_valid,in_ack,out_req;
wire [7:0] out_bits;
integer cycles=0,accepted=0,delivered=0,aborted=0,resets=0,edge_at=0,i,j;
reg [7:0] expected[0:511],held;
reg holding=0,blocked=0;
if(TO_ASYNC) begin
  ToAsyncExample dut(.reset(reset),.clock(clock),.in_valid(in_valid),.in_ready(in_ready),.in_bits(in_bits),
    .out_ack(out_ack),.out_req(out_req),.out_bits(out_bits));
end else begin
  ToClockedExample dut(.reset(reset),.clock(clock),.in_req(in_req),.in_ack(in_ack),.in_bits(in_bits),
    .out_ready(out_ready),.out_valid(out_valid),.out_bits(out_bits));
end
always #7 clock=~clock;
always @(posedge clock) begin
  cycles=cycles+1;
  if(!reset) begin
    if(TO_ASYNC && in_ready && in_valid) begin expected[accepted]=in_bits;accepted=accepted+1;$display("EVENT t=%0t accept word=%h",$time,in_bits);end
    if(!TO_ASYNC) begin
      if(blocked && (!out_valid || out_bits!==held)) $fatal(1,"BRIDGE_STALL_HOLD");
      blocked=out_valid && !out_ready;held=out_bits;
      if(out_valid && out_ready) begin
        if(delivered>=accepted || out_bits!==expected[delivered]) $fatal(1,"BRIDGE_PAYLOAD");
        delivered=delivered+1;
        $display("EVENT t=%0t deliver word=%h",$time,out_bits);
      end
    end
  end
end
always @(posedge in_req) if(!reset && !TO_ASYNC) begin
  expected[accepted]=in_bits;accepted=accepted+1;edge_at=cycles;
  $display("EVENT t=%0t offer word=%h",$time,in_bits);
end
always @(posedge out_valid) if(!reset && !TO_ASYNC && cycles-edge_at<4) $fatal(1,"REQ_SYNC_EARLY");
always @(posedge in_ack) if(!reset && !TO_ASYNC && delivered!=accepted) $fatal(1,"ACK_BEFORE_COMMIT");
always @(posedge out_req) if(!reset && TO_ASYNC) begin held=out_bits;holding=1;end
always @(out_bits) if(!reset && TO_ASYNC && holding && out_bits!==held) $fatal(1,"BRIDGE_ASYNC_HOLD");
always @(posedge out_ack) if(!reset && TO_ASYNC) begin
  if(delivered>=accepted || out_bits!==expected[delivered]) $fatal(1,"BRIDGE_PAYLOAD");
  delivered=delivered+1;edge_at=cycles;
  $display("EVENT t=%0t deliver word=%h",$time,out_bits);
end
always @(negedge out_req) if(!reset && TO_ASYNC && cycles-edge_at<3) $fatal(1,"ACK_SYNC_EARLY");
always @(negedge out_ack) holding=0;
task initialize;
begin
  reset=1;aborted=aborted+accepted-delivered;accepted=0;delivered=0;holding=0;blocked=0;resets=resets+1;
  $display("EVENT t=%0t reset aborted=%0d",$time,aborted);
  #1;in_req=0;in_valid=0;out_ack=0;out_ready=0;in_bits=0;
  #100; if(out_bits!==0 || (TO_ASYNC ? out_req!==0 || in_ready!==0 : in_ack!==0 || out_valid!==0)) $fatal(1,"BRIDGE_RESET");
  @(negedge clock); reset=0; repeat(6) @(negedge clock);
end endtask
task stream(input integer count);
begin
  fork
  begin for(i=0;i<count;i=i+1) begin
    if(TO_ASYNC) begin
      // Data may change freely until the actual Decoupled fire.
      @(negedge clock);in_valid=1;in_bits=(i/2)*73;
      @(posedge clock);while(!in_ready) begin
        @(negedge clock);in_bits=in_bits+19;in_valid=(cycles%3)!=0;
        @(posedge clock); if(!in_valid) begin @(negedge clock);in_valid=1;@(posedge clock);end
      end
      @(negedge clock);in_valid=0;in_bits=~in_bits;
    end else begin
      #3;in_bits=(i/2)*73; #5;in_req=1;wait(in_ack===1); #11;in_req=0;wait(in_ack===0);#9;
    end
  end end
  begin for(j=0;j<count;j=j+1) begin
    if(TO_ASYNC) begin
      wait(out_req===1);#31;out_ack=1;wait(out_req===0);#29;out_ack=0;#3;
    end else begin
      wait(out_valid===1);repeat(3+(j%5)) @(negedge clock);out_ready=1;
      @(posedge clock);@(negedge clock);out_ready=0;
      wait(in_ack===0);
    end
  end end
  join
  repeat(10) @(negedge clock);
  if(accepted!=count || delivered!=count) $fatal(1,"BRIDGE_ACTIVITY accepted=%0d delivered=%0d",accepted,delivered);
end endtask
initial begin
  $dumpfile("trace.vcd");$dumpvars(0,ArchitectureBench);
  #1; initialize();stream(128);
  // One accepted/offered token blocked at the destination, then coordinated abort and restart.
  if(TO_ASYNC) begin
    @(negedge clock);in_valid=1;in_bits=8'hc5;@(posedge clock);@(negedge clock);in_valid=0;
    wait(out_req===1);
  end else begin in_bits=8'hc5;#3;in_req=1;wait(out_valid===1);end
  #100;initialize();stream(16);
  if(aborted!=1 || resets!=2) $fatal(1,"BRIDGE_RESET_ACCOUNTING");
  $display("ARCH_PASS bridge transfers=144 aborted=%0d resets=%0d",aborted,resets);$finish;
end
initial begin #1000000;$fatal(1,"ARCH_DEADLINE");end
endmodule
