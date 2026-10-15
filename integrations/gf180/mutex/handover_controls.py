# SPDX-License-Identifier: Apache-2.0
"""Check the actual output interlock against its known asymmetric-load bypass."""
import argparse
import json
import shutil
import subprocess
from pathlib import Path

from characterize import CORNERS, HERE, analyze_transient, data, header, pwl, sha
from waveform import validate_transient

INTERLOCK = '''XCLEAR0 G0 CLEAR0 VDD VSS ca_mutex_clear
XCLEAR1 G1 CLEAR1 VDD VSS ca_mutex_clear
XOUT0 F0 CLEAR1 B0 G0 VDD VSS ca_mutex_output
XOUT1 F1 CLEAR0 B1 G1 VDD VSS ca_mutex_output'''
BYPASS = '''XBUF00 F0 B0 VDD VSS ca_mutex_inv
XBUF01 B0 G0 VDD VSS ca_mutex_inv WN=2u WP=4u
XBUF10 F1 B1 VDD VSS ca_mutex_inv
XBUF11 B1 G1 VDD VSS ca_mutex_inv WN=2u WP=4u'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ngspice", default="ngspice")
    args = parser.parse_args()
    models, output = args.model_dir.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    circuit = HERE / "mutex.spice"
    mutant = output / "interlock-bypassed.spice"
    original = circuit.read_text()
    if original.count(INTERLOCK) != 1:
        raise ValueError("MUTEX_INTERLOCK_MUTATION_SHAPE")
    mutant.write_text(original.replace(INTERLOCK, BYPASS))
    executable = Path(shutil.which(args.ngspice) or args.ngspice).resolve()
    inputs = [Path(__file__), HERE / "characterize.py", HERE / "waveform.py", circuit,
              executable, models / "design.ngspice", models / "sm141064.ngspice"]
    report = {"status": "RUNNING", "physical_qualification": False,
              "inputs_sha256": {str(p): sha(p) for p in inputs},
              "mutant_sha256": sha(mutant), "cases": []}
    receipt = output / "report.json"
    receipt.write_text(json.dumps(report, indent=2) + "\n")
    for corner in CORNERS:
        voltage = corner[3]
        for is_mutant in (False, True):
            folder = output / f"{corner[0]}-{'bypass' if is_mutant else 'original'}"
            folder.mkdir()
            wave = folder / "wave.tsv"
            r0 = [(0, 0), (20, 0), (20.05, voltage), (70, voltage), (70.05, 0)]
            r1 = [(0, 0), (40, 0), (40.05, voltage), (100, voltage), (100.05, 0),
                  (160, 0), (160.05, voltage), (190, voltage), (190.05, 0)]
            reset = [(0, voltage), (10, voltage), (10.05, 0), (125, 0),
                     (125.05, voltage), (145, voltage), (145.05, 0)]
            deck = header(models, mutant if is_mutant else circuit, corner) + f'''VR0 r0 0 {pwl(r0)}
VR1 r1 0 {pwl(r1)}
VRESET reset 0 {pwl(reset)}
XD reset r0 r1 g0 g1 vdd 0 ca_mutex_gf180_candidate
CG0 g0 0 0.05p
CG1 g1 0 0.005p
.control
set wr_singlescale
set wr_vecnames
tran .0025n 230n
wrdata {wave.as_posix()} v(r0) v(r1) v(reset) v(g0) v(g1) v(xd.n0) v(xd.n1) v(xd.f0) v(xd.f1)
quit
.endc
.end
'''
            deck_path = folder / "probe.spice"
            deck_path.write_text(deck)
            command = [str(executable), "-n", "-b", str(deck_path)]
            case = {"corner": corner[0], "mutant": is_mutant, "command": command,
                    "deck_sha256": sha(deck_path)}
            try:
                result = subprocess.run(command, cwd=models, capture_output=True, text=True, timeout=30)
                log = result.stdout + result.stderr
                if result.returncode or not wave.exists():
                    raise ValueError("MUTEX_HANDOVER_SPICE_FAILED")
                names, rows = data(wave)
                validate_transient(names, rows, 230, .0025)
                checked = analyze_transient(rows, voltage, "sequence")
                required = {"MUTEX_ANALOG_GRANT_OVERLAP"} if is_mutant else set()
                allowed = required | ({"MUTEX_ANALOG_NO_QUIET_HANDOVER"} if is_mutant else set())
                observed = set(checked["errors"])
                case.update(checked, required_diagnostics=sorted(required), allowed_diagnostics=sorted(allowed),
                            passed=required <= observed <= allowed,
                            returncode=result.returncode, wave_sha256=sha(wave))
            except Exception as error:
                log = locals().get("log", "") + "\n" + str(error)
                case.update(passed=False, errors=[str(error)])
            (folder / "simulation.log").write_text(log)
            case["log_sha256"] = sha(folder / "simulation.log")
            report["cases"].append(case)
            receipt.write_text(json.dumps(report, indent=2) + "\n")
        print(corner[0], "interlock pair recorded", flush=True)
    report["inputs_unchanged"] = all(sha(p) == digest for p, digest in report["inputs_sha256"].items())
    passed = report["inputs_unchanged"] and all(c["passed"] for c in report["cases"])
    report["status"] = "HANDOVER_CONTROLS_PASS_UNQUALIFIED" if passed else "HANDOVER_CONTROLS_FAIL_UNQUALIFIED"
    receipt.write_text(json.dumps(report, indent=2) + "\n")
    print(report["status"], flush=True)
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
