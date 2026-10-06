# SPDX-License-Identifier: Apache-2.0
"""Strict timed-model qualification with activated, diagnostic-specific rejection controls."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

from run import read_sources, verify_results
from trace_contract import validate_events

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from check_export import validate_export

# name: fixture, test, expected diagnostic, hold offset fs, mutation
JOBS = {
    "latch": ("latch", "latch_contract", None, None, None),
    "transport": ("transport", "delay_contract", None, None, None),
    "inertial": ("inertial", "delay_contract", None, None, None),
    "setup_early": ("timed_early", "timing_contract", "TIMING_SETUP", None, None),
    "setup_equal": ("timed_equal", "timing_contract", None, None, None),
    "setup_late": ("timed_late", "timing_contract", None, None, None),
    "hold_early": ("timed_equal", "timing_contract", "TIMING_HOLD", 1999, None),
    "hold_equal": ("timed_equal", "timing_contract", None, 2000, None),
    "hold_late": ("timed_equal", "timing_contract", None, 2001, None),
    "delay_reset_fault": ("transport", "delay_contract", "DELAY_TRACE_MISMATCH", None, "reset"),
    "delay_policy_fault": ("transport", "delay_contract", "DELAY_TRACE_MISMATCH", None, "policy"),
    "identity_fault": ("timed_equal", "timing_contract", "TIMING_DATA_NOT_VALID", None, "identity"),
    "capture_fault": ("timed_equal", "timing_contract", "TIMING_MISSING_CAPTURE", None, "capture"),
    "latch_fault": ("timed_equal", "timing_contract", "TIMING_CAPTURED_VALUE", None, "latch"),
}
MUTATIONS = {
    "reset": ("ChiselAsyncDelayLine_v1.sv", " && delivery[WIDTH+127:WIDTH+64] == epoch", ""),
    "policy": ("ChiselAsyncDelayLine_v1.sv", "POLICY == 0 ||", "1'b0 ||"),
    "identity": ("ChiselAsyncDelayLine_v1.sv", "q <= delivery[WIDTH-1:0];", "q <= delivery[WIDTH-1:0] & 8'hff;"),
    "capture": ("ChiselAsyncDelayLine_v1.sv", "if (reset === 1'b0 && initialized &&", "if (1'b0 && initialized &&"),
    "latch": ("ChiselAsyncLatch_v1.sv", "q <= d;", "q <= ~d;"),
}


def hashes(paths):
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def verify_evidence(directory, case, diagnostic, fixture, hold):
    record = json.loads((directory / f"{case}.evidence.json").read_text())
    expected = "FAIL" if diagnostic else "PASS"
    if (record.get("schema") != 1 or record.get("case") != case or record.get("status") != expected or record.get("observations", 0) <= 0
            or diagnostic and str(record.get("error", "")).partition("\n")[0] != diagnostic):
        raise RuntimeError("Missing, inactive or incorrect timing evidence")
    trace = directory / f"{case}.trace.jsonl"
    events = [json.loads(line) for line in trace.read_text().splitlines()]
    if len(events) != record["observations"] or any(e["index"] != i for i, e in enumerate(events, 1)):
        raise RuntimeError("Timing trace inventory mismatch")
    validate_events(events)
    if not diagnostic:
        coverage = record["coverage"]
        if fixture == "latch":
            required = {"latch_checks": 65}
            if sum(event["kind"] == "latch_sample" for event in events) != 65:
                raise RuntimeError("Incomplete latch observations")
        elif case == "delay_contract":
            required = {"input_events": 22, "pulse_boundaries": 3, "reset_pending": 3,
                        "reset_at_delivery": 1, "release_unchanged_data": 2}
            if coverage.get("deliveries", 0) <= 0 or sum(e["kind"] == "delay_delivery" for e in events) != coverage["deliveries"]:
                raise RuntimeError("Inactive delay observations")
        elif hold:
            required = {"hold_boundary": 1, "equal_payload_new_identity": 1, "captures": 1}
        else:
            required = {"captures": 65, "launches": 66, "aborted": 1, "equal_payload_new_identity": 1,
                        "payload_bits": 8, "identity_bits": 32}
        if case == "timing_contract" and sum(e["kind"] == "capture_sample" for e in events) != coverage.get("captures"):
            raise RuntimeError("Missing observed captures")
        if any(coverage.get(key) != value for key, value in required.items()):
            raise RuntimeError("Incomplete timing coverage")
    record["trace_sha256"] = hashlib.sha256(trace.read_bytes()).hexdigest()
    return record


def run_one(name, generated, output):
    from cocotb_tools.runner import get_runner
    fixture, case, diagnostic, hold, mutation = JOBS[name]
    directory = generated / fixture
    resolved = validate_export(directory)
    manifest = json.loads((directory / "contract.json").read_text())["manifest"]
    sources = read_sources(directory)
    original_hashes = hashes(sources)
    build = output / name
    build.mkdir(parents=True, exist_ok=True)
    if mutation:
        filename, old, replacement = MUTATIONS[mutation]
        changed, copies = 0, []
        for source in sources:
            text = source.read_text()
            if source.name == filename:
                if text.count(old) != 1:
                    raise RuntimeError("Missing or ambiguous timing mutation target")
                text = text.replace(old, replacement)
                changed += 1
            destination = build / source.name
            destination.write_text(text, encoding="utf-8")
            copies.append(destination)
        if changed != 1:
            raise RuntimeError("Timing mutation not activated")
        sources = copies
    (build / f"{case}.evidence.json").write_text('{"status":"RUNNING"}')
    (build / f"{case}.trace.jsonl").write_text("")
    runner = get_runner("icarus")
    runner.build(sources=sources, hdl_toplevel=manifest["top"], build_dir=build, always=True,
                 timescale=("1fs", "1fs"), log_file=build / "build.log")
    sys.path.insert(0, str(ROOT / "verification/cocotb"))
    capture_fs = {"timed_early": 9999, "timed_equal": 10000, "timed_late": 10001}.get(fixture, 0)
    environment = {"FIXTURE": fixture, "CONTRACT": str(directory / "contract.json"),
                   "EVIDENCE_DIR": str(build), "CAPTURE_FS": str(capture_fs), "HOLD_OFFSET": str(hold or "")}
    log = build / "simulation.log"
    xml = runner.test(hdl_toplevel=manifest["top"], test_module="test_timing", test_filter=f"\\.{case}$",
                      extra_env=environment, seed=8675309, results_xml=str(build / "results.xml"), log_file=log)
    return {"name": name, "fixture": fixture, "mutation": mutation, "resolution": resolved,
            "source_sha256": original_hashes, "compiled_source_sha256": hashes(sources),
            **verify_results(xml, {case}, diagnostic, log),
            "evidence": verify_evidence(build, case, diagnostic, fixture, hold)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", choices=JOBS)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--generated", type=Path, default=ROOT / "target/generated")
    parser.add_argument("--output", type=Path, default=ROOT / "target/verification/timing")
    args = parser.parse_args()
    output, generated = args.output.resolve(), args.generated.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if args.worker:
        if not args.job:
            parser.error("Worker requires a job")
        result = run_one(args.job, generated, output)
        (output / f"{args.job}.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return
    import cocotb
    report = {"status": "RUNNING", "platform": platform.platform(), "python": sys.version,
              "cocotb": cocotb.__version__, "time_unit": "fs", "precision_fs": 1,
              "selected_runs": [args.job] if args.job else list(JOBS), "runs": [],
              "verification_sha256": {str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
                                      for p in sorted((ROOT / "verification").rglob("*.py"))}}
    def save():
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    save()
    try:
        for name in report["selected_runs"]:
            result_file = output / f"{name}.json"
            result_file.write_text('{"status":"RUNNING"}')
            subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", "--job", name,
                            "--generated", str(generated), "--output", str(output)], check=True, timeout=120)
            result = json.loads(result_file.read_text())
            if result.get("status") != ("EXPECTED_REJECTION" if JOBS[name][2] else "PASS"):
                raise RuntimeError("Incomplete timing worker result")
            report["runs"].append(result)
            save()
            print(f"{name}: {result['status']}", flush=True)
    except BaseException as error:
        report.update(status="ERROR", error=str(error), failed_run=name,
                      not_run=report["selected_runs"][len(report["runs"])+1:])
        save()
        raise
    report["status"] = "PASS"
    save()
    print(f"Timing evidence: {output / 'report.json'}")


if __name__ == "__main__":
    main()
