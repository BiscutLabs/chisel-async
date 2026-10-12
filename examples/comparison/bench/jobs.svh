// The comparison's workload, shared by all four testbenches.
localparam integer TOKENS = 64;     // AddPipeline operand pairs
localparam integer JOBS = 24;       // Gcd jobs
function automatic [7:0] op_a(input integer i); op_a = (i * 37 + 11) % 256; endfunction
function automatic [7:0] op_b(input integer i); op_b = (i * 91 + 7) % 256; endfunction
// Gcd jobs: the edge cases the library's tests name, the worst case for
// Euclid by subtraction (255, 1), then a spread of ordinary pairs.
function automatic [7:0] job_a(input integer i);
  case (i) 0: job_a = 0; 1: job_a = 12; 2: job_a = 0; 3: job_a = 255; default: job_a = op_a(i) | 1; endcase
endfunction
function automatic [7:0] job_b(input integer i);
  case (i) 0: job_b = 9; 1: job_b = 0; 2: job_b = 0; 3: job_b = 1; default: job_b = op_b(i) | 2; endcase
endfunction
function automatic [7:0] gcd(input [7:0] a0, input [7:0] b0);
  reg [7:0] a, b;
  begin
    a = a0; b = b0;
    while (!(a == b || a == 0 || b == 0)) if (a > b) a = a - b; else b = b - a;
    gcd = (a == 0) ? b : a;
  end
endfunction
function automatic integer steps(input [7:0] a0, input [7:0] b0);
  reg [7:0] a, b;
  begin
    a = a0; b = b0; steps = 0;
    while (!(a == b || a == 0 || b == 0)) begin if (a > b) a = a - b; else b = b - a; steps = steps + 1; end
  end
endfunction
