# SPDX-License-Identifier: Apache-2.0
"""Test actual emitted long-hold stages under bounded delays and full data hold."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import re
import subprocess
import sys

from compare_controllers import ROOT, VIOLATIONS, classify, random_words, sha
from run import read_sources
from check_export import validate_export
from longhold_reference import explore, verify_trace
from longhold_topology import check_topology
from longhold_primitives import check_primitives
from longhold_payloads import check_payloads

VIOLATIONS.add("CAPACITY_PENDING_OFFER")
CELLS = ("data_delay", "long_hold", "a", "b", "acknowledge", "payload")


def execute(sources, directory, depth, delays, environment, fault=None, waves=False):
    directory.mkdir(parents=True, exist_ok=True)
    overrides = []
    for stage in range(depth):
        for name, delay in delays[stage].items():
            overrides.append(f"  defparam stages[{stage}].published.dut.ca_primitive_{name}.DELAY_FS={delay*1000000};")
    bench = (ROOT / "verification/controllers/bench.sv").read_text(encoding="utf-8")
    bench = bench.replace("endmodule", "\n".join(overrides) + "\nendmodule")
    bench_path = directory / "bench.sv"
    bench_path.write_text(bench, encoding="utf-8")
    executable = directory / "bench.vvp"
    command = ["iverilog", "-g2012", "-s", "ControllerBench", "-PControllerBench.LONGHOLD=1",
               "-PControllerBench.MULLER=0", f"-PControllerBench.DEPTH={depth}",
               "-o", str(executable), *map(str, sources), str(bench_path)]
    compiled = subprocess.run(command, capture_output=True, text=True, timeout=30)
    (directory / "compile.log").write_text(compiled.stdout + compiled.stderr, encoding="utf-8")
    if compiled.returncode:
        raise RuntimeError(f"Compilation failure: {directory}")
    simulated_command = ["vvp", str(executable), *[f"+{k}={v}" for k, v in environment.items()]]
    if waves:
        simulated_command.append("+waves")
    (directory / "case.json").write_text(json.dumps({"depth": depth, "delays_ns": delays,
        "environment_ns": environment, "fault": fault, "compile": command, "simulate": simulated_command,
        "bench_sha256": sha(bench_path)}, indent=2), encoding="utf-8")
    simulated = subprocess.run(simulated_command, cwd=directory, capture_output=True, text=True, timeout=20)
    log = simulated.stdout + simulated.stderr
    (directory / "simulation.log").write_text(log, encoding="utf-8")
    result = {"case": directory.name, **classify(simulated.returncode, log)}
    if result["status"] == "PASS":
        result["stg_events"] = verify_trace(log, depth)
    return result


def case_configuration(seed, depth, uniform=None):
    rng = random_words(seed)
    environment = {key: 1+next(rng)%60 for key in ("source_pause", "sink_pause", "source_return", "sink_return")}
    delays = [{name: uniform if uniform is not None else 1+next(rng)%10 for name in CELLS} for _ in range(depth)]
    return delays, environment


def check_case_bounds(policy, delays):
    bounds = {**policy["control_delays"], "data_delay": policy["data_delay"], "payload": policy["latch_delay"]}
    for stage in delays:
        if set(stage) != set(bounds):
            raise ValueError("DELAY_ROLE_INVENTORY")
        for name, value in stage.items():
            if not int(bounds[name]["min_fs"]) <= value*1000000 <= int(bounds[name]["max_fs"]):
                raise ValueError("DELAY_OUTSIDE_DECLARED_BOUNDS")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=300)
    parser.add_argument("--seed-start", type=int, default=0)
    parser.add_argument("--depths", type=int, nargs="+", default=[1, 3])
    parser.add_argument("--generated", type=Path, default=ROOT / "target/generated")
    parser.add_argument("--output", type=Path, default=ROOT / "target/verification/longhold")
    args = parser.parse_args()
    if not 1 <= args.seeds <= 10000:
        parser.error("invalid seed count")
    if not 0 <= args.seed_start < 2**32 - args.seeds:
        parser.error("invalid seed start")
    if len(set(args.depths)) != len(args.depths) or any(not 1 <= depth <= 8 for depth in args.depths):
        parser.error("depths must be unique values between 1 and 8")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = output / "report.json"
    evidence = {"status": "RUNNING", "random_seeds": args.seeds, "seed_start": args.seed_start,
                "depths": args.depths, "cases": [], "controls": []}
    def save():
        report.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    save()
    try:
        generated = args.generated.resolve() / "longhold_comparison"
        evidence["original_export"] = validate_export(generated)
        policy = json.loads((generated / "contract.json").read_text())["manifest"]["design"]["timing"][0]
        evidence["declared_policy"] = policy
        version = subprocess.run(["iverilog", "-V"], capture_output=True, text=True, check=True).stdout.splitlines()[0]
        evidence.update(platform=platform.platform(), python=sys.version, simulator=version)
        evidence["stg_reachability"] = explore()
        evidence["topology"] = check_topology((generated / "LongHoldComparisonExample.sv").read_text(encoding="utf-8"))
        sources = read_sources(generated)
        evidence["source_sha256"] = {p.name: sha(p) for p in [*sources, Path(__file__),
            ROOT / "verification/longhold_reference.py", ROOT / "verification/longhold_topology.py",
            ROOT / "verification/longhold_primitives.py",
            ROOT / "verification/longhold_payloads.py",
            ROOT / "verification/controllers/bench.sv"]}
        build = output / "sources"
        build.mkdir(exist_ok=True)
        snapshots = []
        for path in sources:
            target = build / path.name
            target.write_bytes(path.read_bytes())
            snapshots.append(target)
        sources = snapshots
        evidence["primitives"] = check_primitives(sources, output / "primitives")
        evidence["typed_payloads"] = check_payloads(args.generated.resolve(), output / "typed_payloads")
        for depth in args.depths:
            cases = [(f"depth{depth}_uniform_{d}", *case_configuration(0, depth, d)) for d in (1, 10)]
            cases += [(f"depth{depth}_seed_{seed:03}", *case_configuration(seed, depth))
                      for seed in range(args.seed_start, args.seed_start + args.seeds)]
            # Each role slow against fast surroundings, then fast against slow.
            for slow in (False, True):
                for role in CELLS:
                    delays, env = case_configuration(0, depth, 10 if slow else 1)
                    for stage in delays:
                        stage[role] = 1 if slow else 10
                    cases.append((f"depth{depth}_corner_{int(slow)}_{role}", delays, env))
            for name, delays, environment in cases:
                check_case_bounds(policy, delays)
                result = execute(sources, output / name, depth, delays, environment, waves="uniform_10" in name)
                evidence["cases"].append(result)
                if result["status"] != "PASS":
                    execute(sources, output / (name + "_trace"), depth, delays, environment, waves=True)
                    raise RuntimeError(f"Required long-hold case failed: {result}")
            print(f"Long-hold depth {depth}: {len(cases)} PASS", flush=True)
            save()
        # Remove matched admission delay while data still takes 10 ns: old data is captured.
        delays, env = case_configuration(0, 1, 1)
        delays[0].update(request_delay=0, data_delay=10)
        result = execute(sources, output / "missing_match", 1, delays, env, fault="request delay removed", waves=True)
        evidence["controls"].append(result)
        if result.get("all_diagnostics") != ["PAYLOAD_MISMATCH"]:
            raise RuntimeError(f"Matched-delay fault did not activate intended checker: {result}")
        # Delete downstream-ack feedback only from the long-hold OR (actual emitted RTL).
        original = build / "LongHoldComparisonExample.sv"
        mutated, count = re.subn(r"(ca_primitive_long_hold\s*\(.*?\.b\s*\()out_ack(?:_0)?(\))", r"\g<1>1'b0\2",
                                original.read_text(encoding="utf-8"), flags=re.S)
        if count != 1:
            raise RuntimeError("Long-hold feedback mutation target changed")
        mutant = build / "early_release.sv"
        mutant.write_text(mutated, encoding="utf-8")
        delays, env = case_configuration(0, 1, 1)
        env["sink_return"] = 60
        result = execute([mutant if p == original else p for p in sources], output / "early_release", 1,
                         delays, env, fault="long-hold OR feedback removed", waves=True)
        evidence["controls"].append(result)
        if result.get("all_diagnostics") != ["DATA_HOLD"]:
            raise RuntimeError(f"Long-hold fault did not activate intended checker: {result}")
        evidence["mutation_sha256"] = sha(mutant)
        # A separate delay on an inverted input is NOT the published atomic cell.
        split, count = re.subn(r"(ca_primitive_a\s*\(.*?\.falling\s*\()out_ack(?:_0)?(\))", r"\g<1>late_ack\2",
                              original.read_text(encoding="utf-8"), flags=re.S)
        if count != 1:
            raise RuntimeError("Split input-bubble mutation target changed")
        split = split.replace("  wire", "  wire #10000000 late_ack = out_ack;\n  wire", 1)
        split_path = build / "split_bubble.sv"
        split_path.write_text("`timescale 1fs/1fs\n" + split, encoding="utf-8")
        delays, env = case_configuration(0, 1, 1)
        result = execute([split_path if p == original else p for p in sources], output / "split_bubble", 1,
                         delays, env, fault="unacknowledged 10 ns delay on Aout input", waves=True)
        evidence["controls"].append(result)
        if result.get("all_diagnostics") != ["CAPACITY_EXCEEDED"]:
            raise RuntimeError(f"Split-bubble fault did not activate intended checker: {result}")
        evidence["split_bubble_sha256"] = sha(split_path)
        evidence["status"] = "PASS"
    except BaseException as error:
        evidence.update(status="ERROR", error=str(error))
        save()
        raise
    save()
    print(f"Long-hold evidence: {report}")


if __name__ == "__main__":
    main()
