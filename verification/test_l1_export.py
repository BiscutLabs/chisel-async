# SPDX-License-Identifier: Apache-2.0
"""L1 controls for timing obligations remaining attached to actual cell roles."""
import json
import re
import shutil
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from check_export import nodes, validate_export
from test_export import edit_manifest


def copied(tmp_path, fixture):
    directory = tmp_path / fixture
    shutil.copytree(ROOT / "target/generated" / fixture, directory)
    return directory


def change_instance(directory, node, primitive, old, new):
    """Change one preserved instance; never silently target a sibling cell."""
    source = directory / (node["module"] + ".sv")
    text = source.read_text(encoding="utf-8")
    name = primitive["rtl_path"].rsplit(".", 1)[-1]
    pattern = re.compile(r"  " + re.escape(primitive["model"]) +
                         r" #\(\n(?:(?!\n  \)).)*\n  \) " + re.escape(name) + r" \(.*?\n  \);", re.S)
    matches = list(pattern.finditer(text))
    assert len(matches) == 1, "L1_MUTATION_INSTANCE"
    match = matches[0]
    original = match.group()
    assert original.count(old) == 1, "L1_MUTATION_PIN_OR_PARAMETER"
    source.write_text(text[:match.start()] + original.replace(old, new) + text[match.end():], encoding="utf-8")


@pytest.mark.parametrize("fixture", ["select", "merge", "initial_tokens", "phase_to_four", "phase_to_two",
                                     "replicated", "replicated_debug"])
def test_timing_pin_checks_accept_emitted_baselines(tmp_path, fixture):
    result = validate_export(copied(tmp_path, fixture))
    assert result["status"] == "PASS" and result["mapping_checks"] > 0


@pytest.mark.parametrize("fault,fixture,identity,old,new,parameter,diagnostic", [
    ("or_is_buffer", "select", "long_hold", ".OP(2)", ".OP(0)", ("OP", "0"), "HOLD_FORK_CELL_MISMATCH"),
    ("or_wrong_pin", "select", "long_hold", ".b     (out_ack)", ".b     (in_req)", None, "HOLD_FORK_BINDING_MISMATCH"),
    ("a_wrong_falling_pin", "select", "a", ".falling (out_ack)", ".falling (in_req)", None, "HOLD_FORK_BINDING_MISMATCH"),
    ("a_wrong_falling_polarity", "select", "a", ".FALLING_INVERT(1)", ".FALLING_INVERT(0)",
     ("FALLING_INVERT", "0"), "HOLD_FORK_CELL_MISMATCH"),
    ("capture_bypasses_budget", "select", "payload", ".d      (ca_primitive_data_delay_q_probe)",
     ".d      ({in_bits_index == 2'h2, in_bits_index == 2'h1, in_bits_index == 2'h0, in_bits_data})",
     None, "DATA_PATH_BINDING_MISMATCH"),
    ("capture_ignores_hold", "select", "payload", ".closed (ca_primitive_long_hold_q_probe)",
     ".closed (in_req)", None, "DATA_PATH_BINDING_MISMATCH"),
    ("delay_is_inverter", "select", "data_delay", ".OP(0)", ".OP(1)", ("OP", "1"), "DATA_PATH_CELL_MISMATCH"),
    ("guard_bypasses_return", "phase_to_four", "return_guard", ".a     (_returned_ca_primitive_returned_q)",
     ".a     (in_req)", None, "PHASE_RETURN_BINDING_MISMATCH"),
    ("guard_is_inverter", "phase_to_four", "return_guard", ".OP(0)", ".OP(1)", ("OP", "1"), "PHASE_GUARD_CELL_MISMATCH"),
    ("master_is_buffer", "phase_to_four", "master_close", ".OP(1)", ".OP(0)", ("OP", "0"), "PHASE_GUARD_CELL_MISMATCH"),
    ("returned_uses_request", "phase_to_four", "returned", ".closed (out_ack)", ".closed (in_req)",
     None, "PHASE_RETURN_BINDING_MISMATCH"),
])
def test_rehashed_cells_cannot_detach_timing_obligations(tmp_path, fault, fixture, identity, old, new, parameter, diagnostic):
    directory = copied(tmp_path, fixture)

    def corrupt(manifest):
        node = next(n for n in nodes(manifest["design"]) if any(p["id"] == identity for p in n["primitives"]))
        primitive = next(p for p in node["primitives"] if p["id"] == identity)
        change_instance(directory, node, primitive, old, new)
        if parameter:
            # Coherent RTL/descriptor corruption must reach the semantic role check.
            primitive["parameters"][parameter[0]] = parameter[1]

    edit_manifest(directory, corrupt, refresh_rtl=True)
    with pytest.raises(ValueError, match="^" + diagnostic + "$"):
        validate_export(directory)
    assert json.loads((directory / "resolved.json").read_text())["status"] != "PASS"
