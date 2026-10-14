# SPDX-License-Identifier: Apache-2.0
"""Retained-payload receiver exports, functional clocks/joins, and actual-RTL faults."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

from run import ROOT, read_sources
sys.path.insert(0, str(ROOT / "tools"))
from check_export import validate_export


def require(condition, diagnostic):
    if not condition:
        raise ValueError(diagnostic)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixtures():
    for click in (0, 1):
        for stages in (2, 3):
            for settling, width in ((0, 1), (1, 8), (3, 337)):
                for mask in (0, 1):
                    yield dict(id=f"capture_{'click' if click else 'bd'}_{stages}_{settling}_{mask}",
                               click=click, stages=stages, settling=settling, width=width, mask=mask)


def audit(log, fixture):
    rows = re.findall(r"^CAPTURE D ([0-9a-f]+)$", log, re.M)
    width, click = fixture["width"], fixture["click"]
    mask = (1 << width) - 1
    expected = [mask, 0, 0, mask]
    for bit in range(width):
        expected += [1 << bit, mask ^ (1 << bit)]
    expected += [1] * (1 if click else 2)
    if click:
        expected += [mask, mask, 0]
    expected += [0, mask]
    require([int(row, 16) for row in rows] == expected, "CAPTURE_TRACE_PAYLOAD")
    actual = dict(delivered=2*width+6+2*click, accepted=len(expected), resets=7 if click else 6,
                  stopped=2*width+5+2*click)
    marker = "CAPTURE_PASS " + " ".join(f"{key}={value}" for key, value in actual.items())
    require(log.splitlines().count(marker) == 1, "CAPTURE_TRACE_ACTIVITY")
    require(not re.search(r"FATAL:|ERROR:", log), "CAPTURE_TRACE_FAILURE")
    return actual


def bench(fixture, top):
    text = (ROOT / "verification/capture_receipts/receipt.sv").read_text()
    values = {**{key.upper(): value for key, value in fixture.items()}, "TOP": top}
    for key, value in values.items():
        text = text.replace(f"@{key}@", str(value))
    require(not re.search(r"@[A-Z_]+@", text), "CAPTURE_TEMPLATE")
    return text


def execute(name, sources, text, output, fixture, qualified=0, diagnostic=None):
    directory = output / name
    directory.mkdir()
    path = directory / "bench.sv"
    path.write_text(text, encoding="utf-8")
    binary = directory / "bench.vvp"
    command = ["iverilog", "-g2012", "-s", "CaptureReceiptBench",
               f"-PCaptureReceiptBench.QUALIFIED={qualified}", "-o", str(binary), str(path),
               *map(str, sources)]
    compiled = subprocess.run(command, capture_output=True, text=True, timeout=60)
    (directory / "compile.log").write_text(compiled.stdout + compiled.stderr, encoding="utf-8")
    require(compiled.returncode == 0, f"CAPTURE_COMPILE:{name}")
    run = subprocess.run(["vvp", str(binary)], cwd=directory, capture_output=True, text=True, timeout=60)
    log = run.stdout + run.stderr
    (directory / "simulation.log").write_text(log, encoding="utf-8")
    activity = None
    if diagnostic is None:
        require(run.returncode == 0, f"CAPTURE_SIMULATION:{name}")
        activity = audit(log, fixture)
    else:
        # Expected rejection must be a real executed assertion at its exact
        # testbench line and scope, not matching display text or another crash.
        expected_lines = [index for index, line in enumerate(text.splitlines(), 1)
                          if f'$fatal(1,"{diagnostic}")' in line]
        require(len(expected_lines) == 1, "CAPTURE_FATAL_SITE")
        pattern = (r"^FATAL: " + re.escape(str(path)) + ":" + str(expected_lines[0]) + ": "
                   + re.escape(diagnostic) + r"\r?\n\s*Time: [0-9]+\s+Scope: CaptureReceiptBench\r?$")
        require(run.returncode == 1 and len(re.findall(r"^FATAL:", log, re.M)) == 1
                and re.search(pattern, log, re.M), f"CAPTURE_WRONG_REJECTION:{name}")
    record = dict(case=name, status="EXPECTED_REJECTION" if diagnostic else "PASS",
                  diagnostic=diagnostic, activity=activity, compile=command,
                  sources={str(source): sha(source) for source in sources},
                  evidence={p.name: sha(p) for p in directory.iterdir() if p.is_file()})
    (directory / "case.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def mutate(sources, top, output, name, signal, expression):
    originals = [path for path in sources if path.name == top + ".sv"]
    require(len(originals) == 1, "CAPTURE_MUTATION_MODULE")
    original = originals[0]
    pattern = rf"(\bassign {signal}\s*=\s*)([^;]+);"
    changed, count = re.subn(pattern, lambda match: match[1] + expression(match[2]) + ";", original.read_text())
    require(count == 1, "CAPTURE_MUTATION_TARGET")
    path = output / (name + ".sv")
    path.write_text(changed, encoding="utf-8")
    return [path if source == original else source for source in sources]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generated", type=Path, default=ROOT / "target/generated")
    parser.add_argument("--output", type=Path, default=ROOT / "target/verification/capture-receipts")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = dict(status="RUNNING", platform=platform.platform(), cases=[], exports={},
                  runner_sha256=sha(Path(__file__)),
                  bench_sha256=sha(ROOT / "verification/capture_receipts/receipt.sv"))
    report_path = output / "report.json"
    def save():
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    save()
    try:
        join = output / "ChiselAsyncCElement_v1.sv"
        shutil.copy2(ROOT / "src/main/resources/chiselasync/sv/ChiselAsyncCElement_v1.sv", join)
        for fixture in fixtures():
            directory = output / "exports" / fixture["id"]
            shutil.copytree(args.generated.resolve() / fixture["id"], directory)
            report["exports"][fixture["id"]] = validate_export(directory)
            manifest = json.loads((directory / "contract.json").read_text())["manifest"]
            top = manifest["top"]
            sources = read_sources(directory) + [join]
            text = bench(fixture, top)
            for qualified in (0, 1):
                report["cases"].append(execute(fixture["id"] + f"_clock{qualified}", sources,
                                                text, output, fixture, qualified))
                save()
            if fixture["stages"] == 2 and fixture["settling"] == 1:
                faults = [("invalid_mask", "out_bits", lambda _: "in_bits", "CAPTURE_INVALID_MASK_INITIAL")] if fixture["mask"] else [
                    ("payload", "out_bits", lambda rhs: f"({rhs}) ^ (out_valid ? 8'h1 : 8'h0)", "CAPTURE_CONSUMER_PAYLOAD"),
                    ("early_ack", "in_ack", lambda _: "in_req", "CAPTURE_ACK_EARLY"),
                    ("missing_valid", "out_valid", lambda _: "1'b0", "CAPTURE_LATENCY"),
                ]
                for fault, signal, expression, diagnostic in faults:
                    name = fixture["id"] + "_" + fault
                    changed = mutate(sources, top, output, name, signal, expression)
                    report["cases"].append(execute(name, changed, text, output, fixture, diagnostic=diagnostic))
                    save()
        require(len(report["cases"]) == 56 and len(report["exports"]) == 24, "CAPTURE_CASE_INVENTORY")
        report["status"] = "PASS"
    except BaseException as error:
        report.update(status="ERROR", error=str(error))
        save()
        raise
    save()
    print(f"Capture receipts PASS: {len(report['cases'])} cases; {report_path}")


if __name__ == "__main__":
    main()
