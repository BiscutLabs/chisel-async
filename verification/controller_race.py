# SPDX-License-Identifier: Apache-2.0
"""Counterexample to the withdrawn controller, not qualification of a timed view.

Annotate the actual emitted structural fixture with one delayed release AND and
captured-value latch updates. Pair the counterexample with a zero-gate-delay run.
This deliberately small experiment does not reproduce the external 300-seed sweep.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from check_export import validate_export
from run import read_sources

BENCH = """`timescale 1ns/1ps
module ControllerRace;
  reg reset = 0, in_req = 0, out_ack = 0;
  reg [7:0] in_bits = 0;
  wire in_ack, out_req;
  wire [7:0] out_bits;
  integer accepted = 0, delivered = 0, offered = 0;
  StructuralBufferExample dut(.reset(reset), .in_req(in_req), .in_bits(in_bits),
    .in_ack(in_ack), .out_req(out_req), .out_bits(out_bits), .out_ack(out_ack));
  always @(posedge in_ack) if (!reset) accepted = accepted + 1;
  always @(posedge out_ack) if (!reset) delivered = delivered + 1;
  always @(posedge out_req) if (!reset) begin
    offered = offered + 1;
    $display("OFFER time=%0t accepted=%0d delivered=%0d offered=%0d", $time, accepted, delivered, offered);
    if (offered > 1) begin
      if (accepted != 1 || delivered != 1 || in_req != 0)
        $fatal(1, "UNEXPECTED_COUNTEREXAMPLE_STATE");
      $fatal(1, "RACE_DUPLICATE_OFFER accepted=1 delivered=1 offered=2");
    end
  end
  initial begin
    $dumpfile("race.vcd");
    $dumpvars(0, ControllerRace);
    #1 reset = 1;
    #100 reset = 0;
    #100 in_bits = 8'hA5;
    #100 in_req = 1;
    wait(in_ack === 1);
    #100 in_req = 0;
    wait(in_ack === 0);
    wait(out_req === 1);
    #100;
    if (out_bits !== 8'hA5) $fatal(1, "INITIAL_PAYLOAD_MISMATCH");
    out_ack = 1;
    wait(out_req === 0);
    #100 out_ack = 0;
    #100;
    if (accepted != 1 || delivered != 1 || offered != 1 || in_ack !== 0 || out_req !== 0)
      $fatal(1, "INCOMPLETE_BASELINE");
    $display("BASELINE_PASS accepted=1 delivered=1 offered=1");
    $finish;
  end
  initial begin #2000; $fatal(1, "COUNTEREXAMPLE_TIMEOUT"); end
endmodule
"""


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError(f"Counterexample annotation target missing or ambiguous: {old}")
    return text.replace(old, new)


def run_case(generated, destination, gate_delay):
    destination.mkdir(parents=True, exist_ok=True)
    sources = []
    for source in read_sources(generated):
        contents = source.read_text(encoding="utf-8")
        if source.name == "StructuralBufferExample.sv":
            contents = replace_once(contents, ".enable (take | full & release_0)",
                                    ".enable (take | delayed_release)")
            contents = replace_once(contents, "  wire       out_req_0 =",
                f"  wire #{gate_delay} delayed_release = full & release_0;\n  wire       out_req_0 =")
        elif source.name == "ChiselAsyncLatch_v1.sv":
            # Captured-value nonblocking delay on all latch assignments, including reset.
            # Not an inertial gate model, analog model, or production resource change.
            if contents.count("q <= ") != 4:
                raise RuntimeError("Counterexample latch annotation target changed")
            contents = contents.replace("q <= ", "q <= #1 ")
        target = destination / source.name
        target.write_text("`timescale 1ns/1ps\n" + contents, encoding="utf-8")
        sources.append(target)
    bench = destination / "ControllerRace.sv"
    bench.write_text(BENCH, encoding="utf-8")
    compile_result = subprocess.run(["iverilog", "-g2012", "-s", "ControllerRace", "-o", "race.vvp",
                                    *map(str, sources), str(bench)], cwd=destination,
                                   capture_output=True, text=True, timeout=30)
    (destination / "compile.log").write_text(compile_result.stdout + compile_result.stderr, encoding="utf-8")
    if compile_result.returncode:
        raise RuntimeError("Counterexample compilation failed")
    simulated = subprocess.run(["vvp", "race.vvp"], cwd=destination, capture_output=True, text=True, timeout=30)
    (destination / "simulation.log").write_text(simulated.stdout + simulated.stderr, encoding="utf-8")
    diagnostic = "RACE_DUPLICATE_OFFER accepted=1 delivered=1 offered=2"
    if gate_delay:
        fatals = [line for line in simulated.stdout.splitlines() if line.startswith("FATAL:")]
        if simulated.returncode == 0 or len(fatals) != 1 or not fatals[0].endswith(diagnostic):
            raise RuntimeError("Expected duplicate-offer counterexample not reproduced; inspect evidence")
    elif simulated.returncode or "BASELINE_PASS accepted=1 delivered=1 offered=1" not in simulated.stdout:
        raise RuntimeError("Counterexample baseline failed")
    return {"release_and_delay_ns": gate_delay, "latch_delay_ns": 1,
            "status": "COUNTEREXAMPLE_REPRODUCED" if gate_delay else "BASELINE_PASS",
            "diagnostic": diagnostic if gate_delay else None,
            "source_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in [*sources, bench]}}


def main():
    output = ROOT / "target/verification/controller-race"
    output.mkdir(parents=True, exist_ok=True)
    report = output / "report.json"
    report.write_text('{"status":"RUNNING"}\n', encoding="utf-8")
    try:
        generated = ROOT / "target/generated/structural"
        version = subprocess.run(["iverilog", "-V"], capture_output=True, text=True, check=True).stdout.splitlines()[0]
        if "version 13.0 " not in version:
            raise RuntimeError(f"Unqualified Icarus version: {version}")
        resolution = validate_export(generated)
        cases = [run_case(generated, output / name, delay) for name, delay in (("baseline", 0), ("race", 10))]
        result = {"status": "COUNTEREXAMPLE_REPRODUCED", "platform": platform.platform(),
                  "simulator": version, "original_semantic_sha256": resolution["semantic_sha256"],
                  "experiment_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  "scope": "single-stage directed race; not the external 300-seed experiment", "cases": cases}
    except BaseException as error:
        report.write_text(json.dumps({"status": "ERROR", "error": str(error)}, indent=2) + "\n", encoding="utf-8")
        raise
    report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Controller race reproduced; this controller must remain withdrawn. Evidence: {report}")


if __name__ == "__main__":
    main()
