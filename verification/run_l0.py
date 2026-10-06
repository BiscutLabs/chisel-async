# SPDX-License-Identifier: Apache-2.0
"""Run the full regression and a prospectively frozen L0 acceptance campaign."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from qualify import run_steps

SPEC = {"depths": [1, 2, 3, 4], "seed_start": 10000, "seeds": 64,
        "uniform_ns": [1, 10], "roles": ["data_delay", "long_hold", "a", "b", "acknowledge", "payload"],
        "faults": {"missing_match": "PAYLOAD_MISMATCH", "early_release": "DATA_HOLD",
                   "split_bubble": "CAPACITY_EXCEEDED"}}
BASELINE = ["build", "export", "python", "functional", "counterexample", "comparison", "timing",
            "longhold", "architecture", "optimized", "chiselsim", "consumer"]
DEFAULT = ROOT / "qualification/l0-candidate-1.json"


def digest(path):
    # Git's CRLF checkout policy must not change the cross-host source identity.
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def source_inventory(root=ROOT):
    names = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                           cwd=root, capture_output=True, check=True).stdout.decode("utf-8").split("\0")
    prefixes = ("src/", "examples/", "verification/", "tools/", "project/", ".github/")
    return {name: digest(root / name) for name in sorted(set(names))
            if name and (name.startswith(prefixes) or name == "build.sbt")}


def check_candidate(candidate, actual):
    if candidate.get("schema") != 1 or candidate.get("campaign") != SPEC or candidate.get("baseline") != BASELINE:
        raise RuntimeError("L0_CANDIDATE_CONTRACT")
    if not actual or candidate.get("sources") != actual:
        expected = candidate.get("sources", {})
        drift = sorted(k for k in set(actual) | set(expected) if actual.get(k) != expected.get(k))
        raise RuntimeError("L0_SOURCE_DRIFT: " + ", ".join(drift))


def expected_cases():
    names = []
    for depth in SPEC["depths"]:
        names += [f"depth{depth}_uniform_{value}" for value in SPEC["uniform_ns"]]
        names += [f"depth{depth}_seed_{seed:03}" for seed in range(SPEC["seed_start"], SPEC["seed_start"] + SPEC["seeds"])]
        names += [f"depth{depth}_corner_{polarity}_{role}" for polarity in (0, 1) for role in SPEC["roles"]]
    return names


def check_reports(baseline, campaign):
    steps = baseline.get("steps", [])
    names = [step.get("name") for step in steps]
    if (baseline.get("status") != "PASS" or baseline.get("required") != names
            or len(set(names)) != len(names) or names[-len(BASELINE):] != BASELINE
            or any(step.get("exit_code") != 0 for step in steps)):
        raise RuntimeError("L0_BASELINE_INCOMPLETE")
    cases, controls = campaign.get("cases", []), campaign.get("controls", [])
    if (campaign.get("status") != "PASS" or campaign.get("depths") != SPEC["depths"]
            or campaign.get("seed_start") != SPEC["seed_start"] or campaign.get("random_seeds") != SPEC["seeds"]
            or [case.get("case") for case in cases] != expected_cases()
            or any(case.get("status") != "PASS" or case.get("stg_events", 0) <= 0 for case in cases)):
        raise RuntimeError("L0_CAMPAIGN_INCOMPLETE")
    if ([control.get("case") for control in controls] != list(SPEC["faults"])
            or any(control.get("status") != "VIOLATION"
                   or control.get("all_diagnostics") != [SPEC["faults"][control["case"]]] for control in controls)):
        raise RuntimeError("L0_FAULT_CONTROL")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, default=DEFAULT)
    parser.add_argument("--freeze", action="store_true", help="Create a NEW candidate before acceptance; never overwrite")
    args = parser.parse_args()
    if args.freeze:
        candidate = {"schema": 1, "campaign": SPEC, "baseline": BASELINE, "sources": source_inventory()}
        args.candidate.parent.mkdir(parents=True, exist_ok=True)
        with args.candidate.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(candidate, indent=2) + "\n")
        print(f"Frozen (not executed): {args.candidate}")
        return
    parent = ROOT / "target/verification/l0"
    parent.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-"), dir=parent))
    report = {"status": "RUNNING", "review": "separate required decision", "candidate": args.candidate.name}
    def save():
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    save()
    try:
        candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
        candidate_hash = digest(args.candidate)
        check_candidate(candidate, source_inventory())
        report.update(candidate_sha256=candidate_hash, revision=subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip())
        environment = dict(os.environ)
        bins = [ROOT / ".tools/iverilog/bin", ROOT / ".tools/verilator/bin"]
        if os.name == "nt":
            bins.append(Path("C:/msys64/ucrt64/bin"))
        environment["PATH"] = os.pathsep.join(map(str, bins)) + os.pathsep + environment.get("PATH", "")
        python = ROOT / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")
        # Baseline setup creates the venv on a cold host before this command runs.
        command = [str(python), str(ROOT / "verification/run_longhold.py"), "--seed-start", str(SPEC["seed_start"]),
                   "--seeds", str(SPEC["seeds"]), "--depths", *map(str, SPEC["depths"]), "--output", str(output / "campaign")]
        report["execution"] = run_steps([
            ("baseline", [sys.executable, str(ROOT / "tools/qualify.py")]),
            ("frozen_campaign", command)], environment, output / "steps")
        baseline_path = ROOT / "target/verification/qualification/report.json"
        campaign_path = output / "campaign/report.json"
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
        check_reports(baseline, campaign)
        check_candidate(candidate, source_inventory())
        if digest(args.candidate) != candidate_hash:
            raise RuntimeError("L0_CANDIDATE_CHANGED_DURING_RUN")
        report.update(status="PASS", baseline=baseline, campaign_sha256=digest(campaign_path),
                      positive_cases=len(campaign["cases"]), fault_controls=len(campaign["controls"]))
    except BaseException as error:
        report.update(status="ERROR", error=str(error))
        save()
        raise
    save()
    print(f"L0 acceptance PASS (review decision separate): {output / 'report.json'}")


if __name__ == "__main__":
    main()
