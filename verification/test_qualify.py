# SPDX-License-Identifier: Apache-2.0
import json
import os
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from qualify import run_steps


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
