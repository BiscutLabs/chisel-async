# SPDX-License-Identifier: Apache-2.0
"""Independent waveform audit for held grants, pin slew and unresolved samples."""
import argparse
import hashlib
import json
from pathlib import Path

from characterize import data, edge
from waveform import check_held, validate_transient


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("MUTEX_AUDIT_OUTPUT_EXISTS")
    report = json.loads(args.report.read_text())
    if report["status"] == "RUNNING":
        raise ValueError("MUTEX_CAMPAIGN_NOT_COMPLETE")
    results = []
    for index, case in enumerate(report["cases"]):
        if case["kind"] == "filter":
            continue
        wave = args.report.parent / f"{index:03d}-{case['kind']}-{case['corner']}" / "wave.tsv"
        if sha(wave) != case["wave_sha256"]:
            raise ValueError("MUTEX_WAVE_CHANGED")
        names, rows = data(wave)
        validate_transient(names, rows, 60 if case['kind'] == 'contention' else 230,
                           min(case['slew0_ns'], case['slew1_ns'], .2)/20)
        voltage = {"3v30": 3.3, "3v00": 3.0, "3v60": 3.6}[case["corner"][-4:]]
        errors = check_held(rows, voltage)
        # A threshold-crossing grant must become a valid high while the request
        # remains asserted. A last-sample transition is inconclusive, not a pass.
        if case["kind"] == "contention":
            for bit in range(2):
                lower = edge(rows, bit + 4, .3 * voltage, 18, True)
                upper = edge(rows, bit + 4, .7 * voltage, 18, True)
                if lower is not None and upper is None:
                    errors.append(f"MUTEX_GRANT{bit}_PARTIAL_HIGH")
        results.append({"index": index, "errors": errors, "wave_sha256": sha(wave)})
    # Exercise the independent hold checker with an actual modified waveform
    # fragment: one request remains high while its grant makes a runt excursion.
    synthetic = [[0, 3.3, 0, 0, 0, 0], [1e-9, 3.3, 0, 0, 1.2, 0],
                 [2e-9, 3.3, 0, 0, 0, 0]]
    if check_held(synthetic, 3.3) != ["MUTEX_GRANT0_RUNT_OR_REVOKED"]:
        raise ValueError("MUTEX_RUNT_CONTROL_ESCAPED")
    output = {"status": "PASS_SAMPLED_HOLD_AUDIT_UNQUALIFIED" if all(not x["errors"] for x in results) else "FAIL",
              "physical_qualification": False, "report_sha256": sha(args.report),
              "checker_sha256": sha(Path(__file__)),
              "waveform_checker_sha256": sha(Path(__file__).with_name('waveform.py')), "cases": results,
              "synthetic_checker_controls": 1}
    args.output.write_text(json.dumps(output, indent=2) + "\n")
    print(output["status"], len(results))
    raise SystemExit(0 if output["status"].startswith("PASS") else 1)


if __name__ == "__main__":
    main()
