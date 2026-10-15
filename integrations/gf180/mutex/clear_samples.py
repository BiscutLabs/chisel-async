# SPDX-License-Identifier: Apache-2.0
"""Sample the trial loaded-grant low detector's DC transfer curve at five PVTs."""
import argparse
import json
import shutil
import subprocess
from pathlib import Path

from characterize import CORNERS, HERE, data, header, sha


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
    files = (Path(__file__), HERE / "characterize.py", HERE / "waveform.py", circuit,
             executable, models / "design.ngspice", models / "sm141064.ngspice")
    report = {"status": "RUNNING", "physical_qualification": False,
              "inputs_sha256": {str(p): sha(p) for p in files}, "cases": []}
    receipt = output / "report.json"
    receipt.write_text(json.dumps(report, indent=2) + "\n")
    for corner in CORNERS:
        voltage = corner[3]
        folder = output / corner[0]
        folder.mkdir()
        wave = folder / "wave.tsv"
        deck = header(models, circuit, corner) + f'''VIN g 0 0
XD g clear vdd 0 ca_mutex_clear
.control
set wr_singlescale
set wr_vecnames
dc VIN 0 {voltage} {voltage/200}
wrdata {wave.as_posix()} v(g) v(clear)
quit
.endc
.end
'''
        deck_path = folder / "probe.spice"
        deck_path.write_text(deck)
        command = [str(executable), "-n", "-b", str(deck_path)]
        case = {"corner": corner[0], "command": command, "deck_sha256": sha(deck_path)}
        try:
            result = subprocess.run(command, cwd=models, capture_output=True, text=True, timeout=30)
            log = result.stdout + result.stderr
            case["returncode"] = result.returncode
            if result.returncode or not wave.exists():
                raise ValueError("MUTEX_CLEAR_SPICE_FAILED")
            names, rows = data(wave)
            if names != ["v-sweep", "v(g)", "v(clear)"] or len(rows) != 201:
                raise ValueError("MUTEX_CLEAR_SWEEP_SCHEMA")
            if any(abs(row[1] - index * voltage/200) > 1e-7 for index, row in enumerate(rows)):
                raise ValueError("MUTEX_CLEAR_SWEEP_COVERAGE")
            errors = []
            if rows[0][2] < .7 * voltage or rows[-1][2] > .3 * voltage:
                errors.append("MUTEX_CLEAR_ENDPOINT_LEVEL")
            if any(row[2] > .3 * voltage for row in rows if row[1] >= .3 * voltage):
                errors.append("MUTEX_CLEAR_ASSERTED_BEFORE_GRANT_LOW")
            if any(b[2] > a[2] + 1e-6 for a, b in zip(rows, rows[1:])):
                errors.append("MUTEX_CLEAR_NONMONOTONIC")
            case.update(errors=errors, passed=not errors, wave_sha256=sha(wave), samples=len(rows),
                maximum_sampled_grant_with_clear_vih_v=max(row[1] for row in rows if row[2] >= .7 * voltage),
                minimum_sampled_grant_with_clear_vil_v=min(row[1] for row in rows if row[2] <= .3 * voltage))
        except Exception as error:
            log = locals().get("log", "") + "\n" + str(error)
            case.update(passed=False, errors=[str(error)])
        (folder / "simulation.log").write_text(log)
        case["log_sha256"] = sha(folder / "simulation.log")
        report["cases"].append(case)
        receipt.write_text(json.dumps(report, indent=2) + "\n")
    report["inputs_unchanged"] = all(sha(p) == digest for p, digest in report["inputs_sha256"].items())
    passed = report["inputs_unchanged"] and all(c["passed"] for c in report["cases"])
    report["status"] = "CLEAR_SAMPLES_PASS_UNQUALIFIED" if passed else "CLEAR_SAMPLES_FAIL_UNQUALIFIED"
    receipt.write_text(json.dumps(report, indent=2) + "\n")
    print(report["status"], flush=True)
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
