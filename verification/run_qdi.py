# SPDX-License-Identifier: Apache-2.0
"""Bounded CA-08 RTL campaign: truth, indication, reset and composition obligations."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
import itertools
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "build.sbt").is_file())
sys.path.insert(0, str(ROOT / "verification"))
sys.path.insert(0, str(ROOT / "tools"))
from campaign_environment import identity
from check_export import nodes, validate_export
from compare_controllers import random_words, sha
from phase_reference import Protocol
from run import read_sources
from run_phase import delay_overrides, flat

FIXTURES = ("qdi_buffer", "qdi_packet", "qdi_not", "qdi_and", "qdi_or", "qdi_xor", "qdi_select",
            "qdi_adder", "qdi_constant", "qdi_fork", "qdi_join", "qdi_demux", "qdi_merge", "qdi_composition")
WIDTH = dict(qdi_buffer=3, qdi_packet=10, qdi_not=1, qdi_and=2, qdi_or=2, qdi_xor=2,
             qdi_select=3, qdi_adder=3, qdi_constant=3, qdi_fork=2, qdi_join=3, qdi_demux=3, qdi_merge=2)
FAULTS = {
    "wrong_value": ("qdi_xor", "QDI_VALUE"),
    "dropped_dependency": ("qdi_constant", "QDI_EARLY_VALID"),
    "stateless_return": ("qdi_constant", "QDI_EARLY_SPACER"),
    "early_fork_ack": ("qdi_fork", "QDI_FORK_EARLY_ACK"),
    "invalid_rail": ("qdi_buffer", "INVALID_RAIL"),
    "merge_contention": ("qdi_merge", "EXCLUSIVE_MERGE_CONTENTION"),
    "merge_return_contention": ("qdi_merge", "EXCLUSIVE_MERGE_CONTENTION"),
}
SETTLE = 500_000_000  # 500 ns: expose partial-phase errors; not a physical timing assertion.


def require(condition, diagnostic):
    if not condition:
        raise AssertionError(diagnostic)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def truth(fixture, value):
    """Ordinary value definitions, independent of rail/minterm implementation."""
    a, b, choice = bool(value & 1), bool(value & 2), bool(value & 4)
    if fixture == "qdi_not": return int(not a)
    if fixture == "qdi_and": return int(a and b)
    if fixture == "qdi_or": return int(a or b)
    if fixture == "qdi_xor": return int(a != b)
    if fixture == "qdi_select": return int(b if choice else a)
    if fixture == "qdi_adder": return int(a) + int(b) + int(choice)
    if fixture == "qdi_constant": return 1
    if fixture == "qdi_demux": return value & 3
    if fixture == "qdi_composition": return 2 * value
    return value


def permutations(width):
    # The ten-bit aggregate exhausts values, with four declared order pairs.
    # Claiming 10! squared orders would be a rather ambitious smoke test.
    return list(itertools.permutations(range(width))) if width <= 3 else [tuple(range(width)), tuple(reversed(range(width)))]


def case_contract(fixture):
    if fixture == "qdi_composition":
        return dict(steady_transfers=128, deliveries=128, reset_scenarios=["stalled_stream"], exact_capacity=False)
    width = WIDTH[fixture]
    base = (1 << width) * len(permutations(width)) ** 2
    if fixture == "qdi_fork":
        base *= 36
        # Full sweep, one partial-branch completion, three preserved spacer
        # completions and three complete restart broadcasts.
        return dict(steady_transfers=base, deliveries=3 * (base + 3) + 4,
                    reset_scenarios=["partial_valid", "partial_spacer", "partial_branch"], order_pairs=36)
    if fixture == "qdi_merge": base *= 2
    # Each partial-valid reset restarts one complete token. Each partial-spacer
    # reset preserves one delivery and restarts another. A held-valid reset aborts.
    return dict(steady_transfers=base, deliveries=base + 3 * (width - 1) + 1,
                reset_scenarios=[f"partial_{phase}_{k}" for phase in ("valid", "spacer") for k in range(1, width)] + ["held_valid"],
                rail_order_pairs=len(permutations(width)) ** 2)


def channel_catalog(manifest, root_only=False):
    result = []
    for node in ([manifest["design"]] if root_only else nodes(manifest["design"])):
        endpoints = {e["id"]: e for e in node["endpoints"]}
        prefix = "dut" + node["rtl_path"][len(manifest["top"]):] + "."
        for c in node["channels"]:
            width = sum(f["width"] for f in c["layout"])
            packed = lambda zero=False: "{" + ",".join(prefix + flat(f["source"].replace(".one", ".zero") if zero else f["source"])
                                                        for f in reversed(c["layout"])) + "}"
            result.append(dict(c, id=node["rtl_path"] + "::" + c["id"], local_id=c["id"],
                               root=node is manifest["design"], width=width, one=packed(),
                               zero=packed(True) if c["protocol"] == "dual-rail-rtz-v1" else "1'b0",
                               ack=prefix + flat(endpoints[c["acknowledge"]]["source"]),
                               req=prefix + flat(endpoints[c["request"]]["source"]) if "request" in c else "1'b0"))
    return result


def checked_overrides(manifest, seed):
    overrides = delay_overrides(manifest, seed)
    values = {match[1]: int(match[2]) for line in overrides
              if (match := re.fullmatch(r"defparam dut(\S*)\.DELAY_FS=(\d+);", line))}
    count = 0
    for node in nodes(manifest["design"]):
        policies = [t for t in node["timing"] if t["kind"] == "qdi-digital-v1"]
        if not policies: continue
        require(len(policies) == 1, "QDI_TIMING_POLICY")
        bounds = policies[0]["cells"]
        for primitive in node["primitives"]:
            if "DELAY_FS" not in primitive["parameters"]: continue
            key = primitive["rtl_path"][len(manifest["top"]):]
            require(not seed or key in values, "QDI_UNVARIED_PRIMITIVE")
            value = values[key] if seed else int(primitive["parameters"]["DELAY_FS"])
            require(int(bounds["min_fs"]) <= value <= int(bounds["max_fs"]), "QDI_DELAY_OUTSIDE_BOUNDS")
            count += 1
    require(count > 0, "QDI_MISSING_TIMING_CELLS")
    return overrides


def check_fixture_shape(fixture, manifest):
    channels = manifest["design"]["channels"]
    widths = lambda role: [sum(f["width"] for f in c["layout"]) for c in channels if c["role"] == role]
    expected = {
        "qdi_fork": ([2], [2, 2, 2]), "qdi_join": ([1, 2], [3]), "qdi_demux": ([3], [2, 2]),
        "qdi_merge": ([2, 2], [2]), "qdi_composition": ([2], [3]),
    }.get(fixture, ([WIDTH.get(fixture)], [WIDTH[fixture] if fixture in ("qdi_buffer", "qdi_packet") else 2 if fixture == "qdi_adder" else 1]))
    require((widths("input"), widths("output")) == expected, "QDI_FIXTURE_SHAPE")
    require(all(c["protocol"] == ("four-phase-bundled-v1" if fixture == "qdi_composition" else "dual-rail-rtz-v1") for c in channels), "QDI_FIXTURE_PROTOCOL")


def setup(manifest, ports, seed, root_only=False):
    """Drive typed ports through independent packed testbench variables."""
    lines = ["module QdiBench; timeunit 1fs; timeprecision 1fs;", "reg reset=0; integer trace, epoch=0;",
             "integer total_deliveries=0, reset_checks=0; localparam time STEP=" + str(SETTLE) + ";"]
    for port in ports:
        name = flat(port["source"])
        if name != "reset": lines.append(f'wire [{port["width"]-1}:0] {name};')
    lines.append(manifest["top"] + " dut(" + ",".join("." + flat(p["source"]) + "(" + flat(p["source"]) + ")" for p in ports) + ");")
    overrides = checked_overrides(manifest, seed)
    lines += overrides
    roots = {}
    endpoints = {e["id"]: e for e in manifest["design"]["endpoints"]}
    for index, c in enumerate(manifest["design"]["channels"]):
        name = "c" + str(index)
        width = sum(f["width"] for f in c["layout"])
        incoming = c["role"] == "input"
        root = dict(c, name=name, width=width, zero=name + "_zero", one=name + "_one", ack=name + "_ack", req=name + "_req")
        roots[c["id"]] = root
        rail = c["protocol"] == "dual-rail-rtz-v1"
        for kind in (["zero", "one"] if rail else ["one"]):
            lines.append(f'{"reg" if incoming else "wire"} [{width-1}:0] {name}_{kind}' + ("=0;" if incoming else ";"))
            for field in c["layout"]:
                original = flat(field["source"].replace(".one", ".zero") if kind == "zero" else field["source"])
                packed = f'{name}_{kind}[{field["lsb"]} +: {field["width"]}]'
                lines.append(f"assign {original if incoming else packed} = {packed if incoming else original};")
        actual_ack = flat(endpoints[c["acknowledge"]]["source"])
        lines.append(f'{"wire" if incoming else "reg"} {name}_ack' + (";" if incoming else "=0;"))
        lines.append(f"assign {name+'_ack' if incoming else actual_ack} = {actual_ack if incoming else name+'_ack'};")
        if not rail:
            actual_req = flat(endpoints[c["request"]]["source"])
            lines.append(f'{"reg" if incoming else "wire"} {name}_req' + ("=0;" if incoming else ";"))
            lines.append(f"assign {actual_req if incoming else name+'_req'} = {name+'_req' if incoming else actual_req};")
        if not incoming:
            lines.append(f"always @(posedge {name}_ack) if (!reset) total_deliveries++;")
    catalog = channel_catalog(manifest, root_only)
    for index, c in enumerate(catalog):
        lines += [f'wire [{c["width"]-1}:0] one_{index}={c["one"]}, zero_{index}={c["zero"]};',
                  f"integer complete_{index}=0;",
                  f'always @(posedge {c["ack"]}) if (!reset) complete_{index}++;',
                  f'always @(reset or {c["req"]} or {c["ack"]} or one_{index} or zero_{index}) if(trace)',
                  f'$fstrobe(trace,"E|%0d|%0d|%0b|{c["id"]}|%0b|%0b|%0h|%0h",$time,epoch,reset,{c["req"]},{c["ack"]},one_{index},zero_{index});']
    lines += ["task snapshot; begin"]
    for index, c in enumerate(catalog):
        lines += [f'$fdisplay(trace,"C|%0d|{c["id"]}|%0d",epoch,complete_{index}); complete_{index}=0;']
    lines += ["end endtask", "task clear_drivers; begin"]
    for c in roots.values():
        if c["role"] == "output": lines.append(c["ack"] + "=0;")
        else:
            lines.append(c["one"] + "=0;")
            lines.append(c["zero"] + "=0;" if c["protocol"] == "dual-rail-rtz-v1" else c["req"] + "=0;")
    lines += ["end endtask", "task recover; begin if(epoch) snapshot(); reset=1; #1; clear_drivers(); #10000000000;",
              "epoch++; reset=0; #10000000000; end endtask"]
    return lines, roots, catalog, overrides


def output_any(outputs):
    return " | ".join(f'({c["one"]} | {c["zero"]})' for c in outputs)


def choose_expr(outputs, field):
    return outputs[0][field] if len(outputs) == 1 else f'(selected ? {outputs[1][field]} : {outputs[0][field]})'


def strong_bench(fixture, manifest, ports, seed, root_only=False, stimulus=None):
    lines, roots, catalog, overrides = setup(manifest, ports, seed, root_only)
    inputs = [c for c in roots.values() if c["role"] == "input"]
    outputs = [c for c in roots.values() if c["role"] == "output"]
    width = WIDTH[fixture]
    expected_width = outputs[0]["width"]
    order = permutations(width)
    lines += [f"reg [{width-1}:0] drive_zero=0,drive_one=0; integer selected=0;",
              f"integer order[0:{len(order)*width-1}]; integer v,a,b,k,lane;",
              "task set_input; begin"]
    if fixture == "qdi_join":
        left, right = roots["left_input"], roots["right_input"]
        lines += [f'{left["one"]}=drive_one[2]; {left["zero"]}=drive_zero[2];',
                  f'{right["one"]}=drive_one[1:0]; {right["zero"]}=drive_zero[1:0];']
    elif fixture == "qdi_merge":
        for index, c in enumerate(inputs):
            lines.append(f'{c["one"]}=selected=={index} ? drive_one : 0; {c["zero"]}=selected=={index} ? drive_zero : 0;')
    else:
        c = inputs[0]
        lines.append(f'{c["one"]}=drive_one; {c["zero"]}=drive_zero;')
    lines += ["end endtask", "task drive_clear; begin drive_one=0;drive_zero=0;set_input();end endtask"]
    in_ack = (" && ".join(c["ack"] for c in inputs) if fixture == "qdi_join" else
              choose_expr(inputs, "ack") if fixture == "qdi_merge" else inputs[0]["ack"])
    input_any_ack = " | ".join(c["ack"] for c in inputs)
    one, zero = choose_expr(outputs, "one"), choose_expr(outputs, "zero")
    output_mask = (1 << expected_width) - 1
    ack_high = " ".join(f'{c["ack"]}=' + (f"selected=={i};" if len(outputs) > 1 else "1;") for i, c in enumerate(outputs))
    ack_low = " ".join(c["ack"] + "=0;" for c in outputs)
    lines += [f"function [{expected_width-1}:0] expected(input [{width-1}:0] value); begin case(value)"]
    lines += [f"{width}'d{v}: expected={expected_width}'d{truth(fixture,v)};" for v in range(1 << width)]
    lines += ["endcase end endfunction",
              "task arrive(input integer value,input integer arrival,input integer target); integer j,bitno; begin",
              "selected=" + ("(value>>2)&1;" if fixture == "qdi_demux" else "target;") + " drive_clear();",
              f"for(j=0;j<{width};j++) begin bitno=order[arrival*{width}+j];",
              "if(value&(1<<bitno)) drive_one[bitno]=1; else drive_zero[bitno]=1; set_input(); #STEP;",
              f'if(j<{width-1} && (({output_any(outputs)})!=0 || ({input_any_ack}))) $fatal(1,"QDI_EARLY_VALID"); end',
              f'wait(({one} | {zero})=={output_mask}); wait({in_ack});',
              f'if({one} !== expected(value) || {zero} !== ({expected_width}\'d{output_mask} ^ expected(value))) $fatal(1,"QDI_VALUE");']
    if fixture == "qdi_demux":
        lines.append(f'if(selected ? (({outputs[0]["one"]}|{outputs[0]["zero"]})!=0) : (({outputs[1]["one"]}|{outputs[1]["zero"]})!=0)) $fatal(1,"QDI_ROUTE");')
    lines += [f'#(3*STEP); if(({one}|{zero})!={output_mask} || {one}!==expected(value)) $fatal(1,"QDI_BACKPRESSURE_HOLD");',
              "end endtask",
              "task spacer(input integer returning); integer j,bitno; begin",
              ack_high + " #STEP;",
              f"for(j=0;j<{width};j++) begin bitno=order[returning*{width}+j]; drive_one[bitno]=0;drive_zero[bitno]=0;set_input();#STEP;",
              f'if(j<{width-1} && (({one}|{zero})!={output_mask} || !({in_ack}))) $fatal(1,"QDI_EARLY_SPACER"); end',
              f'wait(({output_any(outputs)})==0); wait(!({input_any_ack})); #STEP;', ack_low + " #STEP; end endtask",
              "task transfer(input integer value,input integer arrival,input integer returning,input integer target); begin",
              "arrive(value,arrival,target);spacer(returning);end endtask", "initial begin"]
    for i, permutation in enumerate(order):
        lines += [f"order[{i*width+j}]={bitno};" for j, bitno in enumerate(permutation)]
    lines += ['trace=$fopen("trace.txt","w");$fdisplay(trace,"QDI_TRACE|1"); recover();']
    if stimulus:
        lines.append("transfer(0,0,0,0);")
        if stimulus == "invalid_rail":
            lines += [f'{inputs[0]["zero"]}=1; {inputs[0]["one"]}=' + ("1;" if root_only else "0;")]
        elif stimulus == "merge_contention":
            lines += [f'{inputs[0]["one"]}=1; {inputs[1]["one"]}=' + ("1;" if root_only else "0;")]
        elif stimulus == "merge_return_contention":
            lines += [f'arrive(0,0,0);{outputs[0]["ack"]}=1;#1;',
                      f'{inputs[0]["zero"]}=0;{inputs[0]["one"]}=0;',
                      f'if(!{inputs[0]["ack"]}) $fatal(1,"QDI_RETURN_CONTENTION_NOT_REACHED");',
                      f'{inputs[1]["one"]}=1;']
        lines += ['#(10*STEP);snapshot();$fclose(trace);trace=0;$display("QDI_PREFIX_COMPLETE");$finish;end']
    else:
        lines += [f'for(lane=0;lane<{2 if fixture=="qdi_merge" else 1};lane++) for(v=0;v<{1<<width};v++) '
                  f'for(a=0;a<{len(order)};a++) for(b=0;b<{len(order)};b++) transfer(v,a,b,lane);']
        for k in range(1, width):
            lines += [f'drive_one={(1<<k)-1};drive_zero=0;set_input();#STEP;',
                      f'if(({output_any(outputs)})!=0 || ({input_any_ack})) $fatal(1,"QDI_RESET_PREFIX_VALID");',
                      f'$display("QDI_RESET:partial_valid_{k}");reset_checks++;recover();drive_clear();transfer({(1<<width)-1},0,{len(order)-1},0);',
                      f'arrive(0,0,0); {ack_high} #STEP; drive_zero={((1<<width)-1)^((1<<k)-1)};drive_one=0;set_input();#STEP;',
                      f'if(({one}|{zero})!={output_mask} || !({in_ack})) $fatal(1,"QDI_RESET_PREFIX_SPACER");',
                      f'$display("QDI_RESET:partial_spacer_{k}");reset_checks++;recover();drive_clear();transfer(0,{len(order)-1},0,0);']
        lines += ['arrive(0,0,0);$display("QDI_RESET:held_valid");reset_checks++;recover();drive_clear();transfer(0,0,0,0);',
                  f'if(total_deliveries!={case_contract(fixture)["deliveries"]} || reset_checks!={2*(width-1)+1}) $fatal(1,"QDI_ACTIVITY");',
                  'snapshot();$fclose(trace);trace=0;$display("QDI_PASS");$finish;end']
    lines += ['initial begin #100000000000000; $fatal(1,"QDI_DEADLINE");end', "endmodule"]
    return "\n".join(lines) + "\n", catalog, overrides


def fork_bench(manifest, ports, seed, root_only=False):
    lines, roots, catalog, overrides = setup(manifest, ports, seed, root_only)
    incoming = next(c for c in roots.values() if c["role"] == "input")
    outputs = [c for c in roots.values() if c["role"] == "output"]
    require(len(outputs) == 3, "QDI_FORK_SHAPE")
    one, zero, ack = (incoming[k] for k in ("one", "zero", "ack"))
    lines += ["integer branch_order[0:17];integer bit_order[0:3];integer v,a,b,c,d;",
              "task branch_ack(input integer index,input integer value);begin case(index)"]
    lines += [f'{i}:{o["ack"]}=value;' for i, o in enumerate(outputs)]
    lines += ["endcase end endtask", "task full_outputs(input integer value);begin"]
    for o in outputs:
        lines += [f'wait(({o["one"]}|{o["zero"]})==3);if({o["one"]}!==value[1:0]) $fatal(1,"QDI_VALUE");']
    lines += ["end endtask", "task transfer(input integer value,input integer arrival,input integer returning,input integer rise_order,input integer fall_order);integer j,bitno;begin",
              f'for(j=0;j<2;j++) begin bitno=bit_order[2*arrival+j];if(value&(1<<bitno)) {one}[bitno]=1;else {zero}[bitno]=1;#STEP;end',
              'full_outputs(value);#(3*STEP);',
              'for(j=0;j<3;j++) begin branch_ack(branch_order[3*rise_order+j],1);#STEP;',
              f'if(j<2 && {ack}) $fatal(1,"QDI_FORK_EARLY_ACK");',
              *[f'if(({o["one"]}|{o["zero"]})!=3 || {o["one"]}!==value[1:0]) $fatal(1,"QDI_FORK_DATA_HOLD");' for o in outputs],
              f'end wait({ack});',
              f'for(j=0;j<2;j++) begin bitno=bit_order[2*returning+j];{one}[bitno]=0;{zero}[bitno]=0;#STEP;end',
              f'wait(({output_any(outputs)})==0);',
              'for(j=0;j<3;j++) begin branch_ack(branch_order[3*fall_order+j],0);#STEP;',
              f'if(j<2 && !{ack}) $fatal(1,"QDI_FORK_EARLY_RETURN");end wait(!{ack});#STEP;end endtask', "initial begin"]
    for i, permutation in enumerate(itertools.permutations(range(3))):
        lines += [f"branch_order[{i*3+j}]={value};" for j, value in enumerate(permutation)]
    lines += ["bit_order[0]=0;bit_order[1]=1;bit_order[2]=1;bit_order[3]=0;",
              'trace=$fopen("trace.txt","w");$fdisplay(trace,"QDI_TRACE|1");recover();',
              'for(v=0;v<4;v++) for(a=0;a<2;a++) for(b=0;b<2;b++) for(c=0;c<6;c++) for(d=0;d<6;d++) transfer(v,a,b,c,d);',
              f'{one}=1;#STEP;$display("QDI_RESET:partial_valid");reset_checks++;recover();transfer(3,0,1,0,5);',
              f'{one}=3;full_outputs(3);#1;branch_ack(0,1);#STEP;if({ack}) $fatal(1,"QDI_FORK_EARLY_ACK");',
              '$display("QDI_RESET:partial_branch");reset_checks++;recover();transfer(0,1,0,5,0);',
              f'{zero}=3;full_outputs(0);#1;branch_ack(0,1);branch_ack(1,1);branch_ack(2,1);wait({ack});#STEP;{zero}=2;#STEP;',
              '$display("QDI_RESET:partial_spacer");reset_checks++;recover();transfer(2,0,1,2,3);',
              f'if(total_deliveries!={case_contract("qdi_fork")["deliveries"]} || reset_checks!=3) $fatal(1,"QDI_ACTIVITY");',
              'snapshot();$fclose(trace);trace=0;$display("QDI_PASS");$finish;end',
              'initial begin #100000000000000;$fatal(1,"QDI_DEADLINE");end', "endmodule"]
    return "\n".join(lines) + "\n", catalog, overrides


def mixed_bench(manifest, ports, seed, root_only=False):
    lines, roots, catalog, overrides = setup(manifest, ports, seed, root_only)
    incoming, outgoing = roots["in"], roots["out"]
    rng = random_words(seed + 711)
    words = list(range(4)) * 8 + [next(rng) % 4 for _ in range(32)]
    lines += ["integer words[0:63],i;integer stalled_accepts=0;",
              f'always @(posedge {incoming["ack"]}) if(!reset && epoch==2) stalled_accepts++;',
              'task send(input integer value);begin',
              f'{incoming["one"]}=value;#1000000;{incoming["req"]}=1;wait({incoming["ack"]});#1;{incoming["req"]}=0;wait(!{incoming["ack"]});#1;end endtask',
              'task receive;integer k;begin for(k=0;k<64;k++) begin',
              f'wait({outgoing["req"]});#(1+1000000*((k+{seed})%23));{outgoing["ack"]}=1;',
              f'wait(!{outgoing["req"]});#17000000;{outgoing["ack"]}=0;#1;end end endtask',
              'task stream;begin fork begin for(i=0;i<64;i++) begin send(words[i]);#1000000;end end receive();join #1000000000;end endtask',
              'initial begin']
    lines += [f"words[{i}]={word};" for i, word in enumerate(words)]
    lines += ['trace=$fopen("trace.txt","w");$fdisplay(trace,"QDI_TRACE|1");recover();stream();recover();',
              'fork : stalled begin for(i=0;i<16;i++) send(i%4);wait(1\'b0);end begin #100000000000;end join_any',
              f'if(stalled_accepts<1 || !{outgoing["req"]}) $fatal(1,"QDI_STALL_NOT_REACHED");',
              '$display("QDI_RESET:stalled_stream");reset_checks++;snapshot();reset=1;disable stalled;#1;clear_drivers();#10000000000;epoch++;reset=0;#10000000000;stream();',
              'if(total_deliveries!=128 || reset_checks!=1) $fatal(1,"QDI_ACTIVITY");',
              '$display("QDI_STALLED_ACCEPTS:%0d",stalled_accepts);snapshot();$fclose(trace);trace=0;$display("QDI_PASS");$finish;end',
              'initial begin #100000000000000;$fatal(1,"QDI_DEADLINE");end', "endmodule"]
    return "\n".join(lines) + "\n", catalog, overrides


def bench(fixture, manifest, ports, seed, root_only=False, stimulus=None):
    check_fixture_shape(fixture, manifest)
    if fixture == "qdi_fork": return fork_bench(manifest, ports, seed, root_only)
    if fixture == "qdi_composition": return mixed_bench(manifest, ports, seed, root_only)
    return strong_bench(fixture, manifest, ports, seed, root_only, stimulus)


class Ledger:
    """Input offers create obligations; local input acknowledgements may be late."""
    def __init__(self, fixture, channels):
        self.fixture, self.channels = fixture, channels
        self.monitors = {c["id"]: Protocol(c["protocol"], c["width"]) for c in channels}
        self.inputs = {c["id"]: c for c in channels if c["root"] and c["role"] == "input"}
        self.outputs = {c["id"]: c for c in channels if c["root"] and c["role"] == "output"}
        self.queues = {key: deque() for key in (self.inputs if fixture == "qdi_join" else self.outputs)}
        self.delivered, self.aborted, self.offered, self.completed = Counter(), Counter(), Counter(), Counter()
        self.counts, self.witnesses = Counter(), {}
        self.pending = {}
        self.obligations = Counter()
        self.resetting, self.epochs = True, set()

    def event(self, epoch, reset, name, req, ack, one, zero):
        if reset:
            if not self.resetting:
                for key, queue in self.queues.items(): self.aborted[key] += len(queue); queue.clear()
                self.pending.clear()
            self.resetting = True
            for monitor in self.monitors.values(): monitor.reset()
            self.check()
            return
        self.resetting = False
        self.epochs.add(epoch)
        for event, value in self.monitors[name].observe(req, ack, one, zero):
            if event == "complete": self.counts[(epoch, name)] += 1
            if name in self.inputs:
                if event == "offer":
                    self.offered[name] += 1
                    if self.fixture == "qdi_join": self.queues[name].append(value)
                    else:
                        for target, queue in self.queues.items():
                            if self.fixture != "qdi_demux" or self.outputs[target]["local_id"] == f"out{value>>2}":
                                queue.append(truth(self.fixture, value))
                                self.obligations[target] += 1
                if event == "complete": self.completed[name] += 1
            if name in self.outputs:
                if event == "offer":
                    require(name not in self.pending, "QDI_DUPLICATE_OFFER")
                    if self.fixture == "qdi_join":
                        operands = {c["local_id"]: key for key, c in self.inputs.items()}
                        left, right = (self.queues[operands[k]] for k in ("left_input", "right_input"))
                        require(left and right, "QDI_JOIN_EARLY")
                        expected = (left[0] << 2) | right[0]
                    else:
                        require(self.queues[name], "QDI_UNEXPECTED_OUTPUT")
                        expected = self.queues[name][0]
                    require(value == expected, "QDI_VALUE")
                    self.pending[name] = value
                if event == "complete":
                    require(name in self.pending, "QDI_UNEXPECTED_COMPLETION")
                    self.pending.pop(name)
                    if self.fixture == "qdi_join":
                        for queue in self.queues.values(): queue.popleft()
                    else: self.queues[name].popleft()
                    self.delivered[name] += 1
        self.check()

    def check(self):
        for name, queue in self.queues.items():
            if self.fixture == "qdi_join":
                require(self.offered[name] == sum(self.delivered.values()) + self.aborted[name] + len(queue), "QDI_CONSERVATION")
            else:
                require(self.obligations[name] == self.delivered[name] + self.aborted[name] + len(queue), "QDI_CONSERVATION")

    def finish(self):
        require(not self.resetting and all(m.idle() for m in self.monitors.values()), "QDI_NOT_IDLE")
        require(not self.pending and not any(self.queues.values()), "QDI_CONSERVATION")
        require(self.epochs == set(range(1, max(self.epochs)+1)), "QDI_EPOCH_INVENTORY")
        expected_epochs = 3 if self.fixture == "qdi_composition" else len(case_contract(self.fixture)["reset_scenarios"]) + 1
        require(len(self.epochs) == expected_epochs, "QDI_EPOCH_INVENTORY")
        expected = {(epoch, c["id"]): self.counts[(epoch, c["id"])] for epoch in self.epochs for c in self.channels}
        require(self.witnesses == expected, "QDI_COMPLETION_WITNESS")
        require(all(sum(v for (e, n), v in self.counts.items() if n == c["id"]) > 0 for c in self.channels), "QDI_BOUNDARY_ACTIVITY")
        require(sum(self.aborted.values()) > 0, "QDI_RESET_NOT_ACTIVATED")
        expected_deliveries = case_contract(self.fixture)["deliveries"]
        require(sum(self.delivered.values()) == expected_deliveries, "QDI_ACTIVITY")
        if self.fixture == "qdi_composition":
            for epoch in (1, 3):
                require(all(self.counts[(epoch, name)] == 64 for name in [*self.inputs, *self.outputs]), "QDI_MIXED_EPOCH_ACTIVITY")
                require(all(self.counts[(epoch, c["id"])] > 0 for c in self.channels), "QDI_MIXED_BOUNDARY_ACTIVITY")
        return dict(deliveries=dict(self.delivered), delivered=sum(self.delivered.values()), offered=dict(self.offered),
                    accepted=dict(self.completed), aborted=dict(self.aborted), epochs=sorted(self.epochs),
                    completions={f"{e}:{n}": count for (e, n), count in self.counts.items()})


def replay(fixture, channels, path, complete=True):
    ledger = Ledger(fixture, channels)
    rows = Path(path).read_text(encoding="utf-8").splitlines()
    require(rows and rows[0] == "QDI_TRACE|1", "QDI_TRACE_SCHEMA")
    previous = -1
    for line in rows[1:]:
        fields = line.split("|")
        if fields[0] == "C":
            _, epoch, name, count = fields
            key = (int(epoch), name)
            require(key not in ledger.witnesses and int(count) >= 0, "QDI_DUPLICATE_WITNESS")
            ledger.witnesses[key] = int(count)
            continue
        require(len(fields) == 9 and fields[0] == "E", "QDI_TRACE_SCHEMA")
        _, timestamp, epoch, reset, name, req, ack, one, zero = fields
        require(int(timestamp) >= previous, "QDI_TRACE_ORDER")
        previous = int(timestamp)
        if reset == "1": ledger.event(int(epoch), True, name, 0, 0, 0, 0)
        else:
            require(all(set(v.lower()) <= set("0123456789abcdef") for v in (req, ack, one, zero)), "QDI_UNKNOWN")
            try: ledger.event(int(epoch), False, name, int(req, 2), int(ack, 2), int(one, 16), int(zero, 16))
            except AssertionError as error:
                error.add_note(line)
                raise
    return ledger.finish() if complete else ledger


def output_wrapper(sources, manifest, ports, change):
    """Mutate the compiled RTL boundary, leaving bench/driver/oracle identical."""
    selected = dict(sources)
    top = manifest["top"]
    selected[top + ".sv"], count = re.subn(r"\bmodule\s+" + re.escape(top) + r"\b", "module Original_" + top, selected[top + ".sv"], count=1)
    require(count == 1, "QDI_MUTATION_TARGET")
    lines = ["module " + top + "(" + ",".join(flat(p["source"]) for p in ports) + ");"]
    for p in ports:
        name = flat(p["source"])
        lines.append(f'{p["direction"]} wire [{p["width"]-1}:0] {name};')
        if p["direction"] == "output": lines.append(f'wire [{p["width"]-1}:0] original_{name};')
    lines.append("Original_" + top + " original(" + ",".join("." + flat(p["source"]) + "(" +
                 ("original_" if p["direction"] == "output" else "") + flat(p["source"]) + ")" for p in ports) + ");")
    for p in ports:
        if p["direction"] != "output": continue
        name = flat(p["source"])
        value = "original_" + name
        if change == "early_fork_ack" and name == "in_ack": value = "out_0_ack"
        if change == "wrong_value" and name in ("out_one", "out_zero"):
            value = "original_" + ("out_zero" if name == "out_one" else "out_one")
        lines.append(f"assign {name}={value};")
    selected[top + ".sv"] += "\n" + "\n".join(lines + ["endmodule"]) + "\n"
    return selected


def mutate(name, manifest, ports, sources):
    if name in ("wrong_value", "early_fork_ack"):
        return output_wrapper(sources, manifest, ports, name)
    selected = dict(sources)
    node = next(n for n in nodes(manifest["design"]) if any(p["id"] == "minterm0" for p in n["primitives"]))
    primitive = next(p for p in node["primitives"] if p["id"] == "minterm0")
    instance = primitive["rtl_path"].split(".")[-1]
    path = node["module"] + ".sv"
    text = selected[path]
    if name == "dropped_dependency":
        pattern = "(" + re.escape(instance) + r"\s*\([\s\S]*?\.common\s*\()([^\n]+?)(\)\s*,)"
        text, count = re.subn(pattern, lambda m: m[1] + "(" + m[2] + " | 3'b100)" + m[3], text, count=1)
        require(count == 1, "QDI_MUTATION_TARGET")
    elif name == "stateless_return":
        pattern = "(" + re.escape(instance) + r"\s*\([\s\S]*?\.q\s*\()(\w+)(\))"
        match = re.search(pattern, text)
        require(match is not None, "QDI_MUTATION_TARGET")
        text = re.sub(pattern, lambda m: m[1] + "unused_qdi_fault" + m[3], text, count=1)
        text = text.replace(");", ");\nwire unused_qdi_fault;", 1)
        text = text.replace("endmodule", f"assign {match[2]} = !reset && (&in_zero);\nendmodule")
    else: raise AssertionError("QDI_UNKNOWN_MUTATION")
    selected[path] = text
    return selected


def execute(fixture, manifest, ports, sources, seed, directory, fault=None, mutant=False):
    directory.mkdir(parents=True, exist_ok=False)
    stimulus = fault if fault in ("invalid_rail", "merge_contention", "merge_return_contention") else None
    # Every paired control observes root ports so an RTL wrapper does not alter
    # the bench between baseline and mutant; integration cases observe all nodes.
    text, channels, overrides = bench(fixture, manifest, ports, seed, root_only=bool(fault), stimulus=stimulus)
    if stimulus and not mutant:
        # Keep the same timed prefix, but make the second rail/lane inactive.
        if stimulus == "invalid_rail":
            require(text.count("c0_zero=1; c0_one=1;") == 1, "QDI_STIMULUS_TARGET")
            text = text.replace("c0_zero=1; c0_one=1;", "c0_zero=1; c0_one=0;")
        elif stimulus == "merge_contention":
            input_names = ["c" + str(i) for i, c in enumerate(manifest["design"]["channels"]) if c["role"] == "input"]
            before = input_names[0] + "_one=1; " + input_names[1] + "_one=1;"
            require(text.count(before) == 1, "QDI_STIMULUS_TARGET")
            text = text.replace(before, input_names[0] + "_one=1; " + input_names[1] + "_one=0;")
        else:
            input_names = ["c" + str(i) for i, c in enumerate(manifest["design"]["channels"]) if c["role"] == "input"]
            before = input_names[1] + "_one=1;"
            require(text.count(before) == 1, "QDI_STIMULUS_TARGET")
            text = text.replace(before, input_names[1] + "_one=0;")
    selected = mutate(fault, manifest, ports, sources) if mutant and not stimulus else dict(sources)
    path = directory / "bench.sv"
    path.write_text(text, encoding="utf-8")
    compiled = []
    for name, body in selected.items():
        p = directory / name
        p.write_text(body, encoding="utf-8")
        compiled.append(p)
    command = ["iverilog", "-g2012", "-s", "QdiBench", "-o", str(directory / "sim.vvp"), str(path), *map(str, compiled)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    (directory / "compile.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    require(result.returncode == 0, "QDI_COMPILE: " + result.stderr)
    result = subprocess.run(["vvp", str(directory / "sim.vvp")], cwd=directory, capture_output=True, text=True, timeout=240)
    log = result.stdout + result.stderr
    (directory / "simulation.log").write_text(log, encoding="utf-8")
    fatals = re.findall(r"^FATAL: [^\n]*?: (\w+)", log, re.M)
    diagnostic = FAULTS[fault][1] if fault else None
    if mutant and fault != "invalid_rail":
        require(result.returncode == 1 and fatals == [diagnostic], "QDI_WRONG_REJECTION: " + log[-2000:])
        evidence = {"diagnostic": diagnostic}
    elif mutant:
        require(result.returncode == 0 and not fatals and log.splitlines().count("QDI_PREFIX_COMPLETE") == 1, "QDI_PREFIX_FAILURE")
        try: replay(fixture, channels, directory / "trace.txt", complete=False)
        except AssertionError as error: require(str(error) == diagnostic, "QDI_WRONG_REJECTION: " + str(error))
        else: raise AssertionError("QDI_CONTROL_ESCAPED")
        evidence = {"diagnostic": diagnostic}
    else:
        marker = "QDI_PREFIX_COMPLETE" if stimulus else "QDI_PASS"
        require(result.returncode == 0 and not fatals and log.splitlines().count(marker) == 1, "QDI_SIMULATION: " + log[-3000:])
        if stimulus:
            ledger = replay(fixture, channels, directory / "trace.txt", complete=False)
            require(sum(ledger.delivered.values()) > 0, "QDI_CONTROL_BASELINE_ACTIVITY")
            evidence = {"delivered": sum(ledger.delivered.values())}
        else:
            evidence = replay(fixture, channels, directory / "trace.txt")
            markers = re.findall(r"^QDI_RESET:(\w+)$", log, re.M)
            require(Counter(markers) == Counter(case_contract(fixture)["reset_scenarios"]), "QDI_RESET_INVENTORY")
    row = dict(fixture=fixture, seed=seed, fault=fault, mutant=mutant, status="EXPECTED_REJECTION" if mutant else "PASS",
               evidence=evidence, overrides=overrides, compile=command, exit_code=result.returncode,
               sources={p.name: sha(p) for p in compiled}, bench_sha256=sha(path), trace_sha256=sha(directory / "trace.txt"),
               log_sha256=sha(directory / "simulation.log"))
    write(directory / "case.json", row)
    return row


def audit_case(row, directory, manifest):
    require(read(directory / "case.json") == row, "QDI_CASE_SUMMARY")
    for name, expected in row["sources"].items(): require(sha(directory / name) == expected, "QDI_SOURCE_HASH")
    for name, field in (("bench.sv", "bench_sha256"), ("trace.txt", "trace_sha256"), ("simulation.log", "log_sha256")):
        require(sha(directory / name) == row[field], "QDI_ARTIFACT_HASH")
    channels = channel_catalog(manifest, root_only=bool(row["fault"]))
    log = (directory / "simulation.log").read_text(encoding="utf-8")
    if row["mutant"]:
        diagnostic = FAULTS[row["fault"]][1]
        require(row["status"] == "EXPECTED_REJECTION" and row["evidence"] == {"diagnostic": diagnostic}, "QDI_CONTROL_STATUS")
        if row["fault"] == "invalid_rail":
            try: replay(row["fixture"], channels, directory / "trace.txt", complete=False)
            except AssertionError as error: require(str(error) == diagnostic, "QDI_WRONG_REJECTION")
            else: raise AssertionError("QDI_CONTROL_ESCAPED")
        else:
            require(row["exit_code"] == 1 and re.findall(r"^FATAL: [^\n]*?: (\w+)", log, re.M) == [diagnostic], "QDI_WRONG_REJECTION")
    else:
        require(row["status"] == "PASS" and row["exit_code"] == 0 and "FATAL:" not in log, "QDI_CASE_STATUS")
        prefix = row["fault"] in ("invalid_rail", "merge_contention", "merge_return_contention")
        if prefix:
            ledger = replay(row["fixture"], channels, directory / "trace.txt", complete=False)
            require(sum(ledger.delivered.values()) == row["evidence"]["delivered"] > 0, "QDI_CONTROL_BASELINE_ACTIVITY")
        else:
            require(replay(row["fixture"], channels, directory / "trace.txt") == row["evidence"], "QDI_REPLAY_SUMMARY")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generated", type=Path, default=ROOT / "target/generated")
    parser.add_argument("--output", type=Path, default=ROOT / "target/verification/qdi")
    parser.add_argument("--seeds", type=int, nargs="+", default=list(range(15)))
    parser.add_argument("--fixtures", choices=FIXTURES, nargs="+", default=list(FIXTURES))
    args = parser.parse_args()
    require(not sys.flags.optimize and not os.environ.get("PYTHONOPTIMIZE"), "QDI_ASSERTIONS_DISABLED")
    require(args.seeds and len(set(args.seeds)) == len(args.seeds) and all(0 <= s < 2**32 for s in args.seeds), "QDI_SEED_SELECTION")
    require(args.fixtures and len(set(args.fixtures)) == len(args.fixtures), "QDI_FIXTURE_SELECTION")
    out = args.output.resolve()
    require(not out.exists(), "QDI_OUTPUT_EXISTS: use a fresh directory; failed attempts are retained")
    out.mkdir(parents=True)
    report = dict(status="RUNNING", selected=[f"{f}_{s}" for f in args.fixtures for s in args.seeds], cases=[], faults=[], exports={},
                  scope="finite digital development campaign; atomic cells and ideal forks; no physical QDI or reliability claim",
                  contracts={f: case_contract(f) for f in args.fixtures},
                  checker_sha256={p.name: sha(p) for p in (Path(__file__), ROOT / "verification/phase_reference.py",
                      ROOT / "verification/run_phase.py", ROOT / "verification/run.py", ROOT / "verification/compare_controllers.py", ROOT / "tools/check_export.py")})
    def save(): write(out / "report.json", report)
    save()
    try:
        report.update(identity())
        for fixture in args.fixtures:
            generated = out / "generated" / fixture
            shutil.copytree(args.generated.resolve() / fixture, generated)
            report["exports"][fixture] = validate_export(generated)
            manifest = read(generated / "contract.json")["manifest"]
            ports = read(generated / "ports.json")["nodes"][0]["ports"]
            sources = {p.name: p.read_text(encoding="utf-8") for p in read_sources(generated)}
            for seed in args.seeds:
                row = execute(fixture, manifest, ports, sources, seed, out / f"{fixture}_{seed}")
                audit_case(row, out / f"{fixture}_{seed}", manifest)
                report["cases"].append(row)
                save()
            for fault, (selected_fixture, _) in FAULTS.items():
                if fixture != selected_fixture: continue
                outcomes = [execute(fixture, manifest, ports, sources, 0, out / "faults" / fault / ("mutant" if m else "baseline"), fault, m)
                            for m in (False, True)]
                for row in outcomes:
                    audit_case(row, out / "faults" / fault / ("mutant" if row["mutant"] else "baseline"), manifest)
                report["faults"].append(dict(name=fault, diagnostic=FAULTS[fault][1], status="PASS", outcomes=outcomes))
                save()
            print(f"{fixture}: {len(args.seeds)} cases and exact controls PASS", flush=True)
        require([f'{r["fixture"]}_{r["seed"]}' for r in report["cases"]] == report["selected"] and report["cases"], "QDI_PARTIAL_CAMPAIGN")
        require([r["name"] for r in report["faults"]] == [n for f in args.fixtures for n, (owner, _) in FAULTS.items() if owner == f], "QDI_CONTROL_INVENTORY")
        report["status"] = "PASS"
    except BaseException as error:
        report.update(status="ERROR", error=str(error))
        save()
        raise
    save()


if __name__ == "__main__": main()
