# SPDX-License-Identifier: Apache-2.0
"""Prospective L1 acceptance. A PASS is evidence, not the separate review decision."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = ROOT / "verification/l1-plan-2.json"
DEFAULT_CANDIDATE = ROOT / "qualification/l1-candidate-2.json"
INPUT_PREFIXES = ("src/", "examples/", "verification/", "tools/", "project/")
ADDITIONS = {"verification/l1_acceptance.py", "verification/test_l1_acceptance.py",
             "verification/l1-plan.json", "verification/l1-plan-2.json"}


def require(condition, diagnostic):
    if not condition:
        raise RuntimeError(diagnostic)


def sha(path, normalized=False):
    data = Path(path).read_bytes()
    return hashlib.sha256(data.replace(b"\r\n", b"\n") if normalized else data).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def check_plan(plan):
    seeds = plan.get("seeds", [])
    require(plan.get("schema") == "chisel-async-l1-plan-v1" and isinstance(seeds, list)
            and len(seeds) == 4 and all(type(seed) is int and 0 < seed < 2**32 for seed in seeds)
            and len(set(seeds)) == 4 and {seed % 2 for seed in seeds} == {0, 1}, "L1_PLAN_CONTRACT")
    require(set(seeds).isdisjoint(plan.get("supersession", {}).get("used_seeds", [])), "L1_PLAN_REUSED_SEED")


def git(*args, root=ROOT):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True).stdout


def source_inventory(root=ROOT, acceptance=False):
    names = git("ls-files", "--cached", "--others", "--exclude-standard", "-z", root=root).decode().split("\0")
    return {n: sha(root / n, True) for n in sorted(set(names))
            if n and (n.startswith(INPUT_PREFIXES + ((".github/",) if acceptance else ())) or n == "build.sbt")
            and (acceptance or n not in ADDITIONS)}


def check_sources(plan, root=ROOT):
    actual = source_inventory(root, acceptance=plan.get("schema") == "chisel-async-l1-candidate-v1")
    expected = plan["sources"]
    drift = sorted(k for k in set(actual) | set(expected) if actual.get(k) != expected.get(k))
    require(bool(expected) and not drift, "L1_SOURCE_DRIFT: " + ", ".join(drift))


def check_committed(names, root=ROOT):
    # Acceptance machinery, including the plan, must precede execution in Git.
    for name in sorted(names):
        committed = git("show", "HEAD:" + name, root=root).replace(b"\r\n", b"\n")
        require(committed == (root / name).read_bytes().replace(b"\r\n", b"\n"), "L1_UNCOMMITTED_INPUT: " + name)


def inventory(rows, expected, keys, diagnostic):
    actual = [tuple(row.get(k) for k in keys) for row in rows]
    require(len(actual) == len(set(actual)) and set(actual) == set(map(tuple, expected)), diagnostic)


def artifact_hashes(row, directory):
    for key, filename in (("bench_sha256", "bench.sv"), ("trace_sha256", "trace.txt"),
                          ("log_sha256", "simulation.log"), ("xml_sha256", "results.xml")):
        if key in row:
            if key == "trace_sha256" and (directory / "trace.jsonl").exists():
                filename = "trace.jsonl"
            require(sha(directory / filename) == row[key], "L1_ARTIFACT_HASH: " + str(directory / filename))
    for name, expected in row.get("sources", {}).items():
        path = directory / name
        if not path.exists():
            path = directory / "build" / name
        require(sha(path) == expected, "L1_SOURCE_ARTIFACT_HASH: " + str(path))


def exact_fatal(log, diagnostic):
    require(re.findall(r"^FATAL: [^\n]*?: (\w+)", log, re.M) == [diagnostic], "L1_WRONG_DIAGNOSTIC")


def rejection(operation, diagnostic):
    try:
        operation()
    except AssertionError as error:
        require(str(error) == diagnostic, "L1_WRONG_DIAGNOSTIC: " + str(error))
    else:
        raise RuntimeError("L1_CONTROL_ESCAPED")


def audit_composition(plan, output, generated):
    from composition_reference import replay
    from run_composition import port_roles
    report = read(output / "report.json")
    spec = plan["composition"]
    expected = [(f, seed, "normal") for f in spec["fixtures"] for seed in plan["seeds"]]
    expected += [(f, None, name) for name, (f, _) in spec["faults"].items()]
    require(report["status"] == "PASS", "L1_COMPOSITION_STATUS")
    inventory(report["cases"], expected, ("fixture", "seed", "scenario"), "L1_COMPOSITION_INVENTORY")
    deliveries = 0
    for row in report["cases"]:
        f, scenario = row["fixture"], row["scenario"]
        directory = output / f'{f}_{row.get("seed", 0)}_{scenario}'
        require(read(directory / "case.json") == {k: v for k, v in row.items() if k != "command"}, "L1_CASE_SUMMARY")
        artifact_hashes(row, directory)
        tests = list(ET.parse(directory / "results.xml").iter("testcase"))
        require(len(tests) == 1 and tests[0].get("name") == "composition_contract" and not tests[0].findall("skipped"), "L1_XML_INVENTORY")
        events = [json.loads(line) for line in (directory / "trace.jsonl").read_text().splitlines()]
        replay_case = lambda: replay(f, port_roles(generated / f), events)
        if scenario == "normal":
            require(row["status"] == "PASS" and not tests[0].findall("failure") and not tests[0].findall("error"), "L1_XML_FAILURE")
            summary = replay_case()
            require(all(row["evidence"][k] == v for k, v in summary.items()), "L1_REPLAY_SUMMARY")
            require(summary["delivered"] == spec["deliveries"][f] and summary["resets"] == spec["resets"][f], "L1_COMPOSITION_ACTIVITY")
            require(sum(e["kind"] == "edge" for e in events) > 0, "L1_EMPTY_TRACE")
            deliveries += summary["delivered"]
        else:
            diagnostic = spec["faults"][scenario][1]
            require(row["status"] == "EXPECTED_REJECTION" and row["diagnostic"] == diagnostic
                    and (tests[0].findall("failure") or tests[0].findall("error")), "L1_CONTROL_STATUS")
            if diagnostic in ("EXCLUSIVE_MERGE_CONTENTION", "SELECT_INDEX_OUT_OF_RANGE"):
                exact_fatal((directory / "simulation.log").read_text(), diagnostic)
            else:
                rejection(replay_case, diagnostic)
    return {"positive_cases": len(spec["fixtures"]) * len(plan["seeds"]), "controls": len(spec["faults"]), "deliveries": deliveries}


def phase_total(plan, fixture, seed, scenario):
    total = plan["phase"]["base_deliveries"][fixture]
    if scenario.startswith("reset_"):
        return total + int(scenario in ("reset_partial_spacer", "reset_partial_fork", "reset_to_two_return"))
    return total + (plan["phase"]["warm_deliveries"].get(fixture, 1) if seed % 2 else 0)


def audit_phase(plan, output, generated):
    from phase_reference import replay
    from run_phase import trace_channels
    report = read(output / "report.json")
    spec = plan["phase"]
    require(report["status"] == "PASS", "L1_PHASE_STATUS")
    inventory(report["cases"], [(f, s, "standard") for f in spec["fixtures"] for s in plan["seeds"]],
              ("fixture", "seed", "scenario"), "L1_PHASE_INVENTORY")
    inventory(report["directed"], [(f, s, n) for n, f in spec["directed"].items() for s in (0, 2)],
              ("fixture", "seed", "scenario"), "L1_DIRECTED_INVENTORY")
    inventory(report["faults"], [(n, f, d) for n, (f, d) in spec["faults"].items()],
              ("name", "fixture", "diagnostic"), "L1_PHASE_CONTROL_INVENTORY")
    deliveries = 0
    channels = {f: trace_channels(read(generated / f / "contract.json")["manifest"]) for f in spec["fixtures"]}
    for row in report["cases"] + report["directed"]:
        f, s, scenario = row["fixture"], row["seed"], row["scenario"]
        directory = output / (f"{f}_{s}" if scenario == "standard" else f"directed/{scenario}_{s}")
        require(row["status"] == "PASS" and row == read(directory / "case.json"), "L1_CASE_SUMMARY")
        artifact_hashes(row, directory)
        log = (directory / "simulation.log").read_text()
        require(log.splitlines().count("PHASE_PASS") == 1 and "FATAL:" not in log, "L1_PHASE_LOG")
        if scenario.startswith("reset_"):
            require(log.splitlines().count("SCENARIO_REACHED:" + scenario) == 1, "L1_RESET_WITNESS")
        evidence = replay(f, channels[f], directory / "trace.txt", require_abort=scenario not in
                          ("reset_partial_valid", "reset_partial_spacer", "reset_to_two_return"))
        require(canonical(evidence) == canonical(row["evidence"]), "L1_REPLAY_SUMMARY")
        require(evidence["delivered"] == phase_total(plan, f, s, scenario) and evidence["epochs"] == 3, "L1_PHASE_ACTIVITY")
        deliveries += evidence["delivered"]
    for row in report["faults"]:
        require(row["status"] == "PASS" and len(row["outcomes"]) == 2, "L1_CONTROL_STATUS")
        diagnostic = spec["faults"][row["name"]][1]
        for mutant, outcome in zip((False, True), row["outcomes"]):
            directory = output / "faults" / row["name"] / ("fault" if mutant else "baseline")
            require(outcome == read(directory / "report.json"), "L1_CONTROL_SUMMARY")
            artifact_hashes(outcome, directory)
            operation = lambda: replay(row["fixture"], channels[row["fixture"]], directory / "trace.txt", complete=False)
            log = (directory / "simulation.log").read_text()
            require(outcome["status"] == ("EXPECTED_REJECTION" if mutant else "PASS") and
                    outcome["diagnostic"] == (diagnostic if mutant else None), "L1_CONTROL_STATUS")
            guard = diagnostic == "EXCLUSIVE_MERGE_CONTENTION" or diagnostic.startswith("DONE_")
            if mutant and guard:
                exact_fatal(log, diagnostic)
            else:
                require(log.splitlines().count("FAULT_PREFIX_COMPLETE") == 1 and "FATAL:" not in log, "L1_CONTROL_LOG")
                if mutant:
                    rejection(operation, diagnostic)
                else:
                    count = sum(operation().stats["deliveries"].values())
                    require(count > 0 and count == outcome["deliveries"], "L1_CONTROL_BASELINE_ACTIVITY")
    return {"positive_cases": len(report["cases"]), "directed_cases": len(report["directed"]),
            "controls": len(report["faults"]), "deliveries": deliveries}


def audit_reference(plan, output, generated):
    from run_reference import bench, replay
    report = read(output / "report.json")
    require(report["status"] == "PASS", "L1_REFERENCE_STATUS")
    inventory(report["cases"], [(f, s) for f in plan["reference_styles"] for s in plan["seeds"]],
              ("style", "seed"), "L1_REFERENCE_INVENTORY")
    inventory(report["faults"], [(f, plan["seeds"][0]) for f in plan["reference_styles"]],
              ("style", "seed"), "L1_REFERENCE_CONTROL_INVENTORY")
    for row in report["cases"] + report["faults"]:
        style, seed = row["style"], row["seed"]
        mutant = row in report["faults"]
        directory = output / (f"faults/{style}" if mutant else f"{style}_{seed}")
        require(row == read(directory / "case.json"), "L1_CASE_SUMMARY")
        artifact_hashes(row, directory)
        source = generated / ("reference_" + style)
        manifest, ports = read(source / "contract.json")["manifest"], read(source / "ports.json")["nodes"][0]["ports"]
        _, channels, words, _ = bench(style, manifest, ports, seed)
        operation = lambda: replay(directory / "trace.txt", channels, manifest["top"], words, style == "behavioral")
        if mutant:
            require(row["status"] == "EXPECTED_REJECTION" and row["evidence"] == {"diagnostic": "REFERENCE_SUM_MISMATCH"}, "L1_CONTROL_STATUS")
            rejection(operation, "REFERENCE_SUM_MISMATCH")
        else:
            evidence = operation()
            require(row["status"] == "PASS" and canonical(evidence) == canonical(row["evidence"]), "L1_REPLAY_SUMMARY")
            require(evidence["deliveries"] == {1: 96, 3: 96}, "L1_REFERENCE_ACTIVITY")
    return {"positive_cases": len(report["cases"]), "controls": len(report["faults"]), "deliveries": 192 * len(report["cases"])}


def compile_run(directory, top, bench, sources, parameters=(), traced=False):
    directory.mkdir(parents=True)
    path = directory / "bench.sv"
    path.write_text(bench, encoding="utf-8")
    copied = []
    for name, body in sources.items():
        dest = directory / name
        dest.write_text(body, encoding="utf-8")
        copied.append(dest)
    command = ["iverilog", "-g2012", *(["-DCHISEL_ASYNC_MUTEX_TRACE"] if traced else []), "-s", top,
               *[f"-P{top}.{key}={value}" for key, value in parameters], "-o", str(directory / "sim.vvp"), str(path), *map(str, copied)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    (directory / "compile.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    require(result.returncode == 0, "L1_COMPILE: " + result.stderr)
    result = subprocess.run(["vvp", str(directory / "sim.vvp")], cwd=directory, capture_output=True, text=True, timeout=120)
    log = result.stdout + result.stderr
    (directory / "simulation.log").write_text(log, encoding="utf-8")
    row = {"compile": command, "exit_code": result.returncode, "bench_sha256": sha(path),
           "sources": {p.name: sha(p) for p in copied}, "log_sha256": sha(directory / "simulation.log")}
    return row, log


def mutex_log(log):
    require(log.splitlines().count("RANDOM_MUTEX_PASS") == 1 and "FATAL:" not in log, "L1_MUTEX_LOG")
    choices = [tuple(map(int, line.split("|")[1:])) for line in log.splitlines() if line.startswith("CHOICE|")]
    require(len(choices) == 48 and [c[1:5] for c in choices[:24]] == [c[1:5] for c in choices[24:]], "L1_MUTEX_RESET_REPRODUCIBILITY")
    require(all(10 <= c[4] <= 100 for c in choices), "L1_MUTEX_CHOICE_BOUNDS")
    require(Counter((c[0], c[1]) for c in choices) == Counter({(e, m): 8 for e in (0, 1) for m in range(3)}), "L1_MUTEX_CHOICE_INVENTORY")
    schedules, latencies, winners, commits = {}, set(), defaultdict(set), 0
    for line in log.splitlines():
        fields = line.split("|")
        if fields[0] == "MUTEX_SCHEDULE":
            _, _, time, tag, winner, latency = fields
            require(10 <= int(latency) <= 100, "L1_MUTEX_BOUNDS")
            schedules[int(tag)] = (int(time), int(winner), int(latency))
            latencies.add(int(latency))
        elif fields[0] == "MUTEX_COMMIT":
            _, _, time, tag, winner = fields
            require(int(tag) in schedules, "L1_MUTEX_UNSCHEDULED_COMMIT")
            start, value, latency = schedules[int(tag)]
            require(int(time) == start + latency and int(winner) == value, "L1_MUTEX_COMMIT")
            commits += 1
    require(commits > 100, "L1_MUTEX_ACTIVITY")
    for _, mode, _, winner, _, _ in choices:
        require(winner in (1, 2), "L1_MUTEX_WINNER")
        winners[mode].add(winner)
    return {"choices": len(choices), "commits": commits, "latencies": sorted(latencies),
            "winners": {str(k): sorted(v) for k, v in winners.items()}}


def mutex_coverage(rows, minimum):
    latencies, winners = set(), defaultdict(set)
    for row in rows:
        latencies.update(row["latencies"])
        for mode, values in row["winners"].items():
            winners[mode].update(values)
    require(set(winners) == {"0", "1", "2"} and all(v == {1, 2} for v in winners.values()), "L1_MUTEX_WINNER_COVERAGE")
    require(len(latencies) >= minimum, "L1_MUTEX_LATENCY_COVERAGE")
    return len(latencies)


def comparable_mutex_log(log, bench_path):
    """Ignore only this case's path in Icarus's exact terminal finish record.

    The original log and its hash remain untouched. Line number, finish time,
    units, all decision/commit records and all other content remain significant.
    """
    pattern = (r"(?m)^" + re.escape(str(bench_path))
               + r"(?P<finish>:\d+: \$finish called at \d+ \([^\r\n()]+\))(?P<ending>\r?\n?)\Z")
    match = re.search(pattern, log)
    require(match is not None, "L1_MUTEX_FINISH_IDENTITY")
    return log[:match.start()] + "<case-bench>" + match["finish"] + match["ending"]


def check_mutex_noise_logs(first, first_bench, second, second_bench):
    require(comparable_mutex_log(first, first_bench) == comparable_mutex_log(second, second_bench),
            "L1_MUTEX_GLOBAL_RNG_INTERFERENCE")


def mutex_bench_path(row):
    # Retained compile arguments preserve the original host path when an audit
    # reads downloaded evidence from a different directory or operating system.
    command = row["compile"]
    position = command.index("-o") + 2
    require(position < len(command), "L1_MUTEX_BENCH_IDENTITY")
    bench = command[position]
    require(bench.replace("\\", "/").endswith(f'/{row["seed"]}_{row["noise"]}/bench.sv'),
            "L1_MUTEX_BENCH_IDENTITY")
    return bench


def run_mutex(plan, output, generated):
    source = (generated / "arbiter/ChiselAsyncMutex_v1.sv").read_text(encoding="utf-8")
    bench = (ROOT / "verification/mutex_random.sv").read_text(encoding="utf-8")
    rows = []
    for seed in plan["seeds"]:
        logs = []
        for noise in (0, 1):
            directory = output / f"{seed}_{noise}"
            row, log = compile_run(directory, "MutexReview", bench, {"ChiselAsyncMutex_v1.sv": source},
                                   (("SEED", seed), ("NOISE", noise)), True)
            require(row["exit_code"] == 0, "L1_MUTEX_SIMULATION")
            row.update(seed=seed, noise=noise, status="PASS", evidence=mutex_log(log))
            write(directory / "case.json", row)
            artifact_hashes(row, directory)
            rows.append(row)
            logs.append(log)
        check_mutex_noise_logs(logs[0], output / f"{seed}_0" / "bench.sv",
                               logs[1], output / f"{seed}_1" / "bench.sv")
    distinct = mutex_coverage([r["evidence"] for r in rows], plan["mutex_min_latencies"])
    # Real primitive mutant, paired with the same fresh seed and unchanged bench.
    # Match the documented assignment, while requiring exactly one target.
    changed, count = re.subn(r"latency = RESOLVE_FS \+ draw % \(RESOLVE_MAX_FS - RESOLVE_FS \+ 1\);", "latency = RESOLVE_FS;", source)
    require(count == 1, "L1_MUTEX_MUTATION_TARGET")
    directory = output / "constant_resolution"
    row, log = compile_run(directory, "MutexReview", bench, {"ChiselAsyncMutex_v1.sv": changed},
                           (("SEED", plan["seeds"][0]), ("NOISE", 0)), True)
    require(row["exit_code"] == 0, "L1_MUTEX_CONTROL_EXECUTION")
    evidence = mutex_log(log)
    try:
        mutex_coverage([evidence], plan["mutex_min_latencies"])
    except RuntimeError as error:
        require(str(error) == "L1_MUTEX_LATENCY_COVERAGE", "L1_WRONG_DIAGNOSTIC")
    else:
        raise RuntimeError("L1_CONTROL_ESCAPED")
    row.update(status="EXPECTED_REJECTION", diagnostic="L1_MUTEX_LATENCY_COVERAGE", evidence=evidence)
    write(directory / "case.json", row)
    write(output / "report.json", {"status": "PASS", "cases": rows, "faults": [row], "distinct_latencies": distinct})
    return {"positive_cases": len(rows), "controls": 1, "choices": 48 * len(rows), "distinct_latencies": distinct}


def audit_mutex(plan, output):
    report = read(output / "report.json")
    require(report["status"] == "PASS", "L1_MUTEX_STATUS")
    inventory(report["cases"], [(s, n) for s in plan["seeds"] for n in (0, 1)],
              ("seed", "noise"), "L1_MUTEX_INVENTORY")
    rows, logs, benches = [], {}, {}
    for row in report["cases"]:
        directory = output / f'{row["seed"]}_{row["noise"]}'
        require(row == read(directory / "case.json") and row["status"] == "PASS" and row["exit_code"] == 0, "L1_MUTEX_CASE")
        artifact_hashes(row, directory)
        log = (directory / "simulation.log").read_text()
        evidence = mutex_log(log)
        require(evidence == row["evidence"], "L1_MUTEX_SUMMARY")
        rows.append(evidence)
        logs[(row["seed"], row["noise"])] = log
        benches[(row["seed"], row["noise"])] = mutex_bench_path(row)
    for seed in plan["seeds"]:
        check_mutex_noise_logs(logs[(seed, 0)], benches[(seed, 0)], logs[(seed, 1)], benches[(seed, 1)])
    require(mutex_coverage(rows, plan["mutex_min_latencies"]) == report["distinct_latencies"], "L1_MUTEX_SUMMARY")
    require(len(report["faults"]) == 1, "L1_MUTEX_CONTROL_INVENTORY")
    row = report["faults"][0]
    directory = output / "constant_resolution"
    artifact_hashes(row, directory)
    require(row == read(directory / "case.json") and row["status"] == "EXPECTED_REJECTION" and row["exit_code"] == 0
            and row["diagnostic"] == "L1_MUTEX_LATENCY_COVERAGE", "L1_MUTEX_CONTROL")
    evidence = mutex_log((directory / "simulation.log").read_text())
    require(evidence == row["evidence"] and len(evidence["latencies"]) == 1, "L1_MUTEX_CONTROL_COVERAGE")


def run_extra_cases(plan, output, generated):
    from run import read_sources
    from run_dims import bench as dims_bench
    from run_phase import nodes
    # The fixed regression runners supply their paired controls. These new cases
    # add prospective delay assignments to the same contract-based schedules.
    m = read(generated / "reference_core/contract.json")["manifest"]
    sources = {p.name: p.read_text(encoding="utf-8") for p in read_sources(generated / "reference_core")}
    dims = []
    for seed in plan["seeds"]:
        directory = output / "dims" / str(seed)
        row, log = compile_run(directory, "DimsBench", dims_bench(m, seed), sources)
        require(row["exit_code"] == 0 and log.splitlines().count("DIMS_PASS:9222") == 1 and "FATAL:" not in log, "L1_DIMS_ACTIVITY")
        row.update(seed=seed, status="PASS", deliveries=9222)
        write(directory / "case.json", row)
        dims.append(row)
    m = read(generated / "phase_to_two/contract.json")["manifest"]
    node = next(n for n in nodes(m["design"]) if any(p["id"] == "history" for p in n["primitives"]))
    model, cells = node["module"], {p["id"]: p["rtl_path"].split(".")[-1] for p in node["primitives"]}
    sources = {p.name: p.read_text(encoding="utf-8") for p in read_sources(generated / "phase_to_two")}
    def pin(name):
        return re.search(re.escape(cells[name]) + r"\s*\([\s\S]*?\.q\s*\((\w+)\)", sources[model + ".sv"])[1]
    insert = f"{model} dut(.reset(reset),.in_req(req4),.in_bits(8'h5a),.in_ack(ack4),.out_req(req2),.out_bits(),.out_ack(ack2));\n"
    insert += "\n".join(f"defparam dut.{cells[name]}.DELAY_FS={key};" for key, name in
                          {"C": "history_close", "T": "request_phase", "H": "history", "X": "acknowledge", "G": "request_guard"}.items())
    insert += f'\nassign closed=dut.{pin("history_close")}; assign history=dut.{pin("history")};'
    bench = (ROOT / "verification/phase_closure.sv").read_text().replace("// DUT_INSERT", insert)
    closure = []
    for index, parameters in enumerate(plan["closure_parameters"]):
        directory = output / "closure" / str(index)
        row, log = compile_run(directory, "ReviewAdapterBench", bench, sources, parameters.items())
        require(row["exit_code"] == 0 and log.splitlines().count("ADAPTER_REVIEW_PASS transfers=22 reset_windows=6") == 1
                and "FATAL:" not in log, "L1_CLOSURE_ACTIVITY")
        row.update(status="PASS", parameters=parameters, transfers=22, reset_windows=6)
        write(directory / "case.json", row)
        closure.append(row)
    write(output / "report.json", {"status": "PASS", "dims": dims, "closure": closure})
    return {"dims_cases": len(dims), "dims_deliveries": 9222 * len(dims), "closure_cases": len(closure), "closure_transfers": 22 * len(closure)}


def audit_extra_cases(plan, output):
    report = read(output / "report.json")
    require(report["status"] == "PASS", "L1_FRESH_STATUS")
    inventory(report["dims"], [(s,) for s in plan["seeds"]], ("seed",), "L1_FRESH_DIMS_INVENTORY")
    require([r["parameters"] for r in report["closure"]] == plan["closure_parameters"], "L1_FRESH_CLOSURE_INVENTORY")
    for lane in ("dims", "closure"):
        for index, row in enumerate(report[lane]):
            directory = output / lane / str(row["seed"] if lane == "dims" else index)
            artifact_hashes(row, directory)
            require(row == read(directory / "case.json") and row["status"] == "PASS" and row["exit_code"] == 0, "L1_FRESH_CASE")
            marker = "DIMS_PASS:9222" if lane == "dims" else "ADAPTER_REVIEW_PASS transfers=22 reset_windows=6"
            log = (directory / "simulation.log").read_text()
            require(log.splitlines().count(marker) == 1 and "FATAL:" not in log, "L1_FRESH_ACTIVITY")
            require(row.get("deliveries") == 9222 if lane == "dims" else row["transfers"] == 22 and row["reset_windows"] == 6, "L1_FRESH_ACTIVITY")


def audit_fixed(plan, output, lane):
    report = read(output / "report.json")
    expected = plan["fixed_regressions"][lane]
    require(report["status"] == "PASS" and len(report["cases"]) == expected["cases"], "L1_FIXED_INVENTORY")
    require([r["diagnostic"] for r in report["faults"]] == list(expected["faults"].values()), "L1_FIXED_CONTROLS")
    if lane == "dims":
        inventory(report["cases"], [(s,) for s in (0, 2, 3, 17, 91)], ("seed",), "L1_DIMS_REGRESSION_INVENTORY")
    else:
        parameters = [dict(C=c, T=t, H=h, X=x, G=c+1 if tight else c*4)
                      for c, (t, h, x), tight in itertools.product((1000000, 10000000, 100000000),
                      itertools.product((1, 10000000), repeat=3), (False, True))]
        parameters += [dict(C=c*1000000, T=t*1000000, H=h*1000000, X=1000000, G=40000000)
                       for h, t, c in itertools.product((1, 5), (1, 5), range(13))]
        parameters += [dict(C=10000000, T=1000000, H=1000000, X=1000000, G=40000000)]
        require([r["parameters"] for r in report["cases"]] == parameters, "L1_CLOSURE_REGRESSION_INVENTORY")
    for index, row in enumerate(report["cases"]):
        name = str(row["seed"]) if lane == "dims" else ("case_paired" if index == 100 else f"case_{index}")
        directory = output / name
        artifact_hashes(row, directory)
        marker = "DIMS_PASS:9222" if lane == "dims" else "ADAPTER_REVIEW_PASS transfers=22 reset_windows=6"
        log = (directory / "simulation.log").read_text()
        require(row["status"] == "PASS" and log.splitlines().count(marker) == 1 and "FATAL:" not in log, "L1_FIXED_ACTIVITY")
    for (name, diagnostic), row in zip(expected["faults"].items(), report["faults"]):
        require(row["status"] == "EXPECTED_REJECTION", "L1_CONTROL_STATUS")
        artifact_hashes(row, output / name)
        exact_fatal((output / name / "simulation.log").read_text(), diagnostic)
    return {"positive_cases": expected["cases"], "controls": len(expected["faults"])}


def prepare_exports(plan, generated, destination):
    for fixture, expected in plan["exports"].items():
        source = generated / fixture
        document = read(source / "contract.json")
        actual = {"semantic_sha256": document["semantic_sha256"], "probe_abi_sha256": document["manifest"]["probe_abi"]["sha256"],
                  "port_abi_sha256": document["manifest"]["port_abi"]["sha256"]}
        require(actual == expected, "L1_EXPORT_IDENTITY: " + fixture)
        shutil.copytree(source, destination / fixture)


def freeze(plan_path, candidate_path):
    plan = read(plan_path)
    check_plan(plan)
    candidate = {"schema": "chisel-async-l1-candidate-v1", "source_revision": git("rev-parse", "HEAD").decode().strip(),
                 "baseline": plan["baseline"], "production": plan["production"], "plan_sha256": sha(plan_path, True),
                 "sources": source_inventory(acceptance=True)}
    check_committed(candidate["sources"])
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    with candidate_path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(candidate, indent=2) + "\n")
    print("Frozen, not executed; commit this candidate before running: " + str(candidate_path))


def run(plan_path, candidate_path, generated, output):
    require(not output.exists(), "L1_OUTPUT_EXISTS: acceptance requires a fresh explicit directory")
    output.mkdir(parents=True)
    report = {"status": "RUNNING", "review": "separate required decision", "started_utc": datetime.now(timezone.utc).isoformat(), "lanes": {}}
    def save():
        write(output / "report.json", report)
    save()
    try:
        plan = read(plan_path)
        candidate = read(candidate_path)
        check_plan(plan)
        require(candidate["schema"] == "chisel-async-l1-candidate-v1" and candidate["plan_sha256"] == sha(plan_path, True)
                and candidate["baseline"] == plan["baseline"] and candidate["production"] == plan["production"], "L1_CANDIDATE_CONTRACT")
        require(not sys.flags.optimize and not os.environ.get("PYTHONOPTIMIZE"), "L1_PYTHON_ASSERTIONS_DISABLED")
        check_sources(candidate)
        check_committed([*candidate["sources"], candidate_path.relative_to(ROOT).as_posix()])
        initial = {name: sha(ROOT / name, True) for name in sorted(ADDITIONS)}
        report.update(candidate=git("rev-parse", "HEAD").decode().strip(), baseline=plan["baseline"], production=plan["production"],
                      source_revision=candidate["source_revision"], candidate_sha256=sha(candidate_path, True),
                      plan_sha256=sha(plan_path, True), acceptance_inputs=initial)
        write(output / "plan.json", plan)
        write(output / "candidate.json", candidate)
        from campaign_environment import identity
        report.update(identity())
        generated_copy = output / "generated"
        prepare_exports(plan, generated, generated_copy)
        commands = [("composition", "run_composition.py", ["--seeds", *map(str, plan["seeds"]), "--jobs", "4"]),
                    ("phase", "run_phase.py", ["--seeds", *map(str, plan["seeds"])]),
                    ("reference", "run_reference.py", ["--seeds", *map(str, plan["seeds"])]),
                    ("closure", "run_closure.py", []), ("dims", "run_dims.py", [])]
        for lane, script, arguments in commands:
            command = [sys.executable, str(ROOT / "verification" / script), "--generated", str(generated_copy), "--output", str(output / lane), *arguments]
            report["lanes"][lane] = {"status": "RUNNING", "command": command}
            save()
            with (output / (lane + ".log")).open("w", encoding="utf-8") as log:
                result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=1800)
            report["lanes"][lane]["exit_code"] = result.returncode
            require(result.returncode == 0, "L1_LANE_FAILED: " + lane)
            if lane in ("closure", "dims"):
                audit = audit_fixed(plan, output / lane, lane)
            else:
                audit = {"composition": audit_composition, "phase": audit_phase, "reference": audit_reference}[lane](plan, output / lane, generated_copy)
            report["lanes"][lane].update(status="PASS", audit=audit, report_sha256=sha(output / lane / "report.json"))
            save()
            print(lane + " independently audited PASS", flush=True)
        report["lanes"]["fresh_parameters"] = {"status": "RUNNING"}
        save()
        fresh = run_extra_cases(plan, output / "fresh_parameters", generated_copy)
        audit_extra_cases(plan, output / "fresh_parameters")
        report["lanes"]["fresh_parameters"].update(status="PASS", audit=fresh)
        report["lanes"]["mutex"] = {"status": "RUNNING"}
        save()
        mutex = run_mutex(plan, output / "mutex", generated_copy)
        audit_mutex(plan, output / "mutex")
        report["lanes"]["mutex"].update(status="PASS", audit=mutex)
        # Recheck every recorded artifact before finalization, after all simulations.
        for path in output.rglob("case.json"):
            artifact_hashes(read(path), path.parent)
        check_sources(candidate)
        require(initial == {name: sha(ROOT / name, True) for name in sorted(ADDITIONS)}, "L1_ACCEPTANCE_INPUT_CHANGED")
        require(report["plan_sha256"] == sha(plan_path, True), "L1_PLAN_CHANGED")
        require(report["candidate_sha256"] == sha(candidate_path, True), "L1_CANDIDATE_CHANGED")
        write(output / "artifact-hashes.json", {p.relative_to(output).as_posix(): sha(p) for p in sorted(output.rglob("*"))
                                               if p.is_file() and p != output / "report.json"})
        report.update(status="PASS", finished_utc=datetime.now(timezone.utc).isoformat(),
                      artifact_inventory_sha256=sha(output / "artifact-hashes.json"))
    except BaseException as error:
        report.update(status="ERROR", error=str(error))
        save()
        raise
    save()
    print("L1 acceptance PASS; review/native-platform closure remains a separate decision: " + str(output / "report.json"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--freeze", action="store_true", help="Create a NEW candidate from committed inputs; never overwrite or execute")
    parser.add_argument("--generated", type=Path, default=ROOT / "target/generated")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.freeze:
        require(args.output is None, "L1_FREEZE_DOES_NOT_EXECUTE")
        freeze(args.plan.resolve(), args.candidate.resolve())
        return
    parser.error("--output is required for an acceptance attempt") if args.output is None else None
    bins = [ROOT / ".tools/iverilog/bin"]
    if os.name == "nt":
        bins.append(Path("C:/msys64/ucrt64/bin"))
    os.environ["PATH"] = os.pathsep.join(map(str, bins)) + os.pathsep + os.environ.get("PATH", "")
    run(args.plan.resolve(), args.candidate.resolve(), args.generated.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
