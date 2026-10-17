# SPDX-License-Identifier: Apache-2.0
"""Check passive whole-transform models, native stages, and strict export bindings."""
import argparse
import json
import random
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from check_export import validate_export


def require(ok, diagnostic):
    if not ok:
        raise ValueError(diagnostic)


def execute(directory, sources, text, expected=None):
    directory.mkdir(parents=True, exist_ok=False)
    bench=directory / "bench.sv"
    bench.write_text(text)
    binary=directory / "bench.vvp"
    build=subprocess.run(["iverilog", "-g2012", "-s", "PassiveBench", "-o", str(binary),
                          str(bench), *map(str,sources)], capture_output=True,text=True,timeout=60)
    (directory/"compile.log").write_text(build.stdout+build.stderr)
    require(build.returncode==0, "PASSIVE_COMPILE")
    run=subprocess.run(["vvp",str(binary)],capture_output=True,text=True,timeout=60)
    log=run.stdout+run.stderr
    (directory/"simulation.log").write_text(log)
    if expected is None:
        require(run.returncode==0 and log.splitlines().count("PASSIVE_PASS")==1 and
                not re.search(r"FATAL:|ERROR:",log),"PASSIVE_SIMULATION")
    else:
        sites=[i for i,line in enumerate(text.splitlines(),1) if f'$fatal(1,"{expected}")' in line]
        require(len(sites)==1,"PASSIVE_FATAL_SITE")
        pattern=r"^FATAL: "+re.escape(str(bench))+":"+str(sites[0])+": "+expected+r"\r?\n\s*Time: [0-9]+\s+Scope: PassiveBench(?:\.[A-Za-z0-9_]+)*\r?$"
        require(run.returncode==1 and len(re.findall(r"^FATAL:",log,re.M))==1 and
                re.search(pattern,log,re.M),"PASSIVE_WRONG_REJECTION")


def primitive_bench():
    return """module PassiveBench;
  timeunit 1ns; timeprecision 1ps;
  reg [7:0] a=0; wire [7:0] q, oldq; reg reset=1;
  ChiselAsyncPassiveDataAllowance_v1 #(.WIDTH(8),.DELAY_FS(10000000)) dut(.a(a),.q(q));
  ChiselAsyncControlGate_v1 #(.WIDTH(8),.DELAY_FS(10000000)) old(.reset(reset),.a(a),.b(8'b0),.q(oldq));
  initial begin
    #11; a=8'hff; #11;
    if(q!==8'hff || oldq!==0) $fatal(1,"PASSIVE_RESET_MASKED");
    a=8'hxx; #11;
    if(q!==8'hxx) $fatal(1,"PASSIVE_X_MASKED");
    a=8'hzz; #11;
    if(q!==8'hzz) $fatal(1,"PASSIVE_Z_MASKED");
    a=0; #11; a=8'hff; #2; a=0; #9;
    if(q!==0) $fatal(1,"PASSIVE_NOT_INERTIAL");
    reset=0; a=8'h5a; #11;
    if(q!==8'h5a || oldq!==8'h5a) $fatal(1,"PASSIVE_DATA");
    $display("PASSIVE_PASS"); $finish;
  end
endmodule
"""


