# SPDX-License-Identifier: Apache-2.0
import json
import os
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from qualify import ROOT, mutex_steps, run_steps


def test_mutex_lanes_require_checkers_and_a_fresh_exact_campaign(tmp_path):
    first = mutex_steps(sys.executable, tmp_path)
    second = mutex_steps(sys.executable, tmp_path)
    assert first[0] == ("mutex-checkers", [sys.executable, "-m", "pytest",
                        str(ROOT / "integrations/gf180/mutex"), "-q"])
    assert first[1][0] == "mutex-contract"
    assert first[1][1][:3] == [sys.executable, str(ROOT / "verification/run_mutex_contract.py"), "--output"]
    first_output, second_output = (Path(steps[1][1][3]) for steps in (first, second))
    assert first_output != second_output
    assert first_output.parent.is_dir() and second_output.parent.is_dir()
    assert not first_output.exists() and not second_output.exists()


def test_wrapper_stops_on_failure_and_invalidates_previous_success(tmp_path):
    (tmp_path / "report.json").write_text('{"status":"PASS"}')
    with pytest.raises(RuntimeError, match="broken failed"):
        run_steps([("broken", [sys.executable, "-c", "raise SystemExit(7)"]),
                   ("must_not_run", [sys.executable, "-c", "raise SystemExit(0)"])], dict(os.environ), tmp_path)
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["status"] == "ERROR"
    assert len(report["steps"]) == 1 and report["steps"][0]["exit_code"] == 7
    assert not (tmp_path / "must_not_run.log").exists()


def test_wrapper_rejects_empty_campaign_and_missing_executable(tmp_path):
    with pytest.raises(RuntimeError, match="EMPTY_QUALIFICATION"):
        run_steps([], dict(os.environ), tmp_path)
    with pytest.raises(OSError):
        run_steps([("missing", [str(tmp_path / "absent-executable")])], dict(os.environ), tmp_path)
    assert json.loads((tmp_path / "report.json").read_text())["status"] == "ERROR"
