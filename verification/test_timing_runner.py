# SPDX-License-Identifier: Apache-2.0
import json
import pytest
from run_timing import verify_evidence


def write_case(directory, event):
    name = "timing_contract"
    record = {"case": name, "status": "PASS", "observations": 1,
              "coverage": {"captures": 65, "launches": 66, "aborted": 1,
                           "equal_payload_new_identity": 1, "payload_bits": 8, "identity_bits": 32}}
    (directory / f"{name}.evidence.json").write_text(json.dumps(record))
    (directory / f"{name}.trace.jsonl").write_text(json.dumps(event) + "\n")


def test_claimed_captures_require_actual_observations(tmp_path):
    write_case(tmp_path, {"index": 1, "time_fs": 10, "kind": "summary"})
    with pytest.raises(RuntimeError, match="Missing observed captures"):
        verify_evidence(tmp_path, "timing_contract", None, "timed_equal", None)


@pytest.mark.parametrize("bad_time", [-1, 2**63, 1.0, "1"])
def test_trace_times_cannot_be_rounded_or_out_of_range(tmp_path, bad_time):
    write_case(tmp_path, {"index": 1, "time_fs": bad_time, "kind": "capture_sample"})
    with pytest.raises(RuntimeError, match="integer-femtosecond"):
        verify_evidence(tmp_path, "timing_contract", None, "timed_equal", None)
