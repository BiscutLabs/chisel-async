// SPDX-License-Identifier: Apache-2.0
`timescale 1ns/1ps
module ArchitectureBench;
reg reset=0, out_ack=0;
reg [7:0] in_zero=0,in_one=0;
wire [7:0] out_zero,out_one;
wire in_ack;
integer accepted=0,delivered=0,aborted=0,returned=0,resets=0,i,j;
reg [7:0] expected;
reg [7:0] previous_zero=0,previous_one=0;
DualRailExample dut(.reset(reset),.in_zero(in_zero),.in_one(in_one),.in_ack(in_ack),
  .out_zero(out_zero),.out_one(out_one),.out_ack(out_ack));
always @(posedge in_ack) if(!reset) begin
  if((out_zero^out_one)!==8'hff || (in_zero^in_one)!==8'hff) $fatal(1,"DUAL_EARLY_COMPLETE");
  accepted=accepted+1;
  $display("EVENT t=%0t accept word=%h",$time,in_one);
end
always @(negedge in_ack) if(!reset && resets>0) begin
  if((out_zero|out_one)!==0) $fatal(1,"DUAL_EARLY_SPACER");
  returned=returned+1;
end
always @(out_zero or out_one) if(!reset && (out_zero & out_one)!==0) $fatal(1,"DUAL_ILLEGAL_CODE");
always @(out_zero or out_one) begin
  if(!reset) begin
    if(((previous_zero & ~out_zero)|(previous_one & ~out_one))!=0 && !out_ack) $fatal(1,"DUAL_EARLY_WITHDRAW");
    if(((~previous_zero & out_zero)|(~previous_one & out_one))!=0 && out_ack) $fatal(1,"DUAL_NONMONOTONIC_RETURN");
  end
  previous_zero=out_zero;previous_one=out_one;
end
always @(posedge out_ack) if(!reset) begin
  if((out_zero^out_one)!==8'hff || out_one!==expected) $fatal(1,"DUAL_PAYLOAD");
  delivered=delivered+1;
  $display("EVENT t=%0t deliver word=%h",$time,out_one);
end
task initialize;
begin
  reset=1; aborted=accepted-delivered; resets=resets+1;
  $display("EVENT t=%0t reset aborted=%0d",$time,aborted);
  #1 in_zero=0;in_one=0;out_ack=0; #1000;
  if(out_zero!==0 || out_one!==0 || in_ack!==0) $fatal(1,"DUAL_RESET");
  reset=0; #1000;
end endtask
task transfer(input [7:0] word);
integer bit_index;
begin
  expected=word;
  fork
    begin
      for(bit_index=0;bit_index<8;bit_index=bit_index+1) begin
        #(3+bit_index*3);
        if(word[bit_index]) in_one[bit_index]=1; else in_zero[bit_index]=1;
      end
      wait(in_ack===1); #7;
      for(bit_index=0;bit_index<8;bit_index=bit_index+1) begin
        #(4+bit_index*4); in_zero[bit_index]=0;in_one[bit_index]=0;
      end
      wait(in_ack===0); #40;
    end
    begin
      wait((out_zero^out_one)===8'hff); #(11+(word%29)); out_ack=1;
      wait((out_zero|out_one)===0); #17;out_ack=0;
    end
  join
end endtask
initial begin
  $dumpfile("trace.vcd");$dumpvars(0,ArchitectureBench);
  #1; initialize();
  for(i=0;i<256;i=i+1) transfer(i);
  transfer(8'h55);transfer(8'h55);
  // Reset partial data, full stalled data, and an interrupted spacer wave.
  in_one=1; #100; initialize(); transfer(8'ha5);
  expected=8'h3c; in_one=8'h3c;in_zero=~8'h3c; wait(in_ack===1); #100;
  initialize(); transfer(8'ha5);
  expected=8'hc3; in_one=8'hc3;in_zero=~8'hc3; wait(in_ack===1); #100;out_ack=1;
  #100;in_one[3:0]=0;in_zero[3:0]=0; #100;
  initialize(); transfer(8'ha5);
  #1000;
  if(accepted!=delivered+aborted || delivered!=262 || aborted!=1 || resets!=4 || returned!=261)
    $fatal(1,"DUAL_ACTIVITY accepted=%0d delivered=%0d aborted=%0d returned=%0d resets=%0d",accepted,delivered,aborted,returned,resets);
  $display("ARCH_PASS dualrail delivered=%0d aborted=%0d resets=%0d",delivered,aborted,resets);$finish;
end
initial begin #1000000;$fatal(1,"ARCH_DEADLINE");end
endmodule
