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
    ("matched_delay_fs", "8000000", "INVALID_BUNDLING_POLICY"),
    ("output_delay_fs", "3000000", "INVALID_BUNDLING_POLICY"),
    ("mode", "functional-only", "INVALID_BUNDLING_POLICY"),
    ("latch_closed", "absent", "MISSING_TIMING_ENDPOINT"),
    ("data_delay_fs", "9000000", "BUNDLING_PARAMETER_MISMATCH"),
    ("output_delay_fs", str(2**63), "INVALID_MODEL_TIME"),
])
def test_timing_contract_cannot_drift_from_rtl(longhold_export, key, value, diagnostic):
    edit_manifest(longhold_export, lambda m: m["design"]["timing"][0].update({key: value}))
    with pytest.raises(ValueError, match=f"^{diagnostic}$"):
        validate_export(longhold_export)
    assert json.loads((longhold_export / "resolved.json").read_text())["status"] != "PASS"
