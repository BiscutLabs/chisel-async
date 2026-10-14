# SPDX-License-Identifier: Apache-2.0
"""Core-owned mapping backgrounds for decoded state and wide masked payloads."""
from pathlib import Path
import json
import shutil
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from check_export import paired_probe_values, validate_export


@pytest.mark.parametrize("a_width,b_width", [(1, 1), (2, 8), (8, 2), (2, 337), (337, 2), (337, 337)])
def test_pairing_preserves_old_vectors_and_grows_linearly(a_width, b_width):
    values = paired_probe_values(a_width, b_width)
    pairs = set(values)
    a_mask, b_mask = (1 << a_width) - 1, (1 << b_width) - 1
    old = {(a, b) for a in {1, a_mask} for b in {1, b_mask}}
    assert old <= pairs
    assert values == sorted(pairs)
    assert len(pairs) <= 4 * (a_width + b_width)
    assert all(0 <= a <= a_mask and 0 <= b <= b_mask for a, b in pairs)
    for bit in range(a_width):
        assert (1 << bit, b_mask) in pairs
        assert (a_mask ^ (1 << bit), b_mask) in pairs
    for bit in range(b_width):
        assert (a_mask, 1 << bit) in pairs
        assert (a_mask, b_mask ^ (1 << bit)) in pairs


@pytest.mark.parametrize("width", [1, 8, 337])
def test_decoded_state_two_coincides_with_active_payload_in_both_orders(width):
    ones = (1 << width) - 1
    assert (2, ones) in paired_probe_values(2, width)
    assert (ones, 2) in paired_probe_values(width, 2)


@pytest.mark.parametrize("a_width,b_width", [(0, 1), (1, 0), (-1, 1), (1, -1), (True, 2), (2, False), (2.0, 2), (2, "2")])
def test_invalid_width_is_rejected(a_width, b_width):
    with pytest.raises(ValueError, match="^INVALID_PROBE_DRIVER_WIDTH$"):
        paired_probe_values(a_width, b_width)


@pytest.mark.parametrize("protocol", ["bd", "click"])
@pytest.mark.parametrize("settling,width", [(0, 1), (1, 8), (3, 337)])
def test_masked_receipt_reaches_every_required_bit_polarity(tmp_path, protocol, settling, width):
    fixture = f"capture_{protocol}_2_{settling}_1"
    source = ROOT / "target/generated" / fixture
    assert (source / "contract.json").is_file(), "Required receipt export missing; run EmitCaptureReceipts"
    directory = tmp_path / fixture
    shutil.copytree(source, directory)
    result = validate_export(directory)
    manifest = json.loads((directory / "contract.json").read_text())["manifest"]
    output = next(endpoint for endpoint in manifest["design"]["endpoints"] if endpoint["id"] == "out_data")
    assert output["width"] == width
    resolved = result["probe_paths"][output["probe"]]
    assert result["status"] == "PASS" and result["mapping_checks"] > 0 and resolved in result["endpoints"]
    # Assert that the actual output still has the mandatory activity criterion
    # and passed it; no extension API or scenario-specific probe is involved.
    assert f"INACTIVE_ENDPOINT:{resolved}" in (directory / "contract_probe.sv").read_text()
    log = (directory / "contract_simulation.log").read_text()
    assert f"CONTRACT_PROBES_PASS:{result['mapping_checks']}" in log
    assert "INACTIVE_ENDPOINT:" not in log
