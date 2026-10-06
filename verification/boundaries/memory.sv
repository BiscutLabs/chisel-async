// SPDX-License-Identifier: Apache-2.0
`timescale 1ns/1ps
module BoundaryBench;
parameter HALF=5, PHASE=1, ROM=0;
reg clock=0, reset=0, accept=0, runClock=1;
reg [3:0] latency=0;
reg request_req=0, request_bits_write=0, response_ack=0;
reg [5:0] request_bits_address=0;
reg [15:0] request_bits_data=0;
reg [1:0] request_bits_mask=0;
wire request_ack, response_req, response_bits_error;
wire [15:0] response_bits_data;
integer accepted=0, delivered=0, effects=0, resets=0, outstanding=0;
integer i, before_count;
// TOP and compiler-resolved probes are substituted by the runner.
TOP dut(.*);
wire backend_fire=BACKEND_FIRE;
wire write_commit=WRITE_COMMIT;
always #(HALF) if(runClock) clock=~clock;
always @(posedge clock) if(!reset) begin
  if(backend_fire) begin
    if(outstanding || response_req || response_ack) $fatal(1,"MEMORY_CAPACITY");
    accepted=accepted+1; outstanding=1;
    $display("BND A %0d %0d %0d %0d",request_bits_write,request_bits_address,request_bits_data,request_bits_mask);
  end
  if(write_commit) begin effects=effects+1; $display("BND W"); end
end
always @(posedge response_ack) if(!reset) begin
  if(!response_req || outstanding!=1) $fatal(1,"MEMORY_UNSOLICITED");
  outstanding=0; delivered=delivered+1;
  $display("BND D %0d %0d",response_bits_data,response_bits_error);
end
// Data remains held through BOTH response phases, including delayed ack return.
reg holding=0;
reg [16:0] held;
always @(negedge clock) begin
  if(reset) holding=0;
  else begin
    if(holding && {response_bits_data,response_bits_error}!==held) $fatal(1,"MEMORY_RESPONSE_HOLD");
    if(response_req) begin holding=1; held={response_bits_data,response_bits_error}; end
    if(!response_req && !response_ack) holding=0;
  end
end
task restart;
begin
  #(PHASE+0.137); reset=1; resets=resets+1;
  $display("BND R %0d",outstanding); outstanding=0;
  #0.1; request_req=0; response_ack=0; accept=0;
  #(HALF*9+PHASE); 
  if(request_ack!==0 || response_req!==0 || backend_fire!==0 || write_commit!==0) $fatal(1,"MEMORY_RESET");
  reset=0; #(HALF*12+PHASE); accept=1;
end endtask
task offer(input integer wr, addr, data, mask);
begin
  wait(request_ack===0);
  #(PHASE+0.231); request_bits_write=wr; request_bits_address=addr;
  request_bits_data=data; request_bits_mask=mask;
  #0.173; request_req=1;
end endtask
task source_return;
begin
  wait(request_ack===1); #(HALF*3+PHASE); request_req=0;
  wait(request_ack===0); #0.319;
end endtask
task receive;
begin
  wait(response_req===1); #(HALF*9+PHASE); response_ack=1;
  wait(response_req===0); #(HALF*7+PHASE); response_ack=0;
  #(HALF*12+PHASE);
end endtask
task transaction(input integer wr, addr, data, mask);
begin offer(wr,addr,data,mask); source_return(); receive(); end endtask
initial begin
  $dumpfile("trace.vcd"); $dumpvars(0,BoundaryBench);
  #0.3; restart();
  // Initialize every RAM byte. ROM instead rejects these writes.
  for(i=0;i<16;i=i+1) begin latency=i; transaction(1,i*2,(i*4127)^16'hb5a3,3); end
  for(i=0;i<128;i=i+1) begin
    latency=(i*7)%16;
    transaction((i%3)==0,(i*13)%64,(i/2)*1237,i%4);
  end
  // Exercise every mask on a legal aligned address, including both single bytes.
  for(i=0;i<4;i=i+1) begin transaction(1,8,16'hc35a^(i*16'h3311),i); transaction(0,8,0,0); end
  // A held incoming request cannot execute again even after response delivery.
  latency=0; offer(1,4,16'hd173,3); wait(request_ack===1); receive();
  before_count=accepted; #(HALF*30);
  if(accepted!=before_count) $fatal(1,"MEMORY_REEXECUTION"); source_return();
  // A second request must wait through a stalled response AND delayed ack return.
  offer(0,4,0,0); source_return(); wait(response_req===1);
  offer(0,6,0,0); before_count=accepted; #(HALF*25);
  if(request_ack || accepted!=before_count) $fatal(1,"MEMORY_CAPACITY");
  response_ack=1; wait(response_req===0); #(HALF*25);
  if(request_ack || accepted!=before_count) $fatal(1,"MEMORY_CAPACITY");
  response_ack=0; source_return(); receive();
  // Abort before backend acceptance, after commit/before response, offered response,
  // and after delivery/during return. Readback distinguishes abort from rollback.
  accept=0; offer(1,4,16'haaaa,3); #(HALF*15); restart();
  transaction(0,4,0,0);
  latency=15; offer(1,4,16'h5678,3); wait(request_ack===1); restart();
  transaction(0,4,0,0);
  latency=0; offer(1,4,16'h9abc,3); source_return(); wait(response_req===1); restart();
  transaction(0,4,0,0);
  offer(1,4,16'hdef0,3); source_return(); wait(response_req===1);
  #0.217; response_ack=1; #0.271; restart(); transaction(0,4,0,0);
  // Reset an offered request before a synchronizer can sample it.
  @(negedge clock); offer(1,4,16'hffff,3); #0.019; restart(); transaction(0,4,0,0);
  // Assertion works with the clock stopped; release waits for local clock edges.
  @(negedge clock); runClock=0; restart(); offer(0,4,0,0); #(HALF*20);
  if(request_ack || response_req || backend_fire) $fatal(1,"MEMORY_STOPPED_CLOCK");
  runClock=1; source_return(); receive();
  if(resets!=7 || outstanding!=0) $fatal(1,"MEMORY_ACTIVITY");
  $display("BOUNDARY_PASS memory accepted=%0d delivered=%0d effects=%0d resets=%0d",accepted,delivered,effects,resets);
  $finish;
end
initial begin #5000000; $fatal(1,"BOUNDARY_DEADLINE"); end
endmodule
