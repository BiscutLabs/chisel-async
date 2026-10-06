# SPDX-License-Identifier: Apache-2.0
"""QDI-family assumptions survive export as typed, bound passive markers.

These controls establish metadata/inventory/pin checks, not circuit indication.
Behavioral indication requires the separately driven rail-order campaign.
"""
import copy
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from check_export import marker_parameters, nodes, source_path, timing_refs, validate_export
from test_export import edit_manifest
from test_model_import import importer

FIXTURES = ("qdi_buffer", "qdi_packet", "qdi_not", "qdi_and", "qdi_or", "qdi_xor", "qdi_select",
            "qdi_adder", "qdi_constant", "qdi_fork", "qdi_join", "qdi_demux", "qdi_merge", "qdi_composition")


def copied(tmp_path, fixture):
    source = ROOT / "target/generated" / fixture
    assert (source / "contract.json").is_file(), "Required QDI export missing; run EmitQdi"
    directory = tmp_path / fixture
    shutil.copytree(source, directory)
    return directory


def qdi(node):
    return next(t for t in node["timing"] if t["kind"] == "qdi-digital-v1")


def marker(node):
    return next(p for p in node["primitives"] if p["id"] == qdi(node)["marker"])


def change_instance(directory, node, primitive, mutate):
    """Only mutate the requested instance, never a same-model sibling."""
    path = directory / (node["module"] + ".sv")
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(r"  " + re.escape(primitive["model"]) + r" #\(\n(?:(?!\n  \)).)*\n  \) " +
                         re.escape(primitive["rtl_path"].rsplit(".", 1)[-1]) + r" \(.*?\n  \);", re.S)
    matches = list(pattern.finditer(text))
    assert len(matches) == 1, "QDI_MUTATION_INSTANCE"
    found = matches[0]
    changed = mutate(found.group())
    assert changed != found.group(), "QDI_MUTATION_NO_CHANGE"
    path.write_text(text[:found.start()] + changed + text[found.end():], encoding="utf-8")


def once(text, old, new):
    assert text.count(old) == 1, "QDI_MUTATION_TARGET"
    return text.replace(old, new)


@pytest.mark.parametrize("fixture", FIXTURES)
def test_qdi_markers_cover_every_local_channel_and_resolve(tmp_path, fixture):
    directory = copied(tmp_path, fixture)
    result = validate_export(directory)
    assert result["status"] == "PASS" and result["mapping_checks"] > 0
    manifest = json.loads((directory / "contract.json").read_text())["manifest"]
    policies = [(n, t) for n in nodes(manifest["design"]) for t in n["timing"] if t["kind"] == "qdi-digital-v1"]
    assert policies, "EMPTY_QDI_POLICY_INVENTORY"
    for node, policy in policies:
        assert {c["channel"] for c in policy["input_channels"] + policy["output_channels"]} == {c["id"] for c in node["channels"]}
        assert len(timing_refs(policy)) == 3 * len(node["channels"])
        assert marker(node)["parameters"] == marker_parameters(policy, {e["id"]: e for e in node["endpoints"]})


