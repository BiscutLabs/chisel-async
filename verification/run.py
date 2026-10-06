# SPDX-License-Identifier: Apache-2.0
"""Native event tests with strict result inventory, negative control, and retained logs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = {
    "buffer": "BufferExample", "wide": "WideBufferExample",
    "packet": "PacketBufferExample", "pipeline": "PipelineExample", "celement": "CElementExample",
    "structural": "StructuralBufferExample", "structural_wide": "StructuralWideExample",
    "structural_packet": "StructuralPacketExample", "structural_pipeline": "StructuralPipelineExample",
    "transform": "TransformExample",
    "longhold": "LongHoldExample", "longhold_wide": "LongHoldWideExample",
    "longhold_packet": "LongHoldPacketExample", "longhold_pipeline": "LongHoldPipelineExample",
}
WIDTHS = {"buffer": 8, "wide": 65, "packet": 22, "pipeline": 8,
          "structural": 8, "structural_wide": 65, "structural_packet": 22,
          "structural_pipeline": 8, "transform": 8, "longhold": 8, "longhold_wide": 65,
          "longhold_packet": 22, "longhold_pipeline": 8}
PIPELINES = {"pipeline", "structural_pipeline", "longhold_pipeline"}
CONTROLS = {
    "payload-invert": ("transaction_stream", "PAYLOAD_MISMATCH", "out_bits <= in_bits;", "out_bits <= ~in_bits;"),
    "request-glitch": ("transaction_stream", "REQUEST_WITHDRAWN", "out_req <= 1'b1;",
        "out_req <= 1'b1;\n          out_req <= #0.2 1'b0;\n          out_req <= #0.4 1'b1;"),
    "data-glitch": ("transaction_stream", "DATA_CHANGED_DURING_HANDSHAKE", "out_bits <= in_bits;",
        "out_bits <= in_bits;\n          out_bits <= #0.2 ~in_bits;\n          out_bits <= #0.4 in_bits;"),
    "reset-data": ("reset_aborts_and_restarts", "RESET_DATA_MISMATCH", "out_bits <= {WIDTH{1'b0}};",
        "out_bits <= {WIDTH{1'b1}};"),
    "bit-swap": ("payload_bit_coverage", "PAYLOAD_MISMATCH", "out_bits <= in_bits;",
        "out_bits <= {in_bits[WIDTH-1:3], in_bits[1], in_bits[2], in_bits[0]};"),
    "wide-bit-swap": ("payload_bit_coverage", "PAYLOAD_MISMATCH", "out_bits <= in_bits;",
        "out_bits <= {in_bits[64:34], in_bits[32], in_bits[33], in_bits[31:0]};"),
}
STRUCTURAL_CONTROLS = {
    # Permanent regression for a stale transparent acknowledgement enable.
    "ack-reopen": ("pending_request_and_capacity", "CAPACITY_EXCEEDED",
        ".enable (take | ack)", ".enable (take | ~in_req_0)"),
    "transform-bypass": ("transaction_stream", "PAYLOAD_MISMATCH",
        "in_bits_0 ^ 8'h55", "in_bits_0"),
}
ALL_CONTROLS = {**CONTROLS, **STRUCTURAL_CONTROLS}


def run_name(fixture, control):
    return fixture + (f"-{control}" if control else "")


def case_names(fixture: str) -> set[str]:
    if fixture == "celement":
        return {"celement_exhaustive_boolean_sequences", "celement_unknowns_and_reset_dominance"}
    result = {"transaction_stream", "reset_aborts_and_restarts", "payload_bit_coverage", "reset_full_capacity"}
    if fixture not in PIPELINES:
        result.add("pending_request_and_capacity")
        result.add("bounded_handshake_schedules")
    return result


def read_sources(directory: Path) -> list[Path]:
    filelist = directory / "filelist.f"
    if not filelist.is_file():
        raise RuntimeError("Missing generated filelist; run EmitFixtures first")
    # firtool emits host path separators. Normalize both forms when moving a fixture.
    sources = [(directory / line.strip().replace("\\", "/")).resolve()
               for line in filelist.read_text().splitlines() if line.strip()]
    if not sources or len(sources) != len(set(sources)):
        raise RuntimeError("Empty or duplicate generated source list")
    for source in sources:
        if not source.is_relative_to(directory.resolve()) or not source.is_file():
            raise RuntimeError(f"Invalid/missing generated source: {source}")
    return sources


def verify_results(xml: Path, expected: set[str], diagnostic: str | None, log: Path) -> dict:
    cases = ET.parse(xml).findall(".//testcase")
    if {case.attrib["name"] for case in cases} != expected or len(cases) != len(expected):
        raise RuntimeError("Test inventory mismatch; refusing a vacuous or partial pass")
    if any(case.find("skipped") is not None or case.find("error") is not None for case in cases):
        raise RuntimeError("Required tests were skipped or had infrastructure errors")
    failed = [case for case in cases if case.find("failure") is not None]
    if diagnostic:
        failure = failed[0].find("failure") if len(failed) == 1 else None
        if (failure is None or failure.attrib.get("type") != "AssertionError"
                or failure.attrib.get("message", "").partition("\n")[0] != diagnostic):
            raise RuntimeError(f"Known-bad model was not rejected by the required checker: {diagnostic}")
    elif failed:
        raise RuntimeError(f"Simulation failed: {[case.attrib['name'] for case in failed]}; see {log}")
    return {"cases": sorted(expected), "status": "EXPECTED_REJECTION" if diagnostic else "PASS"}


def check_activity(fixture: str, case: str, record: dict):
    widths = WIDTHS
    required = {
        "transaction_stream": {"stream_transactions": 40},
        "reset_aborts_and_restarts": {"reset_phases": 5},
        "reset_full_capacity": {"full_capacity_with_pending_reset": 1},
        "bounded_handshake_schedules": {"two_token_schedules": 18,
            "equal_and_distinct_schedule_runs": 36, "reset_prefixes": 68, "boundary_pairs": 6},
        "celement_exhaustive_boolean_sequences": {"boolean_transitions": 1024},
        "celement_unknowns_and_reset_dominance": {"four_state_checks": 5},
    }
    if case == "payload_bit_coverage":
        required[case] = {"payload_bits_each_polarity": widths[fixture], "payload_transfers": 2 * widths[fixture]}
    if any(record.get("coverage", {}).get(key) != value for key, value in required.get(case, {}).items()):
        raise RuntimeError(f"Required coverage missing for {fixture}/{case}")
    if fixture == "celement":
        return
    tokens = record.get("tokens", {})
    capacity = 2 if fixture in PIPELINES else 1
    expected = {
        "transaction_stream": (40, 40, 40, 0),
        "payload_bit_coverage": (2 * widths[fixture],) * 3 + (0,),
        "pending_request_and_capacity": (2, 2, 2, 0),
        "reset_aborts_and_restarts": (9, 7, 6, 2),
        "reset_full_capacity": (capacity + 1, 1, 1, capacity),
    }
    counts = tuple(tokens.get(key) for key in ("accepted", "delivered", "returned", "aborted"))
    if (tokens.get("outstanding") != 0 or tokens.get("reserved") != 0
            or tokens.get("capacity") != capacity or tokens.get("accepted", 0) <= 0
            or tokens.get("accepted") != tokens.get("delivered", 0) + tokens.get("aborted", 0)
            or (case in expected and counts != expected[case])):
        raise RuntimeError(f"Required token accounting missing for {fixture}/{case}")


def verify_evidence(directory: Path, expected: set[str], diagnostic: str | None, fixture: str) -> list[dict]:
    records = []
    for case in sorted(expected):
        record = json.loads((directory / f"{case}.evidence.json").read_text(encoding="utf-8"))
        status = "FAIL" if diagnostic else "PASS"
        if (record.get("case") != case or record.get("status") != status
                or record.get("observations", 0) <= 0):
            raise RuntimeError("Missing or inactive observation evidence")
        if diagnostic and str(record.get("error", "")).partition("\n")[0] != diagnostic:
            raise RuntimeError("Negative-control evidence has the wrong diagnostic")
        trace = directory / f"{case}.trace.jsonl"
        lines = trace.read_text(encoding="utf-8").splitlines()
        if len(lines) != record["observations"] or record.get("trace") != trace.name:
            raise RuntimeError("Observation trace inventory mismatch")
        previous_time = -1
        for index, line in enumerate(lines, start=1):
            event = json.loads(line)
            if event.get("index") != index or event.get("time_ps", -1) < previous_time:
                raise RuntimeError("Invalid observation trace ordering")
            previous_time = event["time_ps"]
        if not diagnostic:
            check_activity(fixture, case, record)
        record["trace_sha256"] = hashlib.sha256(trace.read_bytes()).hexdigest()
        records.append(record)
    return records


def run_one(fixture: str, control: str | None, output: Path, generated_root: Path) -> dict:
    from cocotb_tools.runner import get_runner
    sys.path.insert(0, str(ROOT / "tools"))
    from check_export import validate_export

    generated = generated_root / fixture
    resolution = validate_export(generated)
    sources = read_sources(generated)
    build_dir = output / run_name(fixture, control)
    build_dir.mkdir(parents=True, exist_ok=True)
    source_hashes = {source.name: hashlib.sha256(source.read_bytes()).hexdigest() for source in sources}
    if control:
        copies = []
        targets = 0
        for source in sources:
            contents = source.read_text(encoding="utf-8")
            target_name = (f"{FIXTURES[fixture]}.sv" if control in STRUCTURAL_CONTROLS
                           else "ChiselAsyncFourPhaseStorage_v1.sv")
            if source.name == target_name:
                targets += 1
                _, _, old, replacement = ALL_CONTROLS[control]
                if contents.count(old) != 1:
                    raise RuntimeError("Negative-control mutation target missing or ambiguous")
                contents = contents.replace(old, replacement)
            target = build_dir / source.name
            target.write_text(contents, encoding="utf-8")
            copies.append(target)
        sources = copies
        if targets != 1:
            raise RuntimeError("Negative-control model missing or ambiguous")
    expected = {ALL_CONTROLS[control][0]} if control else case_names(fixture)
    diagnostic = ALL_CONTROLS[control][1] if control else None
    # Invalidate every expected evidence file, not just the aggregate report.
    for case in expected:
        (build_dir / f"{case}.evidence.json").write_text('{"status":"RUNNING"}\n', encoding="utf-8")
        (build_dir / f"{case}.trace.jsonl").write_text("", encoding="utf-8")
    runner = get_runner("icarus")
    runner.build(sources=sources, hdl_toplevel=FIXTURES[fixture], build_dir=build_dir,
                 always=True, timescale=("1ns", "1ps"), log_file=build_dir / "build.log")
    sys.path.insert(0, str(ROOT / "verification" / "cocotb"))
    sys.path.insert(0, str(ROOT / "verification"))
    log = build_dir / "simulation.log"
    xml = runner.test(hdl_toplevel=FIXTURES[fixture], test_module="test_components",
                      extra_env={"FIXTURE": fixture, "EVIDENCE_DIR": str(build_dir)}, seed=8675309,
                      test_filter="(" + "|".join(sorted(expected)) + ")$",
                      results_xml=str(build_dir / "results.xml"), log_file=log)
    return {"fixture": fixture, "resolution": resolution, "source_sha256": source_hashes,
            "compiled_source_sha256": {source.name: hashlib.sha256(source.read_bytes()).hexdigest() for source in sources},
            "mutation": control,
            **verify_results(xml, expected, diagnostic, log),
            "evidence": verify_evidence(build_dir, expected, diagnostic, fixture)}


def execute_campaign(runs: list[tuple[str, str | None]], output: Path, generated: Path, metadata: dict) -> dict:
    report = {**metadata, "status": "RUNNING", "runs": [],
              "selected_runs": [run_name(fixture, control) for fixture, control in runs]}
    report_file = output / "report.json"

    def save():
        temporary = output / "report.json.tmp"
        temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        temporary.replace(report_file)

    save()
    try:
        for fixture, control in runs:
            name = run_name(fixture, control)
            result_file = output / f"{name}.json"
            result_file.write_text('{"status":"RUNNING"}\n', encoding="utf-8")
            command = [sys.executable, str(Path(__file__).resolve()), "--worker", "--fixture", fixture,
                       "--output", str(output), "--generated", str(generated.resolve())]
            if control:
                command.extend(["--control", control])
            subprocess.run(command, check=True, timeout=120)
            result = json.loads(result_file.read_text())
            expected_status = "EXPECTED_REJECTION" if control else "PASS"
            if result.get("status") != expected_status:
                raise RuntimeError("Worker did not produce fresh successful evidence")
            report["runs"].append(result)
            save()
            print(f"{name}: {result['status']}", flush=True)
    except BaseException as error:
        report["status"] = "TIMEOUT" if isinstance(error, subprocess.TimeoutExpired) else "ERROR"
        if isinstance(error, KeyboardInterrupt):
            report["status"] = "CANCELED"
        report["error"] = str(error)
        report["failed_run"] = name
        report["not_run"] = report["selected_runs"][len(report["runs"]) + 1:]
        save()
        raise
    report["status"] = "PASS"
    save()
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--fixture", choices=FIXTURES)
    selection.add_argument("--fixtures", choices=FIXTURES, nargs="+")
    parser.add_argument("--output", type=Path, default=ROOT / "target" / "verification")
    parser.add_argument("--generated", type=Path, default=ROOT / "target" / "generated")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--control", choices=ALL_CONTROLS, help=argparse.SUPPRESS)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if args.worker and not args.fixture:
        parser.error("--worker requires --fixture")
    if not args.worker:
        # Invalidate a previous green report before even checking tools.
        (output / "report.json").write_text('{"status":"RUNNING"}\n', encoding="utf-8")
    if not shutil.which("iverilog") or not shutil.which("vvp"):
        raise RuntimeError("Icarus 13.0 is required on PATH; no simulator fallback is performed")
    version = subprocess.run(["iverilog", "-V"], capture_output=True, text=True, check=True).stdout.splitlines()[0]
    if "version 13.0 " not in version:
        raise RuntimeError(f"Unqualified Icarus version: {version}")
    if args.worker:
        result = run_one(args.fixture, args.control, output, args.generated.resolve())
        name = run_name(args.fixture, args.control)
        (output / f"{name}.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return 0
    selected = args.fixtures or ([args.fixture] if args.fixture else list(FIXTURES))
    if len(set(selected)) != len(selected):
        parser.error("duplicate fixture selection")
    runs = [(fixture, None) for fixture in selected]
    runs += [("buffer", control) for control in CONTROLS if control != "wide-bit-swap"]
    if "wide" in selected:
        runs.append(("wide", "wide-bit-swap"))
    if "structural" in selected:
        runs.append(("structural", "ack-reopen"))
    if "transform" in selected:
        runs.append(("transform", "transform-bypass"))
    import cocotb
    metadata = {"platform": platform.platform(), "machine": platform.machine(),
              "python": sys.version, "cocotb": cocotb.__version__, "simulator": version,
              "seed": 8675309, "stimulus_seeds": {"source": 0xA51, "sink": 0xB82},
              "test_driver_sha256": hashlib.sha256((ROOT / "verification/cocotb/test_components.py").read_bytes()).hexdigest()}
    metadata["verification_sha256"] = {str(path.relative_to(ROOT)).replace("\\", "/"):
        hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted((ROOT / "verification").rglob("*.py"))}
    execute_campaign(runs, output, args.generated, metadata)
    print(f"Report: {output / 'report.json'}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError, subprocess.SubprocessError, ET.ParseError) as error:
        print(f"verification: {error}", file=sys.stderr)
        sys.exit(1)
