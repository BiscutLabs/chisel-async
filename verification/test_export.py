# SPDX-License-Identifier: Apache-2.0
"""Adversarial export checks against compiled RTL, not fabricated parser fixtures."""
import copy
import json
from pathlib import Path
import shutil
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from check_export import sha, rtl_hash, semantic_hash, unique_json, validate_export, validate_manifest
from run import read_sources


@pytest.fixture
def exported(tmp_path):
    source = ROOT / "target/generated/buffer"
    if not (source / "contract.json").is_file():
        pytest.fail("Required export missing; run EmitFixtures before compiler tests")
    directory = tmp_path / "copied export with spaces"
    shutil.copytree(source, directory)
    return directory


def edit_manifest(directory, change, refresh_rtl=False):
    path = directory / "contract.json"
    document = json.loads(path.read_text())
    change(document["manifest"])
    if refresh_rtl:
        abi = document["manifest"]["probe_abi"]
        abi["sha256"] = sha((directory / abi["file"]).read_text().encode())
        document["manifest"]["rtl_semantic_sha256"] = {s.name: rtl_hash(s) for s in read_sources(directory)}
    document["semantic_sha256"] = semantic_hash(document["manifest"])
    path.write_text(json.dumps(document), encoding="utf-8")


def test_export_survives_moving_to_path_with_spaces(exported):
    result = validate_export(exported)
    assert result["status"] == "PASS" and result["mapping_checks"] == 294
    assert len(result["endpoints"]) == 7


@pytest.mark.parametrize("fault,diagnostic", [
    ("duplicate", "DUPLICATE_SEMANTIC_ID"), ("alias", "AMBIGUOUS_RTL_PATH"),
    ("domain", "RESET_DOMAIN_MISMATCH"), ("width", "INVALID_CHANNEL_CONTROL"),
    ("missing", "ENDPOINT_MISMATCH"), ("parameter", "PRIMITIVE_PARAMETER_MISMATCH"),
    ("unregistered", "UNREGISTERED_MODULE_OR_PRIMITIVE"),
])
def test_descriptor_corruption_is_rejected_by_specific_checks(exported, fault, diagnostic):
    def change(manifest):
        design = manifest["design"]
        if fault == "duplicate":
            design["endpoints"].append(copy.deepcopy(design["endpoints"][0]))
        elif fault == "alias":
            design["endpoints"][1]["rtl_path"] = design["endpoints"][0]["rtl_path"]
        elif fault == "domain":
            design["primitives"][0]["reset_domain"] = "independent"
        elif fault == "width":
            design["endpoints"][0]["width"] = 2
        elif fault == "missing":
            design["endpoints"][0]["rtl_path"] += "_missing"
        elif fault == "parameter":
            design["primitives"][0]["parameters"]["WIDTH"] = "9"
        else:
            design["primitives"] = []
            manifest["resources"] = {}
    edit_manifest(exported, change)
    with pytest.raises(ValueError, match=f"^{diagnostic}$"):
        validate_export(exported)
    assert json.loads((exported / "resolved.json").read_text())["status"] != "PASS"


@pytest.mark.parametrize("fault,diagnostic", [("mapping", "ENDPOINT_MAPPING_MISMATCH"),
                                             ("reset", "RESET_BINDING_MISMATCH")])
def test_rtl_corruption_rejected_even_with_rehashed_manifest(exported, fault, diagnostic):
    path = exported / "BufferExample.sv"
    text = path.read_text()
    if fault == "mapping":
        abi = exported / "ref_BufferExample.sv"
        refs = abi.read_text()
        old = "ca_p_7_in_data in_bits"
        assert refs.count(old) == 1
        # A valid same-width reference to a deliberately permuted source.
        text = text.replace("endmodule", "wire [7:0] wrong_bits = {in_bits[7:2],in_bits[0],in_bits[1]};\nendmodule")
        abi.write_text(refs.replace(old, "ca_p_7_in_data wrong_bits"))
    else:
        old = ".reset    (reset)"
        assert text.count(old) == 1
        text = text.replace(old, ".reset    (1'b0)")
    path.write_text(text, encoding="utf-8")
    edit_manifest(exported, lambda _: None, refresh_rtl=True)
    with pytest.raises(ValueError, match=f"^{diagnostic}$"):
        validate_export(exported)


def test_missing_and_altered_resource_cannot_pass(exported):
    resource = exported / "ChiselAsyncFourPhaseStorage_v1.sv"
    resource.write_text(resource.read_text() + "// changed\n", encoding="utf-8")
    edit_manifest(exported, lambda _: None, refresh_rtl=True)
    with pytest.raises(ValueError, match="^RESOURCE_HASH_MISMATCH$"):
        validate_export(exported)
    resource.unlink()
    with pytest.raises(RuntimeError, match="Invalid/missing generated source"):
        validate_export(exported)


def test_stale_manifest_and_duplicate_json_keys_rejected(exported):
    document = json.loads((exported / "contract.json").read_text())
    document["manifest"]["design"]["reset_domain"] = "changed"
    with pytest.raises(ValueError, match="SEMANTIC_HASH_MISMATCH"):
        validate_manifest(document)
    with pytest.raises(ValueError, match="DUPLICATE_JSON_KEY"):
        json.loads('{"x":1,"x":2}', object_pairs_hook=unique_json)


@pytest.mark.parametrize("fault,diagnostic", [("deleted", "MISSING_TIMING_ENDPOINT"),
                                             ("overflow", "INVALID_MODEL_TIME"),
                                             ("numeric", "INVALID_MODEL_TIME")])
def test_timing_endpoint_and_exact_bound_are_required(fault, diagnostic):
    document = json.loads((ROOT / "target/generated/timed_equal/contract.json").read_text())
    design = document["manifest"]["design"]
    if fault == "deleted":
        design["endpoints"] = [e for e in design["endpoints"] if e["id"] != "data_valid"]
    else:
        design["timing"][0]["setup_fs"] = str(2**63) if fault == "overflow" else 2000
    document["semantic_sha256"] = semantic_hash(document["manifest"])
    with pytest.raises(ValueError, match=f"^{diagnostic}$"):
        validate_manifest(document)


def test_unknown_contract_constraints_are_not_silently_ignored(exported):
    document = json.loads((exported / "contract.json").read_text())
    document["manifest"]["design"]["unsupported_constraint"] = {"required": True}
    document["semantic_sha256"] = semantic_hash(document["manifest"])
    with pytest.raises(ValueError, match="UNSUPPORTED_CONTRACT_FIELDS"):
        validate_manifest(document)