@pytest.mark.parametrize("fault,fixture,diagnostic", [
    ("missing_output", "qdi_fork", "QDI_CHANNEL_INVENTORY"),
    ("duplicate_channel", "qdi_fork", "QDI_CHANNEL_INVENTORY"),
    ("swapped_rails", "qdi_buffer", "QDI_CHANNEL_BINDING"),
    ("wrong_ack", "qdi_buffer", "QDI_CHANNEL_BINDING"),
    ("wrong_role", "qdi_buffer", "QDI_CHANNEL_BINDING"),
    ("wrong_indication", "qdi_fork", "INVALID_QDI_INDICATION"),
    ("wrong_component_arity", "qdi_join", "QDI_COMPONENT_CHANNELS"),
    ("no_fork_assumption", "qdi_buffer", "INVALID_QDI_ASSUMPTIONS"),
    ("no_exclusion", "qdi_merge", "INVALID_QDI_ASSUMPTIONS"),
    ("zero_bound", "qdi_buffer", "INVALID_MODEL_TIME"),
    ("overflow_bound", "qdi_buffer", "INVALID_MODEL_TIME"),
    ("cell_outside_bound", "qdi_buffer", "QDI_CELL_OUTSIDE_BOUNDS"),
    ("marker_bound", "qdi_buffer", "QDI_MARKER_PARAMETER_MISMATCH"),
    ("marker_wrong_model", "qdi_buffer", "TIMING_MARKER_MODEL_MISMATCH"),
    ("missing_policy", "qdi_buffer", "QDI_CONSTRAINT_INVENTORY"),
    ("duplicate_policy", "qdi_buffer", "QDI_CONSTRAINT_INVENTORY"),
    ("hidden_actual_marker", "qdi_buffer", "UNREGISTERED_MODULE_OR_PRIMITIVE"),
])
def test_rehashed_qdi_metadata_corruption_has_specific_rejection(tmp_path, fault, fixture, diagnostic):
    directory = copied(tmp_path, fixture)

    def corrupt(manifest):
        node = manifest["design"]
        policy, carrier = qdi(node), marker(node)
        if fault == "missing_output": policy["output_channels"].pop()
        elif fault == "duplicate_channel": policy["output_channels"].append(copy.deepcopy(policy["output_channels"][0]))
        elif fault == "swapped_rails":
            c = policy["input_channels"][0]
            c["zero"], c["one"] = c["one"], c["zero"]
        elif fault == "wrong_ack": policy["input_channels"][0]["acknowledge"] = policy["output_channels"][0]["acknowledge"]
        elif fault == "wrong_role": policy["input_channels"], policy["output_channels"] = policy["output_channels"], policy["input_channels"]
        elif fault == "wrong_indication": policy["indication"] = "strong"
        elif fault == "wrong_component_arity": policy["component"] = "storage"
        elif fault == "no_fork_assumption": policy["assumptions"]["forks"] = "unconstrained"
        elif fault == "no_exclusion": policy["assumptions"]["exclusive_inputs"] = "not-applicable"
        elif fault == "zero_bound": policy["cells"]["min_fs"] = "0"
        elif fault == "overflow_bound": policy["cells"]["max_fs"] = str(2**63)
        elif fault == "cell_outside_bound":
            cell = next(p for p in node["primitives"] if "DELAY_FS" in p["parameters"])
            cell["parameters"]["DELAY_FS"] = str(int(policy["cells"]["max_fs"]) + 1)
        elif fault == "marker_bound": carrier["parameters"]["CELL_MAX_FS"] = str(int(policy["cells"]["max_fs"]) + 1)
        elif fault == "marker_wrong_model":
            old = carrier["resource"]
            carrier["model"] = "ChiselAsyncTimingMarker_v1"
            carrier["resource"] = "chiselasync/sv/ChiselAsyncTimingMarker_v1.sv"
            manifest["resources"][carrier["resource"]] = manifest["resources"].pop(old)
        elif fault == "duplicate_policy":
            other = copy.deepcopy(policy)
            other["id"] = "another_qdi"
            node["timing"].append(other)
        else:
            node["timing"].remove(policy)
            # Semantic name changes cannot conceal the independently inventoried marker.
            for p in node["primitives"]: p["id"] = "renamed_" + p["id"]
            if fault == "hidden_actual_marker":
                node["primitives"].remove(carrier)
                manifest["resources"].pop(carrier["resource"])

    edit_manifest(directory, corrupt)
    with pytest.raises(ValueError, match="^" + diagnostic + "$"):
        validate_export(directory)
    assert json.loads((directory / "resolved.json").read_text())["status"] != "PASS"


@pytest.mark.parametrize("fault,diagnostic", [("marker_values", "QDI_MARKER_BINDING_MISMATCH"),
                                              ("marker_parameter", "PRIMITIVE_PARAMETER_MISMATCH"),
                                              ("cell_parameter", "PRIMITIVE_PARAMETER_MISMATCH"),
                                              ("coherent_cell_outside", "QDI_CELL_OUTSIDE_BOUNDS")])
