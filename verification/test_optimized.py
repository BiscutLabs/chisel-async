# SPDX-License-Identifier: Apache-2.0
import json
from pathlib import Path
import re
import shutil

import pytest
from test_export import edit_manifest
from check_export import read_probe_abi, validate_export

ROOT = Path(__file__).resolve().parents[1]


def test_identical_instances_share_definitions_but_different_transforms_do_not():
    results = [validate_export(ROOT / "target/generated" / name) for name in ("replicated", "replicated_debug")]
    optimized, debug = (r["instances"] for r in results)
    root = "ReplicatedExample"
    assert len(set(optimized[f"{root}.ca_child_lane{i}" ] for i in range(8))) == 2
    assert len(set(debug[f"{root}.ca_child_lane{i}"] for i in range(8))) == 8
    assert optimized[f"{root}.ca_child_lane0"] == optimized[f"{root}.ca_child_lane2"]
    assert optimized[f"{root}.ca_child_lane0"] != optimized[f"{root}.ca_child_lane1"]
    assert all(len(r["endpoints"]) == 240 and r["mapping_checks"] == 415680 for r in results)


def test_cross_instance_probe_alias_is_detected_after_rehash(tmp_path):
    directory = tmp_path / "replicated"
    shutil.copytree(ROOT / "target/generated/replicated", directory)
    path = directory / "ref_ReplicatedExample.sv"
    text = path.read_text()
    old = "ca_p_5_lane0_5_first_7_in_data ca_child_lane0.ca_child_first.in_bits"
    assert text.count(old) == 1
    path.write_text(text.replace(old, old.replace(" ca_child_lane0.", " ca_child_lane2.")))
    edit_manifest(directory, lambda _: None, refresh_rtl=True)
    with pytest.raises(ValueError, match="^ENDPOINT_MAPPING_MISMATCH$"):
        validate_export(directory)


@pytest.mark.parametrize("fault,diagnostic", [("parameter", "PRIMITIVE_PARAMETER_MISMATCH"),
    ("bounds", "TIMING_MARKER_PARAMETER_MISMATCH"), ("binding", "TIMING_MARKER_BINDING_MISMATCH")])
def test_timing_intent_remains_bound_to_actual_netlist(tmp_path, fault, diagnostic):
    directory = tmp_path / "timing"
    shutil.copytree(ROOT / "target/generated/timed_equal", directory)
    # Derive the top filename from the manifest; the contract still supplies no RTL connectivity oracle.
    document = json.loads((directory / "contract.json").read_text())
    path = directory / (document["manifest"]["top"] + ".sv")
    if fault == "bounds":
        edit_manifest(directory, lambda m: m["design"]["timing"][0].update(setup_fs="1999"))
    else:
        text = path.read_text()
        if fault == "parameter":
            assert text.count(".SETUP_FS(2000)") == 1
            text = text.replace(".SETUP_FS(2000)", ".SETUP_FS(1999)")
        else:
            text, count = re.subn(r"(ca_primitive_capture_window_marker\s*\(.*?\.values\s*\()[^\n)]+(\))",
                                  r"\g<1>'0\2", text, flags=re.S)
            assert count == 1
        path.write_text(text)
        edit_manifest(directory, lambda _: None, refresh_rtl=True)
    with pytest.raises(ValueError, match=f"^{diagnostic}$"):
        validate_export(directory)


@pytest.mark.parametrize("text,diagnostic", [("", "EMPTY_PROBE_ABI"),
    ("`define ref_T_a x\n`define ref_T_a y", "AMBIGUOUS_PROBE_ABI"),
    ("`define ref_T_a $random", "UNSUPPORTED_PROBE_ABI")])
def test_unsupported_probe_abi_fails_closed(text, diagnostic):
    with pytest.raises(ValueError, match=f"^{diagnostic}$"):
        read_probe_abi(text, "T")
