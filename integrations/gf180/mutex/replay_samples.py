# SPDX-License-Identifier: Apache-2.0
"""Recheck every unchanged sampled waveform with the current mandatory oracles."""
import argparse
import json
from pathlib import Path

from characterize import CORNERS, HERE, analyze_transient, data, sha
from contention import check_contention
from waveform import FILTER_COLUMNS, validate_transient


def signature(case):
    return (case["kind"], case["corner"], case["load0_pf"], case["load1_pf"],
            case["slew0_ns"], case["slew1_ns"], case["skew_ns"],
            case["common_vdd"], case["difference_vdd"], case["mutant"])


def required_cases():
    required = set()
    for corner in CORNERS:
        name = corner[0]
        for load0, load1 in ((.005, .005), (.05, .05), (.05, .005), (.005, .05)):
            for slew0, slew1 in ((.05, .05), (.05, 5), (5, .05)):
                required.add(("sequence", name, load0, load1, slew0, slew1, 0, .5, 0, False))
                for skew in (-1, -.001, 0, .001, 1):
                    required.add(("contention", name, load0, load1, slew0, slew1, skew, .5, 0, False))
        for load in (.005, .05):
            for common in (.4, .5, .6):
                for difference in (-.01, 0, .01):
                    required.add(("filter", name, load, load, .1, .1, 0, common, difference, False))
        required.add(("filter", name, .005, .005, .1, .1, 0, .4, 0, True))
    return required


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("MUTEX_REPLAY_OUTPUT_EXISTS")
    original = json.loads(args.report.read_text())
    if original["status"] == "RUNNING" or not original.get("inputs_unchanged"):
        raise ValueError("MUTEX_REPLAY_INCOMPLETE_INPUT")
    signatures = [signature(case) for case in original["cases"]]
    if len(signatures) != len(set(signatures)) or set(signatures) != required_cases():
        raise ValueError("MUTEX_REPLAY_COVERAGE")
    report = {"status": "RUNNING", "physical_qualification": False,
              "original_report_sha256": sha(args.report), "new_spice_simulations": 0,
              "current_circuit_sha256": sha(HERE / "mutex.spice"),
              "checker_sha256": {str(path): sha(path) for path in
                  (Path(__file__), HERE / "characterize.py", HERE / "contention.py", HERE / "waveform.py")}, "cases": []}
    for index, case in enumerate(original["cases"]):
        folder = args.report.parent / f"{index:03d}-{case['kind']}-{case['corner']}"
        circuit_path = folder / "filter-bypass.spice" if case["mutant"] else HERE / "mutex.spice"
        if sha(circuit_path) != case["circuit_sha256"]:
            raise ValueError("MUTEX_REPLAY_CIRCUIT_CHANGED")
        for name, key in (("wave.tsv", "wave_sha256"), ("probe.spice", "deck_sha256"), ("simulation.log", "log_sha256")):
            if sha(folder / name) != case[key]:
                raise ValueError("MUTEX_REPLAY_INPUT_CHANGED " + str(folder / name))
        names, rows = data(folder / "wave.tsv")
        voltage = next(corner[3] for corner in CORNERS if corner[0] == case["corner"])
        if case["kind"] == "filter":
            if names != FILTER_COLUMNS or len(rows) != 1:
                raise ValueError("MUTEX_FILTER_WAVE_COLUMNS_OR_COUNT")
            errors = [] if max(rows[0][5:7]) <= .3 * voltage else ["MUTEX_FILTER_LEAKED_UNRESOLVED"]
        else:
            validate_transient(names, rows, 60 if case["kind"] == "contention" else 230,
                               min(case["slew0_ns"], case["slew1_ns"], .2)/20)
            errors = analyze_transient(rows, voltage, case["kind"])["errors"]
            if case["kind"] == "contention":
                errors = list(dict.fromkeys(errors + check_contention(rows, voltage)))
        expected = ["MUTEX_FILTER_LEAKED_UNRESOLVED"] if case["mutant"] else []
        report["cases"].append({"index": index, "errors": errors, "expected": expected,
                                "passed": errors == expected, "wave_sha256": case["wave_sha256"]})
    unchanged = all(sha(path) == digest for path, digest in report["checker_sha256"].items())
    passed = unchanged and all(case["passed"] for case in report["cases"])
    report.update(status="ALL_SAMPLED_CHECKS_PASS_UNQUALIFIED" if passed else "ALL_SAMPLED_CHECKS_FAIL_UNQUALIFIED",
                  checker_unchanged=unchanged, positives=450, negative_controls=5)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(report["status"], len(report["cases"]), flush=True)
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
