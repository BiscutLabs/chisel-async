# SPDX-License-Identifier: Apache-2.0
"""Bounded digital comparison; deliberately not physical/controller qualification.

The withdrawn DUT is elaborated Scala RTL, then each Boolean operation is given
an explicit inertial cell. The Muller reference is independently written SV.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import itertools
import json
from pathlib import Path
import platform
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from check_export import validate_export

VIOLATIONS = {
    "DATA_HOLD", "PROTOCOL_REQ_RISE", "PROTOCOL_ACK_RISE", "PROTOCOL_REQ_FALL",
    "PROTOCOL_ACK_FALL", "UNEXPECTED_TOKEN", "PAYLOAD_MISMATCH", "RESET_NOT_QUIESCENT",
    "STALE_AFTER_RESET", "INCOMPLETE_OR_DUPLICATE", "INCOMPLETE_CHANNEL", "STREAM_COUNTS",
    "CAPACITY_COUNT", "CAPACITY_EXCEEDED", "DELIVERY_WITHOUT_SINK", "RESET_ABORT_COUNT",
}
COUNTS = re.compile(r"RESULT PASS accepted=(\d+) delivered=(\d+) aborted=(\d+) "
                    r"returned=(\d+) offered=(\d+) peak=(\d+) resets=(\d+)")


def expression(source):
    """Parse the deliberately restricted scalar grammar; reject all other RTL."""
    tokens = re.findall(r"[A-Za-z_][A-Za-z_0-9]*|[~&|()]", source)
    if "".join(tokens) != re.sub(r"\s", "", source):
        raise ValueError(f"Unsupported expression: {source}")
    cursor = 0

    def parse(level=0):
        nonlocal cursor
        if level < 2:
            left = parse(level + 1)
            op = "|&"[level]
            while cursor < len(tokens) and tokens[cursor] == op:
                cursor += 1
                left = (op, left, parse(level + 1))
            return left
        if cursor == len(tokens):
            raise ValueError(f"Incomplete expression: {source}")
        token = tokens[cursor]
        cursor += 1
        if token == "~":
            return ("~", parse(2))
        if token == "(":
            result = parse()
            if cursor == len(tokens) or tokens[cursor] != ")":
                raise ValueError(f"Unbalanced expression: {source}")
            cursor += 1
            return result
        if re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", token):
            return token
        raise ValueError(f"Unexpected token: {token}")

    result = parse()
    if cursor != len(tokens):
        raise ValueError(f"Trailing expression: {source}")
    return result


def instrument(source):
    """Preserve emitted state connectivity; expand scalar ops, without factoring."""
    source = re.sub(r"//[^\n]*", "", source)
    header = "module ControllerComparisonExample("
    if source.count(header) != 1 or source.count("endmodule") != 1:
        raise ValueError("Unexpected generated module inventory")
    source = source.replace(header, "module ControllerComparisonExample #(parameter BASE=0)(")
    cells, declarations, gates = [], [], []

    def expand(tree):
        if isinstance(tree, str):
            return tree
        op, a, *rest = tree
        a = expand(a)
        b = expand(rest[0]) if rest else "1'b0"
        index = len(cells)
        name = f"cmp_{index}"
        cells.append({"id": index, "kind": {"~": "not", "&": "and", "|": "or"}[op],
                      "a": a, "b": b, "q": name})
        declarations.append(f"  wire {name};")
        gates.append(f"  ComparisonGate #(.ID(BASE+{index}), .OP({'~&|'.index(op)})) "
                     f"gate_{index}(.a({a}), .b({b}), .q({name}));")
        return name

    def wire(match):
        kind, name, rhs = match.groups()
        return f"{kind} {name} = {expand(expression(rhs))};"

    source = re.sub(r"\b(wire|assign)\s+(\w+)\s*=\s*([^;]+);", wire, source)

    def latch(match):
        params, name, ports = match.groups()
        if not re.fullmatch(r"\s*\.RESET_VALUE\(0\),\s*\.WIDTH\((1|40)\)\s*", params):
            raise ValueError("Unexpected latch parameters")
        def port(m):
            return f".{m[1]} ({expand(expression(m[2]))})"
        ports = re.sub(r"\.(reset|enable|d|q)\s*\(([^\n]+)\)", port, ports)
        index = len(cells)
        cells.append({"id": index, "kind": "latch", "instance": name})
        return f"ComparisonLatch #(.ID(BASE+{index}),{params}) {name} ({ports});"

    source, count = re.subn(r"ChiselAsyncLatch_v1\s*#\((.*?)\)\s*(\w+)\s*\((.*?)\);",
                            latch, source, flags=re.S)
    if count != 4 or len(cells) >= 100:
        raise ValueError("Unexpected emitted cell inventory")
    # Fail closed if the compiler moves logic to an unsupported location.
    if re.search(r"[~&|^?]|\b(always|initial|reg|logic|generate|function)\b", source):
        raise ValueError("Unsupported or uninstrumented RTL")
    for match in re.finditer(r"\bassign\s+([^;]+);", source):
        if not re.fullmatch(r"\w+\s*=\s*\w+", match[1]):
            raise ValueError("Unsupported continuous assignment")
    for match in re.finditer(r"\bwire\s+\[[^]]+\]\s+\w+\s*=\s*([^;]+);", source):
        if not re.fullmatch(r"\w+", match[1].strip()):
            raise ValueError("Unsupported vector expression")
    source = source.replace(");\n", ");\n" + "\n".join(declarations) + "\n", 1)
    source = source.replace("endmodule", "\n".join([*gates, "endmodule"]))
    return "`timescale 1ns/1ps\n" + source, cells


def random_words(seed):
    """Frozen xorshift32-v1; not Python's implementation-dependent PRNG API."""
    state = seed + 1
    while True:
        state ^= (state << 13) & 0xFFFFFFFF
        state ^= state >> 17
        state ^= (state << 5) & 0xFFFFFFFF
        state &= 0xFFFFFFFF
        yield state


