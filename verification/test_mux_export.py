"""Adversarial timing-contract checks for the public controlled multiplexer."""
import copy
import json
from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from check_export import validate_manifest, semantic_hash


def check(value):
    validate_manifest({"semantic_sha256": semantic_hash(value), "manifest": value})


def manifest():
    path = ROOT / "target/generated/mux/contract.json"
    if not path.is_file():
        pytest.fail("Required mux export missing; run EmitComposition")
    return json.loads(path.read_text())["manifest"]


def test_controlled_mux_preserves_its_whole_glue_path():
    value = manifest()
    check(value)
    path, = [t for t in value["design"]["timing"] if t.get("logic") == "controlled-multiplexer-input-mux"]
    assert path["delay_owner"] == ["storage"]
    assert path["source"] == "mux_sources" and path["sink"] == "mux_result"


@pytest.mark.parametrize("fault,diagnostic", [("owner","INVALID_DATA_PATH_BINDING"),
    ("budget","DATA_PATH_PARAMETER_MISMATCH"), ("missing","MISSING_MUX_CONSTRAINT")])
def test_controlled_mux_rejects_missing_or_misdirected_budget(fault,diagnostic):
    value = copy.deepcopy(manifest())
    node = value["design"]
    path, = [t for t in node["timing"] if t.get("logic") == "controlled-multiplexer-input-mux"]
    if fault == "owner":
        path["delay_owner"] = []
    elif fault == "budget":
        path["budget"]["model_fs"] = path["budget"]["min_fs"]
    else:
        node["timing"].remove(path)
    with pytest.raises(ValueError, match=f"^{diagnostic}$"):
        check(value)
