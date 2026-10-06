# SPDX-License-Identifier: Apache-2.0
"""Independent integer oracles for Bundle->UInt and SInt->nested Bundle stages."""
import subprocess
from check_export import validate_export
from run import read_sources
from compare_controllers import sha


def check_payloads(generated, output):
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for fixture in ("sum", "signed"):
        directory = generated / f"longhold_{fixture}"
        resolution = validate_export(directory)
        if fixture == "sum":
            values = [(0,0),(255,255),(255,1),(255,1)] + [(a,(a*73+19)%256) for a in range(256)]
            expected = [a+b for a,b in values]
            input_width, output_width = 16, 9
            inputs = [(a << 8)|b for a,b in values]
            ports = ".in_bits_left(input_bits[15:8]),.in_bits_right(input_bits[7:0]),.out_bits(output_bits)"
            module = "LongHoldSumExample"
        else:
            values = list(range(-256,256)) + [0,0,255,-256]
            input_width, output_width = 9, 19
            inputs = [value & 511 for value in values]
            expected = [(((value-17)&1023)<<9) | (int(value>=0)<<8) | (value&255) for value in values]
            ports = (".in_bits(input_bits),.out_bits_value(output_bits[18:9]),"
                     ".out_bits_nonnegative(output_bits[8]),.out_bits_lanes_1(output_bits[7:4]),"
                     ".out_bits_lanes_0(output_bits[3:0])")
            module = "LongHoldSignedExample"
        count = len(inputs)
        init = "\n".join(f"stimulus[{i}]={input_width}'h{v:x}; expected[{i}]={output_width}'h{e:x};"
                         for i,(v,e) in enumerate(zip(inputs, expected)))
        bench = f"""`timescale 1ns/1ps
module PayloadBench;
reg reset=0,in_req=0,out_ack=0;
reg [{input_width-1}:0] input_bits=0;
wire [{output_width-1}:0] output_bits;
wire in_ack,out_req;
reg [{input_width-1}:0] stimulus[0:{count-1}];
reg [{output_width-1}:0] expected[0:{count-1}], held;
reg holding=0;
integer i,j,accepted=0,delivered=0,returned=0,offered=0;
{module} dut(.reset(reset),.in_req(in_req),.in_ack(in_ack),.out_req(out_req),.out_ack(out_ack),{ports});
always @(posedge in_ack) if(!reset) accepted=accepted+1;
always @(posedge out_req) if(!reset) begin held=output_bits; holding=1; offered=offered+1; end
always @(output_bits) if(!reset && holding && output_bits!==held) $fatal(1,"TYPED_DATA_HOLD");
always @(posedge out_ack) if(!reset) begin
  if(delivered>=accepted || delivered>={count}) $fatal(1,"TYPED_UNEXPECTED_TOKEN");
  if(output_bits!==expected[delivered]) $fatal(1,"TYPED_PAYLOAD_MISMATCH index=%0d",delivered);
  delivered=delivered+1;
end
always @(negedge out_ack) if(!reset) begin holding=0; returned=returned+1; end
initial begin
{init}
#1 reset=1; #1000;
if(output_bits!==0 || in_ack!==0 || out_req!==0) $fatal(1,"TYPED_RESET");
reset=0; #1000;
fork
begin for(i=0;i<{count};i=i+1) begin
  input_bits=stimulus[i]; #2 in_req=1; wait(in_ack===1); #13 in_req=0; wait(in_ack===0); #7;
end end
begin for(j=0;j<{count};j=j+1) begin
  wait(out_req===1); #(1+(j*11)%53) out_ack=1;
  wait(out_req===0); #(1+(j*7)%37) out_ack=0; #1;
end end
join
#1000;
if(accepted!={count} || delivered!={count} || returned!={count} || offered!={count} || in_ack!==0 || out_req!==0)
  $fatal(1,"TYPED_INCOMPLETE");
reset=1; #1000;
if(output_bits!==0 || in_ack!==0 || out_req!==0) $fatal(1,"TYPED_RESET_RESTART");
$display("TYPED_PASS count={count}"); $finish;
end
initial begin #1000000; $fatal(1,"TYPED_DEADLINE"); end
endmodule
"""
        work = output / fixture
        work.mkdir(exist_ok=True)
        path = work / "bench.sv"
        path.write_text(bench, encoding="utf-8")
        executable = work / "bench.vvp"
        sources = read_sources(directory)
        compiled = subprocess.run(["iverilog", "-g2012", "-s", "PayloadBench", "-o", str(executable),
                                   str(path), *map(str, sources)], capture_output=True, text=True, timeout=30)
        (work / "compile.log").write_text(compiled.stdout+compiled.stderr, encoding="utf-8")
        if compiled.returncode:
            raise RuntimeError(f"Typed fixture compilation failed: {fixture}")
        simulation = subprocess.run(["vvp", str(executable)], capture_output=True, text=True, timeout=30)
        (work / "simulation.log").write_text(simulation.stdout+simulation.stderr, encoding="utf-8")
        if simulation.returncode or simulation.stdout.count(f"TYPED_PASS count={count}") != 1:
            raise RuntimeError(f"Typed fixture failed: {fixture}: {simulation.stdout}")
        results.append({"fixture": fixture, "transfers": count, "resolution": resolution,
                        "bench_sha256": sha(path), "source_sha256": {p.name: sha(p) for p in sources}})
    return results