def classify(code, log):
    fatals = re.findall(r"^FATAL: [^\n]*?: (\w+)([^\n]*)", log, re.M)
    counts = COUNTS.findall(log)
    if code == 0 and not fatals and len(counts) == 1:
        a, d, b, r, o, p, n = map(int, counts[0])
        if a == d + b and d == 49 and r == 47 and o >= d and p > 0 and n == 7:
            return {"status": "PASS", "counts": dict(zip(
                ("accepted", "delivered", "aborted", "returned", "offered", "peak", "resets"),
                (a, d, b, r, o, p, n)))}
        return {"status": "INFRASTRUCTURE_ERROR", "diagnostic": "Missing required activity"}
    if code == 1 and fatals and not counts and all(n in VIOLATIONS or n == "SIM_DEADLINE" for n, _ in fatals):
        name, details = fatals[0]
        return {"status": "BOUNDED_NONPROGRESS" if name == "SIM_DEADLINE" else "VIOLATION",
                "diagnostic": name, "details": details.strip(),
                "all_diagnostics": [n for n, _ in fatals]}
    return {"status": "INFRASTRUCTURE_ERROR", "diagnostic": "Unexpected simulator outcome"}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compile_model(output, name, sources, *, muller=True, depth=3, forward=40, ack=20):
    directory = output / "build" / name
    directory.mkdir(parents=True, exist_ok=True)
    executable = directory / "bench.vvp"
    command = ["iverilog", "-g2012", "-s", "ControllerBench", "-o", str(executable),
               f"-PControllerBench.MULLER={int(muller)}", f"-PControllerBench.DEPTH={depth}",
               f"-PControllerBench.FORWARD_NS={forward}", f"-PControllerBench.ACK_NS={ack}",
               *map(str, sources)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    (directory / "compile.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    (directory / "compile.json").write_text(json.dumps(command, indent=2), encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"Compilation failed: {directory / 'compile.log'}")
    return executable


def run_case(executable, directory, configuration, waves=False):
    directory.mkdir(parents=True, exist_ok=True)
    args = [f"+d{k}={v}" for k, v in configuration["delays_ns"].items()]
    args += [f"+{k}={v}" for k, v in configuration["environment_ns"].items()]
    command = ["vvp", str(executable), *args, *(["+waves"] if waves else [])]
    (directory / "case.json").write_text(json.dumps({**configuration, "command": command}, indent=2), encoding="utf-8")
    try:
        result = subprocess.run(command, cwd=directory, capture_output=True, text=True, timeout=20)
        log = result.stdout + result.stderr
        outcome = classify(result.returncode, log)
    except subprocess.TimeoutExpired:
        log = "HOST_TIMEOUT: no inference about controller progress is permitted\n"
        outcome = {"status": "INFRASTRUCTURE_ERROR", "diagnostic": "HOST_TIMEOUT"}
    (directory / "simulation.log").write_text(log, encoding="utf-8")
    return {"case": directory.name, **outcome}


def configuration(seed, depth, count, uniform=None, corner=None):
    rng = random_words(seed)
    # Same environment for both controllers, independent of their cell counts.
    env = {key: 1 + next(rng) % 60 for key in
           ("source_pause", "sink_pause", "source_return", "sink_return")}
    delays = {stage * 100 + cell: uniform if uniform is not None else
              corner[cell] if corner is not None else 1 + next(rng) % 10
              for stage in range(depth) for cell in range(count)}
    return {"seed": seed, "prng": "xorshift32-v1", "delays_ns": delays, "environment_ns": env}


def check_cells(build):
    bench = build / "cell_bench.sv"
    bench.write_bytes((ROOT / "verification/controllers/cell_bench.sv").read_bytes())
    for delay in (1, 10):
        executable = build / f"cells_{delay}.vvp"
        compiled = subprocess.run(["iverilog", "-g2012", "-s", "ComparisonCellBench",
            f"-PComparisonCellBench.D={delay}", "-o", str(executable), str(bench), str(build / "cells.sv")],
            capture_output=True, text=True, timeout=30)
        (build / f"cells_{delay}_compile.log").write_text(compiled.stdout + compiled.stderr, encoding="utf-8")
        if compiled.returncode:
            raise RuntimeError("Cell test compilation failed")
        result = subprocess.run(["vvp", str(executable), *[f"+d{i}={delay}" for i in range(3)]],
                                capture_output=True, text=True, timeout=20)
        (build / f"cells_{delay}.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        if result.returncode or result.stdout.count(f"CELL_PASS delay={delay}") != 1:
            raise RuntimeError(f"Comparison cell semantics failed for delay {delay}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=300)
    parser.add_argument("--output", type=Path, default=ROOT / "target/verification/controller-comparison")
    args = parser.parse_args()
    if not 2 <= args.seeds <= 10000:
        parser.error("--seeds must be in 2..10000 (include the fixed seed-1 counterexample)")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = output / "report.json"
    report.write_text('{"status":"RUNNING"}\n', encoding="utf-8")
    try:
        version = subprocess.run(["iverilog", "-V"], capture_output=True, text=True, check=True).stdout.splitlines()[0]
        if "version 13.0 " not in version:
            raise RuntimeError(f"Unqualified Icarus version: {version}")
        generated = ROOT / "target/generated/comparison_unsafe"
        original = validate_export(generated)
        annotated, cells = instrument((generated / "ControllerComparisonExample.sv").read_text(encoding="utf-8"))
        build = output / "build"
        build.mkdir(exist_ok=True)
        unsafe = build / "withdrawn.sv"
        unsafe.write_text(annotated, encoding="utf-8")
        (build / "cell-map.json").write_text(json.dumps(cells, indent=2), encoding="utf-8")
        sources = [ROOT / "verification/controllers" / f for f in ("cells.sv", "muller.sv", "bench.sv")]
        # Snapshot all inputs for replay, not just hashes of potentially changed files.
        snapshots = []
        for path in sources:
            target = build / path.name
            target.write_bytes(path.read_bytes())
            snapshots.append(target)
        sources = [unsafe, *snapshots]
        check_cells(build)
        campaigns = {}
        for name, muller, depth in (("withdrawn", False, 3), ("muller", True, 3), ("muller_six", True, 6)):
            executable = compile_model(output, name, sources, muller=muller, depth=depth)
            count = 4 if muller else len(cells)
            cases = [(f"uniform_{d}", configuration(0, depth, count, uniform=d)) for d in (1, 10)]
            cases += [(f"seed_{s:03}", configuration(s, depth, count)) for s in range(args.seeds)]
            if muller:
                cases += [(f"corner_{i:02}", configuration(0, depth, count, corner=c))
                          for i, c in enumerate(itertools.product((1, 10), repeat=4))]
            outcomes, recorded_failures = [], set()
            for label, config in cases:
                result = run_case(executable, output / name / label, config, waves=label == "uniform_10")
                outcomes.append(result)
                if result["status"] == "INFRASTRUCTURE_ERROR":
                    raise RuntimeError(f"Infrastructure failure in {name}/{label}: {result}")
                if result["status"] != "PASS" and result["diagnostic"] not in recorded_failures:
                    replay = run_case(executable, output / name / (label + "_trace"), config, waves=True)
                    if {k: v for k, v in result.items() if k != "case"} != {k: v for k, v in replay.items() if k != "case"}:
                        raise RuntimeError("Failure replay changed outcome")
                    recorded_failures.add(result["diagnostic"])
            campaigns[name] = {"depth": depth, "expected_stalled_capacity": (depth+1)//2 if muller else depth,
                               "summary": dict(Counter(r["status"] for r in outcomes)), "cases": outcomes}
            print(name, campaigns[name]["summary"], flush=True)
            if any(r["status"] != "PASS" for r in outcomes[:2]):
                raise RuntimeError(f"Uniform-delay baseline failed for {name}")
        # A missing forward bundling margin must be caught while request is held.
        executable = compile_model(output, "bad_forward", sources, forward=0)
        config = configuration(0, 3, 4, corner=(1, 1, 1, 10))
        config["environment_ns"]["sink_pause"] = 60
        control = run_case(executable, output / "controls/bad_forward", config, waves=True)
        if control.get("all_diagnostics") != ["DATA_HOLD"]:
            raise RuntimeError(f"Bundling fault control missed its intended diagnostic: {control}")
        # Mutate the reference datapath, not the scoreboard: even unchanged low
        # payload bytes must not hide a wrong transaction identity.
        bad_payload = build / "bad_payload.sv"
        reference = (build / "muller.sv").read_text(encoding="utf-8")
        if reference.count(".d(in_bits)") != 1:
            raise RuntimeError("Payload fault injection target changed")
        bad_payload.write_text(reference.replace(".d(in_bits)", ".d({32'd0,in_bits[7:0]})"), encoding="utf-8")
        executable = compile_model(output, "bad_identity", [p if p.name != "muller.sv" else bad_payload for p in sources])
        identity_control = run_case(executable, output / "controls/bad_identity", configuration(0, 3, 4, uniform=1), waves=True)
        if identity_control.get("all_diagnostics") != ["PAYLOAD_MISMATCH"]:
            raise RuntimeError(f"Identity fault control missed its intended diagnostic: {identity_control}")
        if campaigns["withdrawn"]["summary"].get("VIOLATION", 0) == 0:
            raise RuntimeError("Withdrawn controller did not produce a functional counterexample")
        if any(r["status"] != "PASS" for n in ("muller", "muller_six") for r in campaigns[n]["cases"]):
            raise RuntimeError("Muller reference violated the declared bounded assumptions")
        result = {"status": "COMPARISON_COMPLETE", "scope": "bounded digital evidence; not external review replication",
                  "platform": platform.platform(), "python": sys.version, "simulator": version,
                  "original_semantic_sha256": original["semantic_sha256"],
                  "original_source_sha256": original["source_sha256"],
                  "source_sha256": {p.name: sha(p) for p in [*sources, bad_payload, build / "cell_bench.sv", Path(__file__)]},
                  "cell_semantics": {"status": "PASS", "delays_ns": [1, 10]},
                  "random_seeds": args.seeds, "forward_margin_ns": 40, "ack_margin_ns": 20,
                  "campaigns": campaigns, "controls": [control, identity_control]}
    except BaseException as error:
        report.write_text(json.dumps({"status": "ERROR", "error": str(error),
                          "campaigns": locals().get("campaigns", {})}, indent=2) + "\n", encoding="utf-8")
        raise
    report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Comparison evidence: {report}")


if __name__ == "__main__":
    main()
