// SPDX-License-Identifier: Apache-2.0
// Test-only owner-obligation monitor; not synthesizable circuit logic.
module MutexContract;
  timeunit 1fs; timeprecision 1fs;
  parameter integer POLICY=0, FAULT=0;
  parameter logic [31:0] SEED=1;
  parameter time RESOLUTION=100;
  reg reset=0, reset_permitted=1;
  reg [1:0] request=0;
  wire [1:0] physical_model_grant;
  reg inject=0;
  wire [1:0] grant = (FAULT==5 && inject) ? 2'b11 :
                     (FAULT==6 && inject) ? 2'b00 :
                     (FAULT==7 && inject) ? 2'b10 : physical_model_grant;
  ChiselAsyncMutex_v1 #(.POLICY(POLICY), .SEED(SEED),
    .RESOLVE_FS(RESOLUTION), .RESOLVE_MAX_FS(RESOLUTION))
    dut(reset,request,physical_model_grant);

  reg [1:0] previous_grant=0, previous_request=0, wait_release=0;
  integer grants=0, returns=0, epochs=0, held_checks=0, unresolved_checks=0;
  integer winner, loser, round;

  // This is an owner precondition, supplied separately from the Mutex reset pin.
  always @(posedge reset)
    if (!reset_permitted) $fatal(1,"MUTEX_RESET_WITHOUT_QUIESCENCE");
  always @(negedge reset)
    if (request!==0) $fatal(1,"MUTEX_STALE_REQUEST_AT_REARM");
  always @(request or grant or reset) begin
    if (reset) begin
      previous_request=request; previous_grant=grant; wait_release=0;
    end else begin
      if ($isunknown(grant) || grant===3) $fatal(1,"MUTEX_GRANT_EXCLUSION");
      if (previous_grant!=0 && grant!=0 && grant!=previous_grant)
        $fatal(1,"MUTEX_MISSING_ZERO_HANDOVER");
      if (previous_grant!=0 && (previous_grant & request)==previous_grant &&
          grant!=previous_grant) $fatal(1,"MUTEX_HELD_GRANT_REVOKED");
      for (integer i=0;i<2;i=i+1) begin
        if (!grant[i]) wait_release[i]=0;
        if (previous_request[i] && !request[i]) begin
          if (!grant[i]) $fatal(1,"MUTEX_REQUEST_WITHDRAWN_BEFORE_SERVICE");
          wait_release[i]=1;
        end
        if (!previous_request[i] && request[i] && wait_release[i])
          $fatal(1,"MUTEX_GRANT_NOT_RELEASED_BEFORE_REUSE");
      end
      if (grant!=previous_grant) begin
        if (grant!=0) begin
          if ((grant & request)!=grant) $fatal(1,"MUTEX_GRANT_WITHOUT_REQUEST");
          grants=grants+1;
        end else returns=returns+1;
      end
      previous_request=request; previous_grant=grant;
    end
  end

  task automatic cold_reset;
    begin
      reset_permitted=1; reset=1; request=0;
      #(2*RESOLUTION+1);
      if (grant!==0) $fatal(1,"MUTEX_RESET_DID_NOT_CLEAR");
      reset=0; #1;
      epochs=epochs+1;
    end
  endtask
  task automatic release_all;
    begin request=0; wait(grant==0); #1; end
  endtask
  initial begin
    #1; cold_reset();
    if (FAULT==1) begin request=1; #1; request=0; end
    if (FAULT==2) begin
      request=1; wait(grant==1); #1; request=0; #1; request=1;
    end
    if (FAULT==3) begin
      reset=1; request=1; #(2*RESOLUTION+1); reset=0;
    end
    if (FAULT==4) begin
      request=1; wait(grant==1); #1; reset_permitted=0; reset=1;
    end
    if (FAULT>=5) begin
      request=1; wait(grant==1); #1;
      if (FAULT==7) request=2;
      inject=1;
    end
    if (FAULT!=0) begin #(4*RESOLUTION); $fatal(1,"MUTEX_FAULT_ESCAPED"); end
    for (round=0;round<3;round=round+1) begin
      // A contender can be unresolved for the entire sampled interval. There
      // is no side effect to count or timeout-based forced grant in this owner.
      request=3;
      for (integer i=0;i<5;i=i+1) begin
        #(RESOLUTION/10);
        if (grant!==0) $fatal(1,"MUTEX_UNRESOLVED_SIDE_EFFECT");
        unresolved_checks=unresolved_checks+1;
      end
      wait(grant!=0); winner=grant; loser=3-winner; #1;
      #(2*RESOLUTION);
      if (grant!==winner) $fatal(1,"MUTEX_WINNER_NOT_RETAINED");
      held_checks=held_checks+1;
      // The losing request persists. Release of the winner is separate from
      // observing grant return; the waiting request is then serviced.
      request=loser; wait(grant==0); wait(grant==loser); #1;
      release_all();
      request=1; wait(grant==1); #1; release_all();
      request=2; wait(grant==2); #1; release_all();
      cold_reset();
    end
    if (grants!=12 || returns!=12 || epochs!=4 || held_checks!=3 || unresolved_checks!=15)
      $fatal(1,"MUTEX_CONTRACT_ACTIVITY");
    $display("MUTEX_CONTRACT_PASS grants=%0d returns=%0d epochs=%0d unresolved=%0d",
      grants,returns,epochs,unresolved_checks);
    $finish;
  end
  initial begin #(1000*RESOLUTION); $fatal(1,"MUTEX_CONTRACT_DEADLINE"); end
endmodule
