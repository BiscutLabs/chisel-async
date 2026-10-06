# SPDX-License-Identifier: Apache-2.0
"""Independent event graph, primitive history and compiler-corruption controls."""
import json
from pathlib import Path
import re
import shutil

import pytest

from longhold_reference import INITIAL, LongHoldSTG, explore, verify_trace
from longhold_primitives import next_c
from longhold_topology import check_topology
from test_export import edit_manifest
from check_export import validate_export

ROOT = Path(__file__).resolve().parents[1]
CYCLE = "Rin+ A+ Lt+ Ain+ B+ Rin- Ain- Rout+ Aout+ A- Rout- Aout- Lt- B-".split()


def test_published_graph_exhausts_reachable_markings_without_deadlock():
    result = explore()
    assert result["markings"] > 14 and result["transitions"] > result["markings"]
    model = LongHoldSTG()
    for event in CYCLE * 2:
        model.fire(event)
    assert model.marking == INITIAL and not any(model.levels.values())


@pytest.mark.parametrize("prefix,illegal", [([], "A+"), (["Rin+", "A+"], "Ain+"),
    (CYCLE[:10], "Lt-"), (CYCLE[:12], "B-"), (CYCLE[:1], "Rin+")])
def test_graph_rejects_missing_causal_predecessor(prefix, illegal):
    model = LongHoldSTG()
    for event in prefix:
        model.fire(event)
    with pytest.raises(AssertionError, match="STG_ORDER"):
        model.fire(illegal)


def test_trace_must_have_activity_and_complete_final_cycle():
    cycle = "\n".join(f"STG stage=0 event={event}" for event in CYCLE) + "\n"
    assert verify_trace(cycle * 40, 1) == 560
    with pytest.raises(AssertionError, match="STG_MISSING_ACTIVITY"):
        verify_trace(cycle * 39, 1)
    with pytest.raises(AssertionError, match="STG_INCOMPLETE"):
        verify_trace(cycle * 40 + "STG stage=0 event=Rin+", 1)
    with pytest.raises(AssertionError, match="STG_ORDER"):
        verify_trace("STG stage=0 event=Rin+\nEVENT reset=1\nSTG stage=0 event=A+", 1)


def test_direct_three_input_c_keeps_history_that_binary_tree_loses():
    # 011 -> 110: no three-input unanimity, but C(C(a,b),c) spuriously rises.
    direct = inner = tree = 0
    for value in (3, 6):
        direct = next_c(direct, value, (3, 0, 0), (0, 0, 0))
        inner = next_c(inner, value & 3, (2, 0, 0), (0, 0, 0))
        tree = next_c(tree, inner | ((value >> 2) << 1), (2, 0, 0), (0, 0, 0))
    assert direct == 0 and tree == 1


@pytest.fixture
def longhold_export(tmp_path):
    source = ROOT / "target/generated/longhold_comparison"
    assert (source / "contract.json").is_file(), "EmitLongHold must run before these tests"
    target = tmp_path / "long hold export"
    shutil.copytree(source, target)
    return target


def test_emitted_topology_and_export_are_checked(longhold_export):
    assert validate_export(longhold_export)["status"] == "PASS"
    topology = check_topology((longhold_export / "LongHoldComparisonExample.sv").read_text())
    assert topology["cells"] == 8 and topology["state_cells"] == 3


@pytest.mark.parametrize("cell,port,new,diagnostic", [
    ("a", "falling", "in_req", "TOPOLOGY_CONNECTION:a"),
    ("long_hold", "b", "in_req", "TOPOLOGY_CONNECTION:long_hold"),
    ("payload", "closed", "in_req", "TOPOLOGY_CONNECTION:payload"),
    ("b", "reset", "in_req", "TOPOLOGY_RESET"),
])
def test_topology_rejects_rewired_cells(longhold_export, cell, port, new, diagnostic):
    source = (longhold_export / "LongHoldComparisonExample.sv").read_text()
    changed, count = re.subn(rf"(ca_primitive_{cell}\s*\(.*?\.{port}\s*\()[^()]+(\))",
                            rf"\g<1>{new}\2", source, flags=re.S)
    assert count == 1
    with pytest.raises(AssertionError, match=diagnostic):
        check_topology(changed)


def test_topology_rejects_changed_input_polarity(longhold_export):
    source = (longhold_export / "LongHoldComparisonExample.sv").read_text()
    assert source.count(".FALLING_INVERT(1)") == 1
    with pytest.raises(AssertionError, match="TOPOLOGY_CELL_PARAMETERS"):
        check_topology(source.replace(".FALLING_INVERT(1)", ".FALLING_INVERT(0)"))


