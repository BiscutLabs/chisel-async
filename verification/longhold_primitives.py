# SPDX-License-Identifier: Apache-2.0
"""Independent unanimity/hold tables for the actual packaged asymmetric cells."""
import itertools
from pathlib import Path
import subprocess


def next_c(previous, values, sizes, masks):
    groups, offset = [], 0
    for size, mask in zip(sizes, masks):
        groups.append([bool((values >> (offset+i) & 1) ^ (mask >> i & 1)) for i in range(size)])
        offset += size
    common, rising, falling = groups
    if all(common) and all(rising):
        return 1
    if not any(common) and not any(falling):
        return 0
    return previous


def check_primitives(sources, output):
    output.mkdir(parents=True, exist_ok=True)
    configs = ((3,0,0,0,0,0,0), (1,1,1,1,0,1,0), (1,0,1,0,0,0,0),
               (1,1,1,1,0,0,0), (2,2,1,1,2,1,0), (3,0,0,0,0,0,1))
    records = []
    for index, config in enumerate(configs):
        common, rising, falling, cm, rm, fm, reset = config
        sizes, masks = config[:3], config[3:6]
        width = sum(sizes)
        stimuli = []
        for first, second in itertools.product(range(1 << width), repeat=2):
            previous = reset
            stimuli.append("reset=1; #(D+1); if(q!==RESET_VALUE[0]) $fatal(1,\"C_RESET_ORACLE\"); reset=0;")
            for value in (first, second):
                expected = next_c(previous, value, sizes, masks)
                c = value & ((1 << common)-1)
                r = (value >> common) & ((1 << rising)-1) if rising else 1
                f = value >> (common+rising) if falling else 0
                stimuli.append(f"common={c}; rising={r}; falling={f}; #(D-1); "
                    f"if(q!==1'b{previous}) $fatal(1,\"C_EARLY_ORACLE\"); #2; "
                    f"if(q!==1'b{expected}) $fatal(1,\"C_STATE_ORACLE\");")
                previous = expected
        checks = 2 * (1 << width)**2
        bench = f"""module PrimitiveBench;
timeunit 1fs; timeprecision 1fs;
parameter D=1000, RESET_VALUE={reset};
reg reset=0;
reg [{common-1}:0] common=0;
reg [{max(1,rising)-1}:0] rising=0;
reg [{max(1,falling)-1}:0] falling=0;
wire q;
ChiselAsyncAsymmetricC_v1 #(.COMMON({common}),.RISING({rising}),.FALLING({falling}),
.COMMON_INVERT({cm}),.RISING_INVERT({rm}),.FALLING_INVERT({fm}),.RESET_VALUE(RESET_VALUE),.DELAY_FS(D)) dut(.*);
initial begin #1;
{chr(10).join(stimuli)}
$display("PRIMITIVE_PASS checks={checks}"); $finish; end
initial begin #100000000000; $fatal(1,"PRIMITIVE_DEADLINE"); end
endmodule
"""
        path = output / f"asymmetric_{index}.sv"
        path.write_text(bench, encoding="utf-8")
        for delay in (1000, 10000):
            executable = output / f"asymmetric_{index}_{delay}.vvp"
            command = ["iverilog", "-g2012", "-s", "PrimitiveBench", f"-PPrimitiveBench.D={delay}",
                       "-o", str(executable), str(path), *map(str, sources)]
            built = subprocess.run(command, capture_output=True, text=True, timeout=30)
            if built.returncode:
                raise RuntimeError(f"Primitive compilation: {built.stdout}{built.stderr}")
            result = subprocess.run(["vvp", str(executable)], capture_output=True, text=True, timeout=30)
            (output / f"asymmetric_{index}_{delay}.log").write_text(result.stdout+result.stderr, encoding="utf-8")
            if result.returncode or result.stdout.count(f"PRIMITIVE_PASS checks={checks}") != 1:
                raise RuntimeError(f"Primitive state/delay check failed: {index}/{delay}: {result.stdout}")
            records.append({"configuration": config, "delay_fs": delay, "checks": checks})
    return records
