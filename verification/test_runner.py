# SPDX-License-Identifier: Apache-2.0
"""The qualification runner must reject false passes and unrelated failures."""
import json
import subprocess
import xml.etree.ElementTree as ET

import pytest

from run import CONTROLS, check_activity, execute_campaign, read_sources, verify_evidence, verify_results


def result(tmp_path, *, name="transaction_stream", failure=None, skipped=False):
    root = ET.Element("testsuite")
    case = ET.SubElement(root, "testcase", name=name)
    if failure:
        ET.SubElement(case, "failure", type="AssertionError", message=failure)
    if skipped:
        ET.SubElement(case, "skipped")
    path = tmp_path / "results.xml"
    ET.ElementTree(root).write(path)
    return path


def test_positive_inventory(tmp_path):
    xml = result(tmp_path)
    assert verify_results(xml, {"transaction_stream"}, False, tmp_path / "log")["status"] == "PASS"


@pytest.mark.parametrize("name,skipped", [("wrong_case", False), ("transaction_stream", True)])
def test_wrong_or_skipped_case_is_not_a_pass(tmp_path, name, skipped):
    with pytest.raises(RuntimeError):
        verify_results(result(tmp_path, name=name, skipped=skipped), {"transaction_stream"}, False, tmp_path / "log")


def test_empty_suite_is_not_a_pass(tmp_path):
    xml = tmp_path / "results.xml"
    xml.write_text("<testsuite />")
    with pytest.raises(RuntimeError, match="inventory"):
        verify_results(xml, {"transaction_stream"}, False, tmp_path / "log")


@pytest.mark.parametrize("control", CONTROLS)
def test_negative_control_requires_specific_checker(tmp_path, control):
    case, diagnostic, _, _ = CONTROLS[control]
    for failure in ("unrelated failure", diagnostic + "_UNRELATED"):
        with pytest.raises(RuntimeError, match="required checker"):
            verify_results(result(tmp_path, name=case, failure=failure), {case}, diagnostic, tmp_path / "log")
    xml = result(tmp_path, name=case, failure=diagnostic + "\nassert 1 == 0")
    assert verify_results(xml, {case}, diagnostic, tmp_path / "log")["status"] == "EXPECTED_REJECTION"


def test_known_bad_model_must_actually_fail(tmp_path):
    with pytest.raises(RuntimeError, match="required checker"):
        verify_results(result(tmp_path), {"transaction_stream"}, "PAYLOAD_MISMATCH", tmp_path / "log")


def test_missing_resource_and_directory_escape_fail(tmp_path):
    (tmp_path / "filelist.f").write_text("missing.sv\n")
    with pytest.raises(RuntimeError, match="missing generated source"):
        read_sources(tmp_path)
    (tmp_path / "filelist.f").write_text("../outside.sv\n")
    with pytest.raises(RuntimeError, match="Invalid/missing"):
        read_sources(tmp_path)


def test_timeout_invalidates_previous_success(tmp_path, monkeypatch):
    (tmp_path / "report.json").write_text('{"status":"PASS"}')
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("simulator", 120)
    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(subprocess.TimeoutExpired):
        execute_campaign([("buffer", None), ("wide", None)], tmp_path, tmp_path, {})
    assert json.loads((tmp_path / "report.json").read_text())["status"] == "TIMEOUT"
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["failed_run"] == "buffer" and report["not_run"] == ["wide"]


def test_stale_worker_evidence_is_rejected(tmp_path, monkeypatch):
    (tmp_path / "buffer.json").write_text('{"status":"PASS"}')
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: None)
    with pytest.raises(RuntimeError, match="fresh successful evidence"):
        execute_campaign([("buffer", None)], tmp_path, tmp_path, {})
    assert json.loads((tmp_path / "report.json").read_text())["status"] == "ERROR"


def stream_evidence():
    return {"schema": 1, "case": "transaction_stream", "status": "PASS", "observations": 1,
            "trace": "transaction_stream.trace.jsonl", "coverage": {"stream_transactions": 40},
            "tokens": {"accepted": 40, "delivered": 40, "returned": 40, "aborted": 0,
                       "capacity": 1, "reserved": 0, "outstanding": 0}}


def test_missing_coverage_cannot_pass_with_nonzero_observations():
    record = stream_evidence()
    record["coverage"] = {}
    with pytest.raises(RuntimeError, match="coverage missing"):
        check_activity("buffer", "transaction_stream", record)


@pytest.mark.parametrize("key,value", [("accepted", 0), ("delivered", 39), ("returned", 39),
                                      ("outstanding", 1), ("capacity", 2), ("aborted", 1)])
def test_incorrect_token_accounting_is_not_a_pass(key, value):
    record = stream_evidence()
    record["tokens"][key] = value
    with pytest.raises(RuntimeError, match="token accounting missing"):
        check_activity("buffer", "transaction_stream", record)


def test_evidence_requires_matching_retained_trace(tmp_path):
    record = stream_evidence()
    (tmp_path / "transaction_stream.evidence.json").write_text(json.dumps(record))
    trace = tmp_path / record["trace"]
    trace.write_text('{"index":1,"time_ps":10,"time_fs":10000,"kind":"summary"}\n')
    assert verify_evidence(tmp_path, {"transaction_stream"}, None, "buffer")[0]["trace_sha256"]
    trace.write_text("")
    with pytest.raises(RuntimeError, match="trace inventory"):
        verify_evidence(tmp_path, {"transaction_stream"}, None, "buffer")


def test_stale_or_empty_evidence_is_not_a_pass(tmp_path):
    evidence = tmp_path / "transaction_stream.evidence.json"
    for record in ({"status": "RUNNING"}, stream_evidence() | {"observations": 0}, stream_evidence() | {"schema": 2}):
        evidence.write_text(json.dumps(record))
        with pytest.raises(RuntimeError, match="inactive observation"):
            verify_evidence(tmp_path, {"transaction_stream"}, None, "buffer")