def test_rehashed_qdi_rtl_corruption_is_checked_against_actual_cells(tmp_path, fault, diagnostic):
    directory = copied(tmp_path, "qdi_buffer")

    def corrupt(manifest):
        node = manifest["design"]
        if fault == "marker_values":
            def invert_values(text):
                text, count = re.subn(r"(\.values\s*\()([^)]*)(\))", r"\1~(\2)\3", text)
                assert count == 1, "QDI_MUTATION_MARKER_VALUES"
                return text
            change_instance(directory, node, marker(node), invert_values)
        elif fault == "marker_parameter":
            change_instance(directory, node, marker(node), lambda s: once(s, ".CELL_MODEL_FS(1000000)", ".CELL_MODEL_FS(2000000)"))
        else:
            cell = next(p for p in node["primitives"] if "DELAY_FS" in p["parameters"])
            old = cell["parameters"]["DELAY_FS"]
            new = str(int(qdi(node)["cells"]["max_fs"]) + 1) if fault == "coherent_cell_outside" else str(int(old) + 1)
            change_instance(directory, node, cell, lambda s: once(s, f".DELAY_FS({old})", f".DELAY_FS({new})"))
            if fault == "coherent_cell_outside": cell["parameters"]["DELAY_FS"] = new

    edit_manifest(directory, corrupt, refresh_rtl=True)
    with pytest.raises(ValueError, match="^" + diagnostic + "$"):
        validate_export(directory)


def test_qdi_marker_semantic_name_is_not_the_obligation_identity(tmp_path):
    directory = copied(tmp_path, "qdi_buffer")

    def rename(manifest):
        node = manifest["design"]
        marker(node)["id"] = "renamed_passive_carrier"
        qdi(node)["marker"] = "renamed_passive_carrier"

    edit_manifest(directory, rename)
    assert validate_export(directory)["status"] == "PASS"


def test_coherently_omitted_qdi_channel_is_still_present_in_typed_hardware_abi(tmp_path):
    directory = copied(tmp_path, "qdi_fork")

    def omit(manifest):
        node = manifest["design"]
        policy, carrier = qdi(node), marker(node)
        removed = policy["output_channels"].pop()["channel"]
        node["channels"] = [c for c in node["channels"] if c["id"] != removed]
        endpoints = {e["id"]: e for e in node["endpoints"]}
        old_width = carrier["parameters"]["WIDTH"]
        carrier["parameters"] = marker_parameters(policy, endpoints)
        width = carrier["parameters"]["WIDTH"]
        next(p for p in carrier["ports"] if p["name"] == "values")["width"] = int(width)
        expression = "{" + ", ".join(source_path(node, endpoints[ref]["source"]).split(".", 1)[1]
                                     for ref in reversed(timing_refs(policy))) + "}"

        def reduce_marker(text):
            text = once(text, f".WIDTH({old_width})", f".WIDTH({width})")
            text, count = re.subn(r"(\.values\s*\()([^)]*)(\))", lambda m: m[1] + expression + m[3], text)
            assert count == 1, "QDI_MUTATION_MARKER_VALUES"
            return text

        change_instance(directory, node, carrier, reduce_marker)

    edit_manifest(directory, omit, refresh_rtl=True)
    with pytest.raises(ValueError, match="^QDI_CHANNEL_ABI_INVENTORY$"):
        validate_export(directory)


def test_passive_qdi_marker_imports_with_exact_specialized_ports(tmp_path):
    model = "ChiselAsyncQdiMarker_v1"
    source = ROOT / "src/main/resources/chiselasync/sv" / (model + ".sv")
    output = tmp_path / "qdi-marker.mlir"
    parameters = {"MODE": 3, "COMPONENT": 6, "WIDTH": 19,
                  "CELL_MIN_FS": 123, "CELL_MAX_FS": 456, "CELL_MODEL_FS": 234}
    result = subprocess.run([importer(), "--top", model,
                             *(arg for key, value in parameters.items() for arg in ("-G", f"{key}={value}")),
                             str(source), "-o", str(output)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    ir = output.read_text()
    assert f"hw.module @{model}(in %reset : i1, in %values : i19)" in ir, "QDI_MARKER_IMPORT_PORTS"
    assert "hw.output" in ir and "llhd." not in ir, "QDI_MARKER_IS_NOT_PASSIVE"
    # Direct import specializes and erases unused assumption parameters. The
    # emitted-RTL inventory tests above check their preservation in our export;
    # this test does not claim constraint retention through arbitrary IR import.
