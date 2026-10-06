# SPDX-License-Identifier: Apache-2.0
"""Encoding-specific event oracles applied to actual emitted architecture probes."""
import argparse
import json
from pathlib import Path
import platform
import re
import subprocess
import sys

from run import ROOT, read_sources
sys.path.insert(0, str(ROOT / "tools"))
from check_export import validate_export
from compare_controllers import sha, random_words

FIXTURES = {"dualrail":"DualRailExample", "to_async":"ToAsyncExample",
            "to_clocked":"ToClockedExample", "bridge_roundtrip":"BridgeRoundTripExample"}


def execute(name, sources, bench, directory, parameters=(), diagnostic=None):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "bench.sv"
    path.write_text(bench, encoding="utf-8")
    executable = directory / "bench.vvp"
    compile_command = ["iverilog", "-g2012", "-s", "ArchitectureBench", *parameters, "-o", str(executable), str(path), *map(str,sources)]
    result = subprocess.run(compile_command, capture_output=True, text=True, timeout=30)
    (directory / "compile.log").write_text(result.stdout+result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"ARCH_COMPILE: {name}: {result.stderr}")
    result = subprocess.run(["vvp", str(executable)], cwd=directory, capture_output=True, text=True, timeout=30)
    log = result.stdout+result.stderr
    (directory / "simulation.log").write_text(log, encoding="utf-8")
    fatals = re.findall(r"^FATAL: [^\n]*?: (\w+)", log, re.M)
    if diagnostic:
        if result.returncode != 1 or fatals != [diagnostic] or "ARCH_PASS" in log:
            raise RuntimeError(f"ARCH_WRONG_REJECTION:{name}: {log}")
    elif result.returncode or fatals or len(re.findall(r"^ARCH_PASS .+$", log, re.M)) != 1:
        raise RuntimeError(f"ARCH_FAILURE:{name}: {log}")
    record = {"case":name,"status":"EXPECTED_REJECTION" if diagnostic else "PASS", "diagnostic":diagnostic,
        "compile":compile_command,"bench_sha256":sha(path), "sources":{p.name:sha(p) for p in sources},
        "activity":re.findall(r"^ARCH_PASS .+$",log,re.M)}
    (directory / "case.json").write_text(json.dumps(record,indent=2),encoding="utf-8")
    print(f"{name}: {record['status']}",flush=True)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generated",type=Path,default=ROOT / "target/generated")
    parser.add_argument("--output",type=Path,default=ROOT / "target/verification/architecture")
    args=parser.parse_args()
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    record={"status":"RUNNING","platform":platform.platform(),"python":sys.version,"cases":[],"exports":{},
            "checker_sha256":sha(Path(__file__)), "bench_sha256":{p.name:sha(p) for p in (ROOT / 'verification/architecture').glob('*.sv')}}
    report=output / "report.json"
    def save(): report.write_text(json.dumps(record,indent=2)+'\n',encoding="utf-8")
    save()
    try:
        sources={}
        for fixture in FIXTURES:
            directory=args.generated.resolve()/fixture
            record["exports"][fixture]=validate_export(directory)
            destination=output / "sources" / fixture;destination.mkdir(parents=True,exist_ok=True)
            sources[fixture]=[]
            for original in read_sources(directory):
                path=destination/original.name;path.write_bytes(original.read_bytes());sources[fixture].append(path)
        record["simulator"]=subprocess.run(["iverilog","-V"],capture_output=True,text=True,check=True).stdout.splitlines()[0]
        dual=(ROOT / "verification/architecture/dualrail.sv").read_text()
        bridges=(ROOT / "verification/architecture/bridges.sv").read_text()
        trip=(ROOT / "verification/architecture/roundtrip.sv").read_text()
        for seed in range(8):
            rng=random_words(seed)
            overrides=[]
            for cell in [f"{kind}{i}" for i in range(8) for kind in ("zero","one","present")]+["completion"]:
                overrides.append(f"defparam dut.ca_primitive_{cell}.DELAY_FS={1000000*(1+next(rng)%10)};")
            bench=dual.replace("endmodule",'\n'.join(overrides)+'\nendmodule')
            name=f"dualrail_seed_{seed}"
            record["cases"].append(execute(name,sources["dualrail"],bench,output/name))
        for fixture,mode in (("to_async",1),("to_clocked",0)):
            record["cases"].append(execute(fixture,sources[fixture],bridges,output/fixture,[f"-PArchitectureBench.TO_ASYNC={mode}"]))
        for source,sink,phase in ((7,11,3),(11,7,1),(5,5,0),(3,19,7)):
            name=f"roundtrip_{source}_{sink}_{phase}"
            record["cases"].append(execute(name,sources["bridge_roundtrip"],trip,output/name,
                [f"-PArchitectureBench.{key}={value}" for key,value in (("SOURCE_HALF",source),("SINK_HALF",sink),("SINK_PHASE",phase))]))
        # Mutate actual emitted RTL; require the intended external protocol checker.
        mutations=[("dualrail","first_bit","DUAL_EARLY_COMPLETE",dual,[],r"assign in_ack = [^;]+;","assign in_ack = out_zero[0] | out_one[0];"),
                   ("dualrail","stateless_completion","DUAL_EARLY_SPACER",dual,[],r"assign in_ack = [^;]+;","assign in_ack = &(out_zero | out_one);"),
                   ("to_async","ack_sync_bypass","ACK_SYNC_EARLY",bridges,["-PArchitectureBench.TO_ASYNC=1"],r"ack_stages_1 <= ack_stages_0;","ack_stages_1 <= out_ack;"),
                   ("to_clocked","req_sync_bypass","REQ_SYNC_EARLY",bridges,["-PArchitectureBench.TO_ASYNC=0"],r"request_stages_1 <= request_stages_0;","request_stages_1 <= in_req;")]
        for fixture,name,diagnostic,bench,parameters,pattern,replacement in mutations:
            original=next(p for p in sources[fixture] if p.name==FIXTURES[fixture]+".sv")
            changed,count=re.subn(pattern,replacement,original.read_text(encoding="utf-8"))
            if count!=1: raise RuntimeError(f"ARCH_MUTATION_TARGET:{name}:{count}")
            mutant=original.parent/(name+".sv");mutant.write_text(changed,encoding="utf-8")
            record["cases"].append(execute(name,[mutant if p==original else p for p in sources[fixture]],bench,output/name,parameters,diagnostic))
        record["status"]="PASS"
    except BaseException as error:
        record.update(status="ERROR",error=str(error));save();raise
    save();print(f"Architecture evidence: {report}")


if __name__=="__main__": main()
