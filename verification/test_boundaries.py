# SPDX-License-Identifier: Apache-2.0
"""Adversarial CA-09 export and oracle checks; generated RTL is required."""
import copy
import json
from pathlib import Path
import shutil

import pytest
from run_boundaries import ROOT, FIXTURES, audit_memory, audit_events
from check_export import validate_export
from test_export import edit_manifest


def copied(tmp_path, fixture="memory_ram"):
    original = ROOT / "target/generated" / fixture
    assert (original / "contract.json").is_file(), "Required boundary export missing; run EmitBoundaries"
    target = tmp_path / (fixture + " with spaces")
    shutil.copytree(original, target)
    return target


@pytest.mark.parametrize("fixture", FIXTURES)
def test_application_boundaries_resolve_optimized_exports(tmp_path, fixture):
    result = validate_export(copied(tmp_path, fixture))
    assert result["status"] == "PASS" and result["mapping_checks"] > 0


@pytest.mark.parametrize("fault,diagnostic", [
    ("missing", "UNREGISTERED_MODULE_OR_PRIMITIVE"), ("duplicate", "MEMORY_HW_INVENTORY"),
    ("depth", "MEMORY_HW_SHAPE"), ("width", "MEMORY_HW_SHAPE"), ("mask", "MEMORY_HW_SHAPE"),
    ("reset", "UNSUPPORTED_MEMORY_POLICY"), ("collision", "UNSUPPORTED_MEMORY_POLICY"),
    ("latency", "UNSUPPORTED_MEMORY_POLICY"), ("source", "MEMORY_HW_SHAPE"),
])
def test_declared_memory_must_match_actual_chisel_lowering(tmp_path, fault, diagnostic):
    directory = copied(tmp_path)
    def change(manifest):
        node = manifest["design"]
        memory = node["memories"][0]
        if fault == "missing": del node["memories"]
        elif fault == "duplicate":
            other = copy.deepcopy(memory); other["id"] = "extra"; node["memories"].append(other)
        elif fault in ("depth", "width", "mask"):
            memory[{"depth":"depth", "width":"word_bits", "mask":"mask_bits"}[fault]] *= 2
        elif fault == "reset": memory["reset_contents"] = "cleared"
        elif fault == "collision": memory["read_under_write"] = "new"
        elif fault == "latency": memory["read_latency"] = 0
        elif fault == "source": memory["source"] += "wrong"
    edit_manifest(directory, change)
    with pytest.raises(ValueError, match="^" + diagnostic + "$"):
        validate_export(directory)


@pytest.mark.parametrize("fault,diagnostic", [("array", "MEMORY_RTL_SHAPE"), ("mask", "MEMORY_RTL_PORTS"),
                                               ("ir", "MEMORY_HW_SHAPE")])
def test_memory_evidence_is_checked_independently_of_updated_hashes(tmp_path, fault, diagnostic):
    directory = copied(tmp_path)
    path = directory / ("design.hw.mlir" if fault == "ir" else "memory_16x16.sv")
    old, new = {"array": ("Memory[0:15]", "Memory[0:7]"),
                "mask": ("[1:0]  RW0_wmask", "[0:0]  RW0_wmask"),
                "ir": ("<16 x 16, mask 2>", "<32 x 16, mask 2>")}[fault]
    text = path.read_text(); assert old in text
    path.write_text(text.replace(old, new))
    edit_manifest(directory, lambda _: None, refresh_rtl=True)
    with pytest.raises(ValueError, match="^" + diagnostic + "$"):
        validate_export(directory)


@pytest.mark.parametrize("trace,rom,diagnostic", [
    ("", False, "MEMORY_ACTIVITY"),
    ("BND A 1 0 4660 3\nBND D 0 0", False, "MEMORY_MISSING_EFFECT"),
    ("BND A 1 0 4660 3\nBND W\nBND W", False, "MEMORY_EXTRA_EFFECT"),
    ("BND A 1 0 4660 3\nBND W\nBND R 1\nBND A 0 0 0 0\nBND D 0 0", False, "MEMORY_PAYLOAD"),
    ("BND A 1 0 4660 3\nBND W", True, "MEMORY_EXTRA_EFFECT"),
    ("BND A 1 1 4660 3\nBND W", False, "MEMORY_EXTRA_EFFECT"),
    ("BND A 0 0 0 0", False, "MEMORY_UNINITIALIZED_READ"),
    ("BND D 0 0", False, "MEMORY_UNSOLICITED"),
    ("BND A 1 0 4660 3\nBND W\nBND R 0", False, "MEMORY_RESET_ACCOUNTING"),
    ("BND A 2 0 0 0", False, "MEMORY_TRACE"),
])
def test_byte_oracle_detects_effects_errors_and_reset_rollback(trace, rom, diagnostic):
    with pytest.raises(ValueError, match="^" + diagnostic + "$"):
        audit_memory(trace, rom)


def test_event_oracle_rejects_missing_and_coalesced_away_deliveries():
    for trace in ("", "BND D 1\n", "\n".join(f"BND D {i}" for i in range(1, 16))):
        with pytest.raises(ValueError, match="^EVENT_PAYLOAD$"):
            audit_events(trace)


@pytest.mark.parametrize("fault,diagnostic", [("empty_list", "MEMORY_INVENTORY"), ("empty_object", "MEMORY_INVENTORY"),
    ("bool_read", "UNSUPPORTED_MEMORY_POLICY"), ("bool_write", "UNSUPPORTED_MEMORY_POLICY")])
def test_memory_inventory_rejects_schema_invalid_python_values(tmp_path, fault, diagnostic):
    directory = copied(tmp_path)
    def change(manifest):
        node = manifest["design"]
        if fault.startswith("empty"):
            node["memories"] = [] if fault == "empty_list" else {}
        else:
            node["memories"][0]["read_latency" if fault == "bool_read" else "write_latency"] = True
    edit_manifest(directory, change)
    with pytest.raises(ValueError, match="^" + diagnostic + "$"):
        validate_export(directory)
