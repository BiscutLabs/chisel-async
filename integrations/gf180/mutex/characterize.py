# SPDX-License-Identifier: Apache-2.0
"""Bounded, unqualified GF180 Mutex schematic samples using external ngspice."""
import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from contention import check_contention
from waveform import FILTER_COLUMNS, check_held, data, validate_transient

HERE = Path(__file__).resolve().parent
CORNERS = (("tt_025C_3v30", "typical", 25, 3.3),
           ("ss_125C_3v00", "ss", 125, 3.0), ("ss_n40C_3v00", "ss", -40, 3.0),
           ("ff_125C_3v60", "ff", 125, 3.6), ("ff_n40C_3v60", "ff", -40, 3.6))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pwl(points):
    return "PWL(" + " ".join(f"{time:.12g}n {value:.12g}" for time, value in points) + ")"


def header(models, circuit, corner):
    _, process, temperature, voltage = corner
    return f'''GF180 Mutex schematic experiment, unqualified
.include "{(models / 'design.ngspice').as_posix()}"
.lib "{(models / 'sm141064.ngspice').as_posix()}" {process}
.include "{circuit.as_posix()}"
.param sw_stat_global=0 sw_stat_mismatch=0
.temp {temperature}
.options method=gear reltol=1e-5 abstol=1e-13 vntol=1e-7
VDD vdd 0 {voltage}
'''


def edge(rows, column, level, after_ns, rising):
    for before, after in zip(rows, rows[1:]):
        if after[0] < after_ns * 1e-9:
            continue
        if (before[column] < level <= after[column]) if rising else (before[column] > level >= after[column]):
            slope = after[column] - before[column]
            return (before[0] + (after[0] - before[0]) * (level - before[column]) / slope) * 1e9
    return None


def sampled(rows, at_ns, column):
    return min(rows, key=lambda row: abs(row[0] - at_ns * 1e-9))[column]