@pytest.mark.parametrize("key,value,diagnostic", [
    ("matched_delay_fs", "10000000", "INVALID_BUNDLING_POLICY"),
    ("output_delay_fs", "30000000", "INVALID_BUNDLING_POLICY"),
    ("mode", "functional-only", "INVALID_BUNDLING_POLICY"),
    ("latch_closed", "absent", "MISSING_TIMING_ENDPOINT"),
    ("data_delay", {"min_fs":"1000000", "max_fs":"10000000", "model_fs":"9000000"}, "BUNDLING_PARAMETER_MISMATCH"),
    ("latch_delay", {"min_fs":"2000000", "max_fs":"10000000", "model_fs":"1000000"}, "INVALID_DELAY_BOUNDS"),
    ("output_delay_fs", str(2**63), "INVALID_MODEL_TIME"),
])
def test_timing_contract_cannot_drift_from_rtl(longhold_export, key, value, diagnostic):
    edit_manifest(longhold_export, lambda m: m["design"]["timing"][0].update({key: value}))
    with pytest.raises(ValueError, match=f"^{diagnostic}$"):
        validate_export(longhold_export)
    assert json.loads((longhold_export / "resolved.json").read_text())["status"] != "PASS"


def test_sweep_cannot_escape_declared_cell_envelope(longhold_export):
    from run_longhold import check_case_bounds, case_configuration
    policy = json.loads((longhold_export / "contract.json").read_text())["manifest"]["design"]["timing"][0]
    for delay in (1, 10):
        values, _ = case_configuration(0, 3, delay)
        check_case_bounds(policy, values)
    values[1]["b"] = 11
    with pytest.raises(ValueError, match="DELAY_OUTSIDE_DECLARED_BOUNDS"):
        check_case_bounds(policy, values)


@pytest.mark.parametrize('skew_fs,expected', [(0,'PASS'),(20000000,'DATA_HOLD')])
def test_long_hold_or_fork_arrival_constraint_on_actual_rtl(tmp_path,skew_fs,expected):
    import subprocess
    import hashlib
    from run import read_sources
    tmp_path=ROOT/'target/verification/fork-arrival'/f'{skew_fs}fs'
    tmp_path.mkdir(parents=True,exist_ok=True)
    report=tmp_path/'report.json'; report.write_text('{"status":"RUNNING"}',encoding='utf-8')
    sources=read_sources(ROOT/'target/generated/longhold_comparison')
    original=next(p for p in sources if p.name=='LongHoldComparisonExample.sv')
    text,count=re.subn(r'(ca_primitive_long_hold\s*\(.*?\.b\s*\()out_ack(?:_0)?(\))',
                       r'\g<1>late_hold_ack\2',original.read_text(encoding='utf-8'),flags=re.S)
    assert count==1, 'FORK_SKEW_MUTATION_TARGET'
    text=text.replace('  wire',f'  wire late_hold_ack;\n  assign #{skew_fs}fs late_hold_ack = out_ack;\n  wire',1)
    mutant=tmp_path/'fork_skew.sv'; mutant.write_text('`timescale 1fs/1fs\n'+text,encoding='utf-8')
    snapshots=[]
    for source in sources:
        if source==original: snapshots.append(mutant)
        else:
            snapshot=tmp_path/source.name; snapshot.write_bytes(source.read_bytes()); snapshots.append(snapshot)
    bench=tmp_path/'bench.sv'
    bench.write_text('''module ForkBench;
      timeunit 1ns; timeprecision 1fs;
      reg reset=1, in_req=0, out_ack=0; reg [39:0] in_bits=0;
      wire in_ack,out_req; wire [39:0] out_bits;
      LongHoldComparisonExample dut(.*);
      initial begin
        #1000; reset=0; #100; in_bits=17; #10; in_req=1;
        wait(in_ack); #1; in_req=0; wait(!in_ack); wait(out_req);
        // The input handshake is complete; another unaccepted value is legal.
        in_bits=34; #100; out_ack=1;
        #10; if(out_bits!==40'd17) $fatal(1,"DATA_HOLD");
        #100; out_ack=0; #100; $display("FORK_BASELINE_PASS"); $finish;
      end
      initial begin #10000; $fatal(1,"FORK_TIMEOUT"); end
    endmodule''',encoding='utf-8')
    image=tmp_path/'fork.vvp'
    command=['iverilog','-g2012','-s','ForkBench','-o',str(image),
             *map(str,snapshots),str(bench)]
    compiled=subprocess.run(command,capture_output=True,text=True,timeout=30)
    (tmp_path/'compile.log').write_text(compiled.stdout+compiled.stderr,encoding='utf-8')
    assert compiled.returncode==0,compiled.stderr
    result=subprocess.run(['vvp',str(image)],capture_output=True,text=True,timeout=30)
    (tmp_path/'simulation.log').write_text(result.stdout+result.stderr,encoding='utf-8')
    if expected=='PASS': assert result.returncode==0 and 'FORK_BASELINE_PASS' in result.stdout,result.stdout
    else: assert result.returncode!=0 and re.findall(r'^FATAL: [^\n]*?: (\w+)',result.stdout,re.M)==[expected],result.stdout
    report.write_text(json.dumps(dict(status='PASS',expected=expected,skew_fs=skew_fs,command=command,
        simulation_exit=result.returncode,source_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                                                       for p in [*snapshots,bench]},
        log_sha256=hashlib.sha256((tmp_path/'simulation.log').read_bytes()).hexdigest()),indent=2)+'\n',encoding='utf-8')
