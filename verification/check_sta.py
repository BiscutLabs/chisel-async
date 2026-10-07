# SPDX-License-Identifier: Apache-2.0
"""Exercise the shipped OpenSTA checker using known paths and deliberate violations.

Requires a caller-installed OpenSTA. No PDK, synthesis tool or Python packages.
Every negative control must fail with its exact diagnostic, not a tool error.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
CASES = {
    "buffer": ('ca_measure buffer [list -from [ca_exact port {a[0]}] -to [ca_exact port {z[0]}]] 0.99 1.01', None),
    "bus": ('ca_measure bus [list -from [get_ports a*] -to [get_ports z*]] 0.99 1.01', None),
    "pin": ('ca_measure pin [list -from [ca_exact pin early_path/A] -to [ca_exact pin early_path/Z]] 0.99 1.01', None),
    "arc": ('ca_arc arc [get_pins early_path/A] [get_pins early_path/Z] 0.99 1.01', None),
    "arc_min": ('ca_arc arc [get_pins early_path/A] [get_pins early_path/Z] 1.1 3', "TIMING_MIN_VIOLATION"),
    "arc_max": ('ca_arc arc [get_pins early_path/A] [get_pins early_path/Z] 0 0.9', "TIMING_MAX_VIOLATION"),
    "arc_missing": ('ca_arc arc [get_pins early_path/A] [get_pins late_second/Z] 0 3', "TIMING_ARC_UNRESOLVED"),
    "order": ('''set early [ca_measure early [list -rise_from [ca_exact port {a[0]}] -rise_to [ca_exact port {z[0]}]] 0 3]
set late [ca_measure late [list -rise_from [ca_exact port {a[0]}] -fall_to [ca_exact port late]] 0 3]
ca_order fork $early $late 0.1''', None),
    "min": ('ca_measure min [list -from [get_ports {a[0]}] -to [get_ports {z[0]}]] 1.1 3', "TIMING_MIN_VIOLATION"),
    "max": ('ca_measure max [list -from [get_ports {a[0]}] -to [get_ports {z[0]}]] 0 0.9', "TIMING_MAX_VIOLATION"),
    "equality": ('ca_order fork {1 1} {1 1} 0', "TIMING_ORDER_VIOLATION"),
    "margin": ('ca_order closure {1 1} {2 2} 1', "TIMING_ORDER_VIOLATION"),
    "reversed": ('ca_order fork {2 2} {1 1} 0', "TIMING_ORDER_VIOLATION"),
    "missing_pin": ('ca_exact pin absent/A', "TIMING_ENDPOINT_UNRESOLVED"),
    "wildcard": ('ca_exact port {a[*]}', "TIMING_ENDPOINT_UNRESOLVED"),
    "missing_bit": ('ca_exact port {a[2]}', "TIMING_ENDPOINT_UNRESOLVED"),
    "no_path": ('ca_measure disconnected [list -from [get_ports {a[0]}] -to [get_ports disconnected]] 0 10', "TIMING_SOURCE_UNCOVERED"),
    "partial_bus": ('ca_measure partial [list -from [get_ports {a[0]}] -to [get_ports z*]] 0 10', "TIMING_SINK_UNCOVERED"),
    "missing_source": ('ca_measure partial [list -from [get_ports a*] -to [get_ports {z[0]}]] 0 10', "TIMING_SOURCE_UNCOVERED"),
}


def run(executable, output):
    output.mkdir(parents=True, exist_ok=False)
    result = {"status": "RUNNING", "cases": [], "files_sha256": {}}
    report = output / "report.json"
    def save():
        report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    files = [ROOT / "verification/sta/fixture.lib", ROOT / "verification/sta/fixture.v",
             ROOT / "src/main/resources/chiselasync/timing-endpoints.tcl",
             ROOT / "src/main/resources/chiselasync/timing-checks.tcl"]
    result["files_sha256"] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    save()
    try:
        for name, (body, expected) in CASES.items():
            commands = [f'read_liberty {{{files[0].as_posix()}}}', f'read_verilog {{{files[1].as_posix()}}}',
                        'link_design -no_black_boxes Checker', f'source {{{files[2].as_posix()}}}',
                        f'source {{{files[3].as_posix()}}}', body, 'puts CA_CHECKER_CASE_PASS']
            script = output / f"{name}.tcl"
            script.write_text('if {[catch {\n' + '\n'.join(commands) +
                              '\n} message]} {puts stderr "CA_CHECKER_FAILURE: $message"; exit 1}\nexit 0\n', encoding="utf-8")
            proc = subprocess.run([executable, '-exit', str(script.resolve())], capture_output=True, text=True, timeout=60)
            text = proc.stdout + proc.stderr
            (output / f"{name}.log").write_text(text, encoding="utf-8")
            errors = re.findall(r'^CA_CHECKER_FAILURE: ([A-Z_]+)', text, re.M)
            passed = (proc.returncode == 0 and text.count('CA_CHECKER_CASE_PASS') == 1 and not errors) if expected is None else (
                proc.returncode != 0 and errors == [expected] and 'CA_CHECKER_CASE_PASS' not in text)
            result["cases"].append(dict(name=name, expected=expected, matched=passed))
            save()
            if not passed:
                raise RuntimeError(f"STA checker regression {name}: {text}")
        result["status"] = "PASS"
    except BaseException as error:
        result.update(status="ERROR", error=str(error))
        raise
    finally:
        save()
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sta', default='sta')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.sta, args.output.resolve())
    print(f"PASS: {len(result['cases'])} OpenSTA checker cases")