def analyze_transient(rows, voltage, mode):
    # Columns: time, R0, R1, RESET, G0, G1, internal N0/N1, filter F0/F1.
    errors = check_held(rows, voltage)
    lo, hi = .3 * voltage, .7 * voltage
    if any(row[4] > lo and row[5] > lo for row in rows if row[0] > 15e-9):
        errors.append("MUTEX_ANALOG_GRANT_OVERLAP")
    if any(row[4] < -.1 * voltage or row[5] < -.1 * voltage or
           row[4] > 1.1 * voltage or row[5] > 1.1 * voltage for row in rows):
        errors.append("MUTEX_ANALOG_OUTPUT_RAIL")
    result = {"errors": errors}
    if mode == "contention":
        errors.extend(check_contention(rows, voltage))
        first = [edge(rows, col, hi, 18, True) for col in (4, 5)]
        resolved = [value for value in first if value is not None]
        result.update(first_grant_ns=min(resolved) if resolved else None,
                      unresolved_at_end=not resolved,
                      maximum_resolution_bound_ns=None)
        return result
    expected = ((35, 1, 0), (60, 1, 0), (90, 0, 1), (120, 0, 0),
                (140, 0, 0), (155, 0, 0), (180, 0, 1), (220, 0, 0))
    for when, bit0, bit1 in expected:
        values = [sampled(rows, when, col) for col in (4, 5)]
        if any(value < hi if bit else value > lo for value, bit in zip(values, (bit0, bit1))):
            errors.append(f"MUTEX_SEQUENCE_{when}NS")
    rise0 = edge(rows, 4, hi, 18, True)
    release0 = edge(rows, 4, lo, 68, False)
    handover = edge(rows, 5, hi, 68, True)
    release1 = edge(rows, 5, lo, 98, False)
    request0 = edge(rows, 1, .5 * voltage, 18, True)
    request_release0 = edge(rows, 1, .5 * voltage, 68, False)
    request_release1 = edge(rows, 2, .5 * voltage, 98, False)
    measurements = (rise0, release0, handover, release1, request0, request_release0, request_release1)
    if any(value is None for value in measurements):
        errors.append("MUTEX_MISSING_TIMING_ACTIVITY")
    else:
        result.update(uncontended_to_vih_ns=rise0 - request0,
                      release0_to_vil_ns=release0 - request_release0,
                      release1_to_vil_ns=release1 - request_release1,
                      quiet_vil_to_vih_ns=handover - release0)
        if handover <= release0:
            errors.append("MUTEX_ANALOG_NO_QUIET_HANDOVER")
    for col in (4, 5):
        starts = [edge(rows, col, level * voltage, 18 if col == 4 else 68, True) for level in (.1, .9)]
        result[f"grant{col-4}_rise_10_90_ns"] = starts[1] - starts[0] if all(v is not None for v in starts) else None
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()
    models, output = args.model_dir.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    circuit = HERE / "mutex.spice"
    executable = Path(shutil.which(args.ngspice) or args.ngspice).resolve()
    inputs = [circuit, Path(__file__), HERE / "waveform.py", HERE / "contention.py",
              models / "design.ngspice", models / "sm141064.ngspice", executable]
    report = {"status": "RUNNING", "physical_qualification": False,
              "layout": None, "extracted_circuit": None, "statistical_variation": False,
              "inputs_sha256": {str(p): sha(p) for p in inputs}, "cases": [],
              "receiver_thresholds_vdd": {"vil": .3, "vih": .7}}
    report_path = output / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    version = subprocess.run([str(executable), "--version"], capture_output=True, text=True, timeout=30, check=True)
    report["simulator"] = version.stdout + version.stderr

    def run_case(kind, corner, load, slew0=.1, slew1=.1, skew=0, common=.5, difference=0, mutant=False, load1=None):
        index = len(report["cases"])
        folder = output / f"{index:03d}-{kind}-{corner[0]}"
        folder.mkdir()
        source = circuit
        if mutant:
            source = folder / "filter-bypass.spice"
            original = circuit.read_text()
            target = "XP0 F0 N0 N1 VDD"
            assert original.count(target) == 1
            source.write_text(original.replace(target, "XP0 F0 N0 VDD VDD"))
        voltage = corner[3]
        load1 = load if load1 is None else load1
        deck = header(models, source, corner)
        wave = folder / "wave.tsv"
        if kind == "filter":
            deck += f'''VN0 n0 0 {voltage * common}
VN1 n1 0 {voltage * (common + difference)}
XF n0 n1 f0 f1 vdd 0 ca_mutex_filter
XCLEAR0 g0 clear0 vdd 0 ca_mutex_clear
XCLEAR1 g1 clear1 vdd 0 ca_mutex_clear
XOUT0 f0 clear1 b0 g0 vdd 0 ca_mutex_output
XOUT1 f1 clear0 b1 g1 vdd 0 ca_mutex_output
CG0 g0 0 {load}p
CG1 g1 0 {load1}p
.control
set wr_singlescale
set wr_vecnames
op
wrdata {wave.as_posix()} v(n0) v(n1) v(f0) v(f1) v(g0) v(g1)
quit
.endc
.end
'''
        else:
            if kind == "contention":
                r0 = [(0, 0), (20, 0), (20 + slew0, voltage)]
                r1 = [(0, 0), (20 + skew, 0), (20 + skew + slew1, voltage)]
                reset = [(0, voltage), (10, voltage), (10 + slew0, 0)]
                finish = 60
            else:
                r0 = [(0, 0), (20, 0), (20 + slew0, voltage), (70, voltage), (70 + slew0, 0)]
                r1 = [(0, 0), (40, 0), (40 + slew1, voltage), (100, voltage), (100 + slew1, 0),
                      (160, 0), (160 + slew1, voltage), (190, voltage), (190 + slew1, 0)]
                reset = [(0, voltage), (10, voltage), (10 + slew0, 0), (125, 0),
                         (125 + slew0, voltage), (145, voltage), (145 + slew0, 0)]
                finish = 230
            deck += f'''VR0 r0 0 {pwl(r0)}
VR1 r1 0 {pwl(r1)}
VRESET reset 0 {pwl(reset)}
XD reset r0 r1 g0 g1 vdd 0 ca_mutex_gf180_candidate
CG0 g0 0 {load}p
CG1 g1 0 {load1}p
.control
set wr_singlescale
set wr_vecnames
tran {min(slew0, slew1, .2)/20}n {finish}n
wrdata {wave.as_posix()} v(r0) v(r1) v(reset) v(g0) v(g1) v(xd.n0) v(xd.n1) v(xd.f0) v(xd.f1)
quit
.endc
.end
'''
        deck_path = folder / "probe.spice"
        deck_path.write_text(deck)
        command = [str(executable), "-n", "-b", str(deck_path)]
        entry = dict(kind=kind, corner=corner[0], load0_pf=load, load1_pf=load1, slew0_ns=slew0, slew1_ns=slew1,
                     skew_ns=skew, common_vdd=common, difference_vdd=difference, mutant=mutant,
                     command=command, deck_sha256=sha(deck_path), circuit_sha256=sha(source))
        try:
            result = subprocess.run(command, cwd=models, text=True, capture_output=True, timeout=args.timeout)
            log = result.stdout + result.stderr
            entry["returncode"] = result.returncode
            if result.returncode or not wave.exists():
                raise ValueError("MUTEX_SPICE_EXECUTION_FAILED: " + log[-1000:])
            names, rows = data(wave)
            entry.update(wave_sha256=sha(wave), samples=len(rows), columns=names)
            if kind == "filter":
                if names != FILTER_COLUMNS or len(rows) != 1:
                    raise ValueError("MUTEX_FILTER_WAVE_COLUMNS_OR_COUNT")
                # time/scale plus the six declared voltage columns.
                values = rows[-1]
                errors = [] if max(values[5:7]) <= .3 * voltage else ["MUTEX_FILTER_LEAKED_UNRESOLVED"]
                entry.update(errors=errors, filtered_voltages=values[3:5], grant_voltages=values[5:7])
            else:
                validate_transient(names, rows, finish, min(slew0, slew1, .2)/20)
                entry.update(analyze_transient(rows, voltage, kind))
            entry["passed"] = entry["errors"] == (["MUTEX_FILTER_LEAKED_UNRESOLVED"] if mutant else [])
        except subprocess.TimeoutExpired as error:
            log = str(error)
            entry.update(passed=False, errors=["MUTEX_SPICE_TIMEOUT"])
        except Exception as error:
            log = locals().get("log", "") + "\n" + str(error)
            entry.update(passed=False, errors=[str(error)])
        (folder / "simulation.log").write_text(log)
        entry["log_sha256"] = sha(folder / "simulation.log")
        report["cases"].append(entry)
        report_path.write_text(json.dumps(report, indent=2) + "\n")

    for corner in CORNERS:
        for load, load1 in ((.005, .005), (.05, .05), (.05, .005), (.005, .05)):
            for slew0, slew1 in ((.05, .05), (.05, 5), (5, .05)):
                run_case("sequence", corner, load, slew0, slew1, load1=load1)
                for skew in (-1, -.001, 0, .001, 1):
                    run_case("contention", corner, load, slew0, slew1, skew, load1=load1)
        for load in (.005, .05):
            for common in (.4, .5, .6):
                for difference in (-.01, 0, .01):
                    run_case("filter", corner, load, common=common, difference=difference)
        run_case("filter", corner, .005, common=.4, mutant=True)
        print(f"{corner[0]}: {len(report['cases'])} cases recorded", flush=True)
    unchanged = all(sha(path) == digest for path, digest in report["inputs_sha256"].items())
    success = unchanged and all(case["passed"] for case in report["cases"])
    report.update(status="SCHEMATIC_SAMPLES_PASS_UNQUALIFIED" if success else "SCHEMATIC_SAMPLES_FAIL_UNQUALIFIED",
                  inputs_unchanged=unchanged,
                  positives=sum(not c["mutant"] for c in report["cases"]),
                  negative_controls=sum(c["mutant"] for c in report["cases"]))
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(report["status"], flush=True)
    raise SystemExit(0 if success else 1)


if __name__ == "__main__":
    main()
