# SPDX-License-Identifier: Apache-2.0
"""Persistent-request contract checks; finite digital evidence, not qualification."""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIAGNOSTICS = {
    1: "MUTEX_REQUEST_WITHDRAWN_BEFORE_SERVICE",
    2: "MUTEX_GRANT_NOT_RELEASED_BEFORE_REUSE",
    3: "MUTEX_STALE_REQUEST_AT_REARM",
    4: "MUTEX_RESET_WITHOUT_QUIESCENCE",
    5: "MUTEX_GRANT_EXCLUSION",
    6: "MUTEX_HELD_GRANT_REVOKED",
    7: "MUTEX_MISSING_ZERO_HANDOVER",
    8: "MUTEX_GRANT_WITHOUT_REQUEST",
    9: "MUTEX_RESET_DID_NOT_CLEAR",
    10: "MUTEX_WINNER_NOT_RETAINED",
    11: "MUTEX_MODEL_RESOLUTION_DELAY_VIOLATED",
}


def fault_kind(fault):
    if fault == 0:
        return "none"
    if fault == 10:
        return "sampled_reference_corruption"
    if fault in range(1, 5):
        return "owner_protocol_fault"
    if fault in DIAGNOSTICS:
        return "injected_output_fault"
    raise ValueError(f"MUTEX_UNKNOWN_FAULT: {fault}")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def accepts_log(returncode, log, expected=None, line=None):
    if re.search(r"^\s*ERROR:", log, re.M):
        return False
    if expected is None:
        return returncode == 0 and log.count("MUTEX_CONTRACT_PASS ") == 1 and not re.search(r"^\s*FATAL:", log, re.M)
    pattern = rf"^FATAL: .*mutex_contract\.sv:{line}: {expected}\r?$"
    return returncode != 0 and len(re.findall(r"^\s*FATAL:", log, re.M)) == 1 and \
        len(re.findall(pattern, log, re.M)) == 1 and "MUTEX_CONTRACT_PASS" not in log


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "target/verification/mutex-contract")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "RUNNING", "physical_qualification": False, "cases": []}
    report_path = output / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    source = ROOT / "src/main/resources/chiselasync/sv/ChiselAsyncMutex_v1.sv"
    bench = ROOT / "verification/mutex_contract.sv"
    compiler, simulator = (Path(shutil.which(name) or name).resolve() for name in ("iverilog", "vvp"))
    report["input_sha256"] = {str(p): sha(p) for p in (source, bench, Path(__file__), compiler, simulator)}
    report["simulator"] = subprocess.run([str(compiler), "-V"], capture_output=True,
        text=True, check=True, timeout=30).stdout.splitlines()[0]
    positives = [(p, 1, 100, 0, None) for p in range(4)]
    positives += [(3, seed, 100, 0, None) for seed in (2, 19, 0xffffffff)]
    positives += [(p, 19, 1000000, 0, None) for p in range(4)]
    negatives = [(p, 19, 100, fault, diagnostic) for p in range(4)
                 for fault, diagnostic in DIAGNOSTICS.items()]
    try:
        for index, (policy, seed, resolution, fault, expected) in enumerate(positives + negatives):
            case = output / f"case-{index:02d}-policy{policy}-fault{fault}"
            case.mkdir()
            binary = case / "sim.vvp"
            command = [str(compiler), "-g2012", "-s", "MutexContract", "-o", str(binary),
                f"-PMutexContract.POLICY={policy}", f"-PMutexContract.SEED={seed}",
                f"-PMutexContract.RESOLUTION={resolution}", f"-PMutexContract.FAULT={fault}",
                str(bench), str(source)]
            compiled = subprocess.run(command, text=True, capture_output=True, timeout=30)
            (case / "compile.log").write_text(compiled.stdout + compiled.stderr)
            if compiled.returncode:
                raise AssertionError(f"MUTEX_COMPILE_FAILED {case.name}")
            binary_before = sha(binary)
            result = subprocess.run([str(simulator), str(binary)], text=True, capture_output=True, timeout=30)
            log = result.stdout + result.stderr
            (case / "simulation.log").write_text(log)
            if expected is None:
                if not accepts_log(result.returncode, log):
                    raise AssertionError(f"MUTEX_POSITIVE_FAILED {case.name}: {log}")
            else:
                # Require the actual assertion at its source line, not a timeout,
                # compiler failure or a loose substring in unrelated diagnostics.
                line = next(i for i, text in enumerate(bench.read_text().splitlines(), 1)
                            if f'$fatal(1,"{expected}")' in text)
                if not accepts_log(result.returncode, log, expected, line):
                    raise AssertionError(f"MUTEX_WRONG_NEGATIVE {case.name}: {log}")
            if sha(binary) != binary_before:
                raise AssertionError("MUTEX_SIMULATION_BINARY_CHANGED")
            report["cases"].append({"policy": policy, "seed": seed, "resolution_fs": resolution,
                "fault": fault, "fault_kind": fault_kind(fault), "expected": expected,
                "command": command, "returncode": result.returncode,
                "binary_sha256": sha(binary), "log_sha256": sha(case / "simulation.log")})
        report["inputs_unchanged"] = all(sha(path) == digest for path, digest in report["input_sha256"].items())
        if not report["inputs_unchanged"]:
            raise AssertionError("MUTEX_CAMPAIGN_INPUT_CHANGED")
        report.update(status="PASS_DIGITAL_CONTRACT", positives=len(positives), negatives=len(negatives))
    except Exception as error:
        report.update(status="FAIL", error=str(error))
        raise
    finally:
        report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(f"PASS: {len(positives)} digital contract cases, {len(negatives)} exact-diagnostic controls")


if __name__ == "__main__":
    main()
