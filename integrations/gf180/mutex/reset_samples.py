# SPDX-License-Identifier: Apache-2.0
"""Electrical reset/rearm characterization, including deliberately unsafe owner use.

The active-grant reset and stale held request are characterization stimuli, not
legal owner sequences. A passing sample demonstrates why the owner must drain
and clear/rebase requests before resetting and rearming the cell.
"""
import argparse
import json
import shutil
import subprocess
from pathlib import Path

from characterize import CORNERS, HERE, data, edge, header, pwl, sampled, sha
from waveform import check_held, validate_transient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ngspice", default="ngspice")
    args = parser.parse_args()
    models, output = args.model_dir.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    circuit = HERE / "mutex.spice"
    executable = Path(shutil.which(args.ngspice) or args.ngspice).resolve()
    inputs = [Path(__file__), HERE / "characterize.py", HERE / "waveform.py", circuit, executable,
              models / "design.ngspice", models / "sm141064.ngspice"]
    report = {"status": "RUNNING", "physical_qualification": False,
              "active_reset_is_legal_owner_operation": False,
              "inputs_sha256": {str(p): sha(p) for p in inputs}, "cases": []}
    receipt = output / "report.json"
    receipt.write_text(json.dumps(report, indent=2) + "\n")
    for corner in CORNERS:
        voltage = corner[3]
        for load in (.005, .05):
            for slew in (.05, 5):
                folder = output / f"{len(report['cases']):02d}-{corner[0]}"
                folder.mkdir()
                wave = folder / "wave.tsv"
                deck = header(models, circuit, corner)
                reset = [(0, voltage), (10, voltage), (10 + slew, 0), (40, 0), (40 + slew, voltage),
                         (60, voltage), (60 + slew, 0), (110, 0), (110 + slew, voltage),
                         (125, voltage), (125 + slew, 0)]
                r0 = [(0, 0), (20, 0), (20 + slew, voltage), (90, voltage), (90 + slew, 0)]
                r1 = [(0, 0), (140, 0), (140 + slew, voltage)]
                deck += f'''VRESET reset 0 {pwl(reset)}
VR0 r0 0 {pwl(r0)}
VR1 r1 0 {pwl(r1)}
XD reset r0 r1 g0 g1 vdd 0 ca_mutex_gf180_candidate
CG0 g0 0 {load}p
CG1 g1 0 {load}p
.control
set wr_singlescale
set wr_vecnames
tran {min(slew, .2)/20}n 170n
wrdata {wave.as_posix()} v(r0) v(r1) v(reset) v(g0) v(g1)
quit
.endc
.end
'''
                deck_path = folder / "probe.spice"
                deck_path.write_text(deck)
                command = [str(executable), "-n", "-b", str(deck_path)]
                case = {"corner": corner[0], "load_pf": load, "slew_ns": slew,
                        "command": command, "deck_sha256": sha(deck_path)}
                try:
                    result = subprocess.run(command, cwd=models, capture_output=True, text=True, timeout=30)
                    log = result.stdout + result.stderr
                    case["returncode"] = result.returncode
                    if result.returncode or not wave.exists():
                        raise ValueError("MUTEX_RESET_SPICE_FAILED")
                    names, rows = data(wave)
                    validate_transient(names, rows, 170, min(slew, .2)/20,
                        ["time", "v(r0)", "v(r1)", "v(reset)", "v(g0)", "v(g1)"])
                    errors = check_held(rows, voltage)
                    for when, expect0, expect1 in ((35, 1, 0), (55, 0, 0), (80, 1, 0),
                                                   (105, 0, 0), (120, 0, 0), (135, 0, 0), (165, 0, 1)):
                        for col, bit in ((4, expect0), (5, expect1)):
                            value = sampled(rows, when, col)
                            if (value < .7 * voltage) if bit else (value > .3 * voltage):
                                errors.append(f"MUTEX_RESET_STATE_{when}_{col}")
                    if any(row[4] > .3 * voltage and row[5] > .3 * voltage for row in rows):
                        errors.append("MUTEX_RESET_GRANT_OVERLAP")
                    assertion = edge(rows, 3, .5 * voltage, 39, True)
                    clearance = edge(rows, 4, .3 * voltage, 39, False)
                    release = edge(rows, 3, .5 * voltage, 59, False)
                    regrant = edge(rows, 4, .7 * voltage, 59, True)
                    if any(value is None for value in (assertion, clearance, release, regrant)):
                        errors.append("MUTEX_RESET_MISSING_TRANSITION")
                    else:
                        case.update(reset_to_clear_ns=clearance-assertion,
                                    unsafe_stale_request_regrant_ns=regrant-release)
                    case.update(errors=errors, passed=not errors, wave_sha256=sha(wave), samples=len(rows))
                except Exception as error:
                    log = locals().get("log", "") + "\n" + str(error)
                    case.update(errors=[str(error)], passed=False)
                (folder / "simulation.log").write_text(log)
                case["log_sha256"] = sha(folder / "simulation.log")
                report["cases"].append(case)
                receipt.write_text(json.dumps(report, indent=2) + "\n")
        print(corner[0], "reset samples recorded", flush=True)
    report["inputs_unchanged"] = all(sha(p) == digest for p, digest in report["inputs_sha256"].items())
    passed = report["inputs_unchanged"] and all(c["passed"] for c in report["cases"])
    report["status"] = "RESET_SAMPLES_PASS_UNQUALIFIED" if passed else "RESET_SAMPLES_FAIL_UNQUALIFIED"
    receipt.write_text(json.dumps(report, indent=2) + "\n")
    print(report["status"], flush=True)
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
