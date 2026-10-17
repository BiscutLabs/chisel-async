# SPDX-License-Identifier: Apache-2.0
"""Negative controls for the exact reset-free payload contract and event oracle."""
import json
from pathlib import Path
import sys
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT / "tools"))
from check_export import semantic_hash, validate_manifest
from run_passive_allowance import execute, primitive_bench


@pytest.mark.parametrize("fault,diagnostic", [
    ("reset-port","PASSIVE_ALLOWANCE_PORTS"),
    ("extra-parameter","PASSIVE_ALLOWANCE_PARAMETERS"),
    ("zero-width","PASSIVE_ALLOWANCE_PARAMETERS"),
    ("negative-delay","PASSIVE_ALLOWANCE_PARAMETERS"),
    ("delay-overflow","PASSIVE_ALLOWANCE_PARAMETERS"),
    ("wrong-pin-width","PASSIVE_ALLOWANCE_PORTS"),
    ("wrong-pin-direction","PASSIVE_ALLOWANCE_PORTS"),
])
def test_passive_descriptor_rejects_shape_drift(fault,diagnostic):
    document=json.loads((ROOT/"build/passive-allowance-exports/bd-passive/contract.json").read_text())
    cell=next(p for p in document["manifest"]["design"]["primitives"] if p["id"]=="data_delay")
    if fault=="reset-port": cell["ports"].append(dict(name="reset",width=1,direction="input"))
    elif fault=="extra-parameter": cell["parameters"]["RESET_VALUE"]="0"
    elif fault=="zero-width": cell["parameters"]["WIDTH"]="0"
    elif fault=="negative-delay": cell["parameters"]["DELAY_FS"]="-1"
    elif fault=="delay-overflow": cell["parameters"]["DELAY_FS"]=str(2**63)
    elif fault=="wrong-pin-width": cell["ports"][0]["width"]=7
    else: cell["ports"][0]["direction"]="output"
    document["semantic_sha256"]=semantic_hash(document["manifest"])
    with pytest.raises(ValueError,match="^"+diagnostic+"$"):
        validate_manifest(document)


@pytest.mark.parametrize("fault,diagnostic", [
    ("x-mask","PASSIVE_X_MASKED"),
    ("z-mask","PASSIVE_Z_MASKED"),
    ("transport","PASSIVE_NOT_INERTIAL"),
])
def test_actual_primitive_mutants_hit_exact_assertion(tmp_path,fault,diagnostic):
    model=ROOT/"src/main/resources/chiselasync/sv/ChiselAsyncPassiveDataAllowance_v1.sv"
    text=model.read_text()
    if fault=="x-mask": new="assign #DELAY_FS q = (a === 8'hxx) ? 8'h00 : a;"
    elif fault=="z-mask": new="assign #DELAY_FS q = (a === 8'hzz) ? 8'h00 : a;"
    else:
        text=text.replace("output wire [WIDTH-1:0] q", "output reg [WIDTH-1:0] q")
        new="always @(a) q <= #DELAY_FS a;"
    assert text.count("assign #DELAY_FS q = a;")==1
    mutant=tmp_path/"mutant.sv"
    mutant.write_text(text.replace("assign #DELAY_FS q = a;",new))
    execute(tmp_path/"run",[mutant,model.with_name("ChiselAsyncControlGate_v1.sv")],primitive_bench(),diagnostic)