def stage_bench(top,click):
    transfer = """
      in_bits=value; #1; in_req=~in_req;
      wait(in_ack===in_req); wait(out_req!==out_ack);
      if(out_bits!==(value^8'ha5)) $fatal(1,"PASSIVE_TOKEN");
      in_bits=8'hxx;
      #40;
      if(out_bits!==(value^8'ha5)) $fatal(1,"PASSIVE_HOLD");
      out_ack=out_req; #80;
""" if click else """
      in_bits=value; #1; in_req=1;
      wait(in_ack===1); wait(out_req===1);
      if(out_bits!==(value^8'ha5)) $fatal(1,"PASSIVE_TOKEN");
      in_req=0; wait(in_ack===0); in_bits=8'hxx;
      #40;
      if(out_bits!==(value^8'ha5)) $fatal(1,"PASSIVE_HOLD");
      out_ack=1; wait(out_req===0); out_ack=0; #80;
"""
    return f"""module PassiveBench;
  timeunit 1ns; timeprecision 1ps;
  reg reset=0, in_req=0, out_ack=0;
  reg [7:0] in_bits=8'hxx; wire in_ack,out_req; wire [7:0] out_bits;
  {top} dut(.reset(reset),.in_req(in_req),.in_bits(in_bits),.in_ack(in_ack),
           .out_req(out_req),.out_bits(out_bits),.out_ack(out_ack));
  initial begin #20000; $fatal(1,"PASSIVE_DEADLINE"); end
  task token(input [7:0] value); begin {transfer} end endtask
  integer i;
  initial begin
    #1; reset=1; #100; reset=0; #100;
    if(in_ack!==0 || out_req!==0) $fatal(1,"PASSIVE_IDLE_X_EVENT");
    for(i=0;i<16;i=i+1) token(i*17);
    in_bits=8'hf0; #1; in_req={'~in_req' if click else '1'};
    wait(out_req!==out_ack); #40;
    reset=1; in_req=0; out_ack=0; in_bits=8'hxx; #100;
    if(in_ack!==0 || out_req!==0) $fatal(1,"PASSIVE_RESET_EVENT");
    reset=0; #100; token(8'h3c); token(8'h00);
    $display("PASSIVE_PASS"); $finish;
  end
endmodule
"""


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exports",type=Path,default=ROOT/"build/passive-allowance-exports")
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    report={"status":"RUNNING","cases":[]}
    (args.output/"report.json").write_text(json.dumps(report,indent=2))
    models=ROOT/"src/main/resources/chiselasync/sv"
    sources=[models/"ChiselAsyncPassiveDataAllowance_v1.sv",models/"ChiselAsyncControlGate_v1.sv"]
    execute(args.output/"primitive",sources,primitive_bench())
    report["cases"].append("primitive:X/Z,reset-independent,inertial,legacy-reset")
    mutant=args.output/"masked.sv"
    mutant.write_text(sources[0].read_text().replace("assign #DELAY_FS q = a;","assign #DELAY_FS q = 0;"))
    execute(args.output/"masked-control",[mutant,sources[1]],primitive_bench(),"PASSIVE_RESET_MASKED")
    report["cases"].append("negative:reset-mask")
    for click in (False,True):
      for passive in (False,True):
        name=f"{'click' if click else 'bd'}-{'passive' if passive else 'default'}"
        directory=args.exports/name
        contract=json.loads((directory/"contract.json").read_text())
        top=contract["manifest"]["top"]
        source=[directory/s.strip() for s in (directory/"filelist.f").read_text().splitlines() if s.strip()]
        execute(args.output/name,source,stage_bench(top,click))
        validate_export(directory)
        report["cases"].append(name+":18tokens,invalid-X,stalled-output,immediate-reuse,reset,strict-export")
        if passive:
            main_source=directory/(top+".sv")
            main_text=main_source.read_text()
            require(main_text.count(".DELAY_FS(11000000)")==1,"PASSIVE_GUARD_MUTATION_SITE")
            short=args.output/(name+"-short.sv")
            short.write_text(main_text.replace(".DELAY_FS(11000000)",".DELAY_FS(0)"))
            execute(args.output/(name+"-short-control"),
                    [short if p==main_source else p for p in source],stage_bench(top,click),"PASSIVE_TOKEN")
            report["cases"].append(name+":negative-short-request")
            # Actual independent primitive delay overrides inside declared cell bounds.
            # Data/request/output/ACK guards stay at their explicit policy values.
            for seed in (19,47,83):
                rng=random.Random(seed)
                varied=args.output/(name+f"-seed{seed}.sv")
                changed=re.sub(r"\.DELAY_FS\(1000000\)",
                               lambda _:f".DELAY_FS({rng.randint(1,10)*1000000})",main_text)
                require(changed!=main_text,"PASSIVE_RANDOMIZED_ACTIVITY")
                varied.write_text(changed)
                execute(args.output/(name+f"-seed{seed}"),
                        [varied if p==main_source else p for p in source],stage_bench(top,click))
                report["cases"].append(name+f":randomized-cell-delays-seed{seed}")
    for name in ("typed","bd-seeded","click-seeded"):
        validate_export(args.exports/name)
        report["cases"].append(name+":strict-export")
    report["status"]="PASS"
    (args.output/"report.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report,indent=2))

if __name__=="__main__":
    main()
