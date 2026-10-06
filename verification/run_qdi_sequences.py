# SPDX-License-Identifier: Apache-2.0
"""CA-08 emitted-RTL source-return, reservation, chain-capacity and reset checks.

Finite digital evidence with atomic cells and ideal forks, not physical QDI.
Every attempt keeps its copied exports, benches, traces, logs and replay hashes.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import run_qdi as q

FIXTURES = tuple(f for f in q.FIXTURES if f not in ("qdi_fork", "qdi_composition"))
DIAGNOSTIC = "QDI_SOURCE_SPACER_HOLD"
DEADLINE = 'initial begin #1000000000000;$fatal(1,"QDI_SEQUENCE_DEADLINE");end endmodule'
START = 'trace=$fopen("trace.txt","w");$fdisplay(trace,"QDI_TRACE|1");recover();'
FINISH = 'snapshot();$fclose(trace);trace=0;$display("QDI_SEQUENCE_PASS");$finish;end'


def source_bench(fixture, manifest, ports, seed):
    q.check_fixture_shape(fixture, manifest)
    lines, roots, channels, overrides = q.setup(manifest, ports, seed)
    incoming = [c for c in roots.values() if c["role"] == "input"]
    outgoing = [c for c in roots.values() if c["role"] == "output"]
    width, ow = q.WIDTH[fixture], outgoing[0]["width"]
    mask, output_mask = (1 << width) - 1, (1 << ow) - 1
    lines += [f"reg [{width-1}:0] drive_zero=0,drive_one=0;integer selected=0;", "task set_input;begin"]
    if fixture == "qdi_join":
        for channel, bits in ((roots["left_input"], "[2]"), (roots["right_input"], "[1:0]")):
            lines += [f'{channel[rail]}=drive_{rail}{bits};' for rail in ("one", "zero")]
    else:
        for index, channel in enumerate(incoming):
            lines += [f'{channel[rail]}=' + (f'selected=={index} ? drive_{rail} : 0;' if fixture == "qdi_merge"
                       else f'drive_{rail};') for rail in ("one", "zero")]
    lines += ["end endtask"]
    input_ack = " && ".join(c["ack"] for c in incoming) if fixture == "qdi_join" else q.choose_expr(incoming, "ack")
    any_ack = " | ".join(c["ack"] for c in incoming)
    one, zero = (q.choose_expr(outgoing, rail) for rail in ("one", "zero"))
    ack_high = " ".join(c["ack"] + "=" + (f"selected=={i};" if len(outgoing) > 1 else "1;") for i, c in enumerate(outgoing))
    ack_low = " ".join(c["ack"] + "=0;" for c in outgoing)
    lines += ["initial begin " + START, f"drive_zero={mask};set_input();wait(({one}|{zero})=={output_mask});wait({input_ack});#STEP;",
              f'if({one}!=={ow}\'d{q.truth(fixture,0)})$fatal(1,"QDI_SEQUENCE_VALUE");',
              '$display("QDI_SEQUENCE:ACCEPTED");drive_zero=0;set_input();#(10*STEP);',
              f'if(({one}|{zero})!={output_mask}||{one}!=={ow}\'d{q.truth(fixture,0)}||!({input_ack})||total_deliveries!=0)$fatal(1,"{DIAGNOSTIC}");',
              '$display("QDI_SEQUENCE:SOURCE_SPACER_HELD");',
              ack_high + f'wait(({q.output_any(outgoing)})==0);wait(!({any_ack}));#STEP;',
              f'selected={1 if fixture in ("qdi_merge", "qdi_demux") else 0};drive_one={mask};set_input();#(10*STEP);',
              f'if(({q.output_any(outgoing)})!=0||({any_ack})||total_deliveries!=1)$fatal(1,"QDI_PENDING_OFFER_ACCEPTED");',
              '$display("QDI_SEQUENCE:NEXT_OFFER_BLOCKED");',
              ack_low + f'wait(({one}|{zero})=={output_mask});wait({input_ack});#STEP;',
              f'if({one}!=={ow}\'d{q.truth(fixture,mask)})$fatal(1,"QDI_SEQUENCE_VALUE");',
              ack_high + ' #STEP;drive_one=0;set_input();' + f'wait(({q.output_any(outgoing)})==0);wait(!({any_ack}));#STEP;' + ack_low + ' #STEP;',
              'if(total_deliveries!=2)$fatal(1,"QDI_SEQUENCE_ACTIVITY");', FINISH, DEADLINE]
    return "\n".join(lines), channels, overrides


def reset_bench(manifest, ports):
    q.check_fixture_shape("qdi_buffer", manifest)
    lines, roots, channels, overrides = q.setup(manifest, ports, 0)
    a, b = roots["in"], roots["out"]
    lines += ["initial begin " + START,
              f'{a["one"]}=5;{a["zero"]}=2;wait(({b["one"]}|{b["zero"]})==7);#1;{b["ack"]}=1;#1;',
              f'if({a["ack"]}||total_deliveries!=1)$fatal(1,"QDI_EARLY_RESET_NOT_REACHED");',
              '$display("QDI_SEQUENCE:DELIVERED_BEFORE_ACCEPTED");recover();',
              f'{a["one"]}=3;{a["zero"]}=4;wait({a["ack"]});#1;{b["ack"]}=1;#1;{a["one"]}=0;{a["zero"]}=0;',
              f'wait(({b["one"]}|{b["zero"]})==0);#1;{b["ack"]}=0;wait(!{a["ack"]});#STEP;',
              'if(total_deliveries!=2)$fatal(1,"QDI_SEQUENCE_ACTIVITY");', FINISH, DEADLINE]
    return "\n".join(lines), channels, overrides


def chain_bench(manifest, length, seed):
    q.check_fixture_shape("qdi_buffer", manifest)
    q.require(1 <= length <= 6, "QDI_CHAIN_LENGTH")
    lines = ["module QdiBench;timeunit 1fs;timeprecision 1fs;reg reset=1;integer trace,epoch=1;",
             f"wire [2:0] z[0:{length}],o[0:{length}];wire a[0:{length}];",
             "reg [2:0] input_zero=0,input_one=0;reg output_ack=0;assign z[0]=input_zero;assign o[0]=input_one;",
             f"assign a[{length}]=output_ack;integer accepted=0,delivered=0,sent=0,received=0;",
             "always @(posedge a[0])if(!reset)accepted++;always @(posedge output_ack)if(!reset)delivered++;"]
    overrides, channels = [], []
    for i in range(length):
        lines.append(f'{manifest["top"]} dut{i}(.reset(reset),.in_zero(z[{i}]),.in_one(o[{i}]),.in_ack(a[{i}]),.out_zero(z[{i+1}]),.out_one(o[{i+1}]),.out_ack(a[{i+1}]));')
        overrides += [line.replace("defparam dut.", f"defparam dut{i}.") for line in q.checked_overrides(manifest, (seed + 19 * i) % 2**32)]
    lines += overrides
    for i in range(length + 1):
        name = f"Chain::boundary{i}"
        channels.append(dict(id=name, local_id=f"boundary{i}", root=i in (0, length), role="input" if i == 0 else "output",
                             protocol="dual-rail-rtz-v1", width=3))
        lines += [f'integer complete_{i}=0;always @(posedge a[{i}])if(!reset)complete_{i}++;',
                  f'always @(reset or a[{i}] or o[{i}] or z[{i}])if(trace)$fstrobe(trace,"E|%0d|1|%0b|{name}|0|%0b|%0h|%0h",$time,reset,a[{i}],o[{i}],z[{i}]);']
    lines += ["task snapshot;begin", *[f'$fdisplay(trace,"C|1|Chain::boundary{i}|%0d",complete_{i});' for i in range(length+1)],
              'end endtask', 'initial begin trace=$fopen("trace.txt","w");$fdisplay(trace,"QDI_TRACE|1");#1000000000;reset=0;#1000000000;fork',
              'begin for(sent=0;sent<64;sent++)begin input_one=sent%8;input_zero=7^(sent%8);wait(a[0]);#1;input_zero=0;input_one=0;wait(!a[0]);#1;end end',
              f'begin #1000000000;if(accepted!={(length+1)//2}||delivered!=0)$fatal(1,"QDI_CHAIN_CAPACITY");',
              '$display("QDI_SEQUENCE_CAPACITY:%0d",accepted);',
              f'for(received=0;received<64;received++)begin wait((z[{length}]|o[{length}])==7);if(o[{length}]!==(received%8))$fatal(1,"QDI_SEQUENCE_VALUE");#1;output_ack=1;wait((z[{length}]|o[{length}])==0);#1;output_ack=0;end end',
              'join #1000000000;if(accepted!=64||delivered!=64)$fatal(1,"QDI_SEQUENCE_ACTIVITY");', FINISH, DEADLINE]
    return "\n".join(lines), channels, overrides


def remove_sink_reservation(manifest, sources):
    """Replace the sink-ack input by duplicated input completion in six rail cells.

    This preserves the initial token, but its rails incorrectly return as soon as
    the source returns spacer, even though the receiver has not acknowledged.
    """
    selected = dict(sources)
    path = manifest["top"] + ".sv"
    text = selected[path]
    cells = [p for p in manifest["design"]["primitives"] if re.fullmatch(r"strong_(zero|one)[0-2]", p["id"])]
    q.require(len(cells) == 6, "QDI_RESERVATION_MUTATION_TARGET")
    for cell in cells:
        instance = re.escape(cell["rtl_path"].rsplit(".", 1)[-1])
        pattern = r"(" + instance + r"\s*\([\s\S]*?\.common\s*\(\{)out_ack,\s*(\w+)(,)"
        text, count = re.subn(pattern, lambda m: m[1] + "~" + m[2] + ", " + m[2] + m[3], text, count=1)
        q.require(count == 1, "QDI_RESERVATION_MUTATION_TARGET")
    selected[path] = text
    return selected


def expected_counts(spec, channels):
    counts = {}
    for c in channels:
        if not c["root"]: continue
        amount = 64 if spec["kind"] == "chain" else 2
        if spec["kind"] == "reset" and c["role"] == "input": amount = 1
        if spec["fixture"] == "qdi_demux" and c["role"] == "output": amount = 1
        if spec["fixture"] == "qdi_merge" and c["role"] == "input": amount = 1
        counts[c["id"]] = amount
    return counts


def check_ledger(spec, channels, ledger):
    q.require(not ledger.resetting and all(m.idle() for m in ledger.monitors.values()), "QDI_SEQUENCE_NOT_IDLE")
    q.require(not ledger.pending and not any(ledger.queues.values()) and not sum(ledger.aborted.values()), "QDI_SEQUENCE_CONSERVATION")
    epochs = {1, 2} if spec["kind"] == "reset" else {1}
    q.require(ledger.epochs == epochs, "QDI_SEQUENCE_EPOCHS")
    expected = expected_counts(spec, channels)
    actual = dict(ledger.completed) | dict(ledger.delivered)
    q.require(actual == expected, "QDI_SEQUENCE_ACTIVITY")
    expected_offers = {c["id"]: 2 if spec["kind"] == "reset" else expected[c["id"]] for c in channels if c["root"] and c["role"] == "input"}
    q.require(dict(ledger.offered) == expected_offers, "QDI_SEQUENCE_OFFERS")
    witnesses = {(epoch, c["id"]): ledger.counts[(epoch, c["id"])] for epoch in epochs for c in channels}
    q.require(ledger.witnesses == witnesses, "QDI_SEQUENCE_WITNESSES")
    q.require(all(sum(ledger.counts[(e, c["id"])] for e in epochs) > 0 for c in channels), "QDI_SEQUENCE_BOUNDARY_ACTIVITY")
    if spec["kind"] == "chain":
        q.require(all(ledger.counts[(1, c["id"])] == 64 for c in channels), "QDI_SEQUENCE_CHAIN_ACTIVITY")
    return dict(offered=dict(ledger.offered), accepted=dict(ledger.completed), delivered=dict(ledger.delivered),
                aborted=dict(ledger.aborted), epochs=sorted(epochs),
                completions={f"{e}:{n}": count for (e, n), count in ledger.counts.items()})


def check_log(spec, code, log):
    fatals = re.findall(r"^FATAL: [^\n]*?: (\w+)", log, re.M)
    markers = re.findall(r"^QDI_SEQUENCE:(\w+)$", log, re.M)
    if spec.get("mutant"):
        q.require(code == 1 and fatals == [DIAGNOSTIC] and markers == ["ACCEPTED"], "QDI_SEQUENCE_WRONG_REJECTION")
    else:
        q.require(code == 0 and not fatals and log.splitlines().count("QDI_SEQUENCE_PASS") == 1, "QDI_SEQUENCE_SIMULATION")
        expected = ["ACCEPTED", "SOURCE_SPACER_HELD", "NEXT_OFFER_BLOCKED"] if spec["kind"] == "source" else ["DELIVERED_BEFORE_ACCEPTED"] if spec["kind"] == "reset" else []
        q.require(markers == expected, "QDI_SEQUENCE_MARKERS")
        capacities = re.findall(r"^QDI_SEQUENCE_CAPACITY:(\d+)$", log, re.M)
        q.require(capacities == ([str((spec["length"]+1)//2)] if spec["kind"] == "chain" else []), "QDI_SEQUENCE_CAPACITY_EVIDENCE")


def audit_case(row, directory, channels):
    q.require(q.read(directory / "case.json") == row, "QDI_SEQUENCE_CASE_SUMMARY")
    q.require(row["status"] == ("EXPECTED_REJECTION" if row["spec"].get("mutant") else "PASS"), "QDI_SEQUENCE_CASE_STATUS")
    q.require({"bench.sv", "compile.log", "simulation.log", "trace.txt"} < set(row["hashes"]), "QDI_SEQUENCE_ARTIFACT_INVENTORY")
    for name, digest in row["hashes"].items():
        q.require(q.sha(directory / name) == digest, "QDI_SEQUENCE_ARTIFACT_HASH")
    log = (directory / "simulation.log").read_text(encoding="utf-8")
    check_log(row["spec"], row["exit_code"], log)
    if not row["spec"].get("mutant"):
        ledger = q.replay(row["spec"]["fixture"], channels, directory / "trace.txt", complete=False)
        q.require(check_ledger(row["spec"], channels, ledger) == row["evidence"], "QDI_SEQUENCE_REPLAY_SUMMARY")
    else:
        q.require(row["evidence"] == {"diagnostic": DIAGNOSTIC}, "QDI_SEQUENCE_CONTROL_SUMMARY")


def execute(spec, manifest, ports, sources, directory):
    directory.mkdir(parents=True, exist_ok=False)
    text, channels, overrides = (chain_bench(manifest, spec["length"], spec["seed"]) if spec["kind"] == "chain" else
                                reset_bench(manifest, ports) if spec["kind"] == "reset" else
                                source_bench(spec["fixture"], manifest, ports, spec["seed"]))
    selected = remove_sink_reservation(manifest, sources) if spec.get("mutant") else sources
    (directory / "bench.sv").write_text(text, encoding="utf-8")
    for name, body in selected.items(): (directory / name).write_text(body, encoding="utf-8")
    command = ["iverilog", "-g2012", "-s", "QdiBench", "-o", str(directory / "sim.vvp"),
               str(directory / "bench.sv"), *(str(directory / name) for name in selected)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    (directory / "compile.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    q.require(result.returncode == 0, "QDI_SEQUENCE_COMPILE: " + result.stderr)
    result = subprocess.run(["vvp", str(directory / "sim.vvp")], cwd=directory, capture_output=True, text=True, timeout=60)
    log = result.stdout + result.stderr
    (directory / "simulation.log").write_text(log, encoding="utf-8")
    check_log(spec, result.returncode, log)
    evidence = {"diagnostic": DIAGNOSTIC} if spec.get("mutant") else check_ledger(spec, channels, q.replay(spec["fixture"], channels, directory / "trace.txt", complete=False))
    row = dict(spec=spec, status="EXPECTED_REJECTION" if spec.get("mutant") else "PASS", evidence=evidence,
               overrides=overrides, compile=command, exit_code=result.returncode,
               hashes={name: q.sha(directory / name) for name in [*selected, "bench.sv", "compile.log", "simulation.log", "trace.txt"]})
    q.write(directory / "case.json", row)
    audit_case(row, directory, channels)
    return row


def selection(seeds):
    return ([dict(kind="source", fixture=f, seed=s, id=f"{f}_{s}") for f in FIXTURES for s in seeds] +
            [dict(kind="chain", fixture="qdi_buffer", seed=s, length=n, id=f"chain{n}_{s}") for n in range(1, 7) for s in seeds] +
            [dict(kind="reset", fixture="qdi_buffer", seed=0, id="delivered_before_accepted")])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generated", type=Path, default=q.ROOT / "target/generated")
    parser.add_argument("--output", type=Path, default=q.ROOT / "target/verification/qdi-sequences")
    parser.add_argument("--seeds", type=int, nargs="+", default=[17, 101])
    args = parser.parse_args()
    q.require(not sys.flags.optimize and not os.environ.get("PYTHONOPTIMIZE"), "QDI_ASSERTIONS_DISABLED")
    q.require(args.seeds and len(set(args.seeds)) == len(args.seeds) and all(0 <= s < 2**32 for s in args.seeds), "QDI_SEED_SELECTION")
    out = args.output.resolve()
    q.require(not out.exists(), "QDI_SEQUENCE_OUTPUT_EXISTS: use a fresh directory; failed attempts are retained")
    out.mkdir(parents=True)
    selected = selection(args.seeds)
    controls = [dict(kind="source", fixture="qdi_buffer", seed=0, mutant=m, id="reservation_" + ("mutant" if m else "baseline")) for m in (False, True)]
    report = dict(status="RUNNING", scope="finite atomic-cell digital sequences; ideal forks; no physical QDI claim",
                  selected=selected, selected_controls=controls, cases=[], controls=[], exports={},
                  checker_sha256={p.name: q.sha(p) for p in (Path(__file__), Path(q.__file__), q.ROOT / "verification/phase_reference.py", q.ROOT / "verification/run_phase.py", q.ROOT / "tools/check_export.py")})
    q.write(out / "report.json", report)
    try:
        report.update(q.identity())
        exports = {}
        for fixture in FIXTURES:
            copied = out / "generated" / fixture
            shutil.copytree(args.generated.resolve() / fixture, copied)
            report["exports"][fixture] = q.validate_export(copied)
            exports[fixture] = (q.read(copied / "contract.json")["manifest"], q.read(copied / "ports.json")["nodes"][0]["ports"],
                                {p.name: p.read_text(encoding="utf-8") for p in q.read_sources(copied)})
        for specs, key in ((selected, "cases"), (controls, "controls")):
            for spec in specs:
                report[key].append(execute(spec, *exports[spec["fixture"]], out / spec["id"]))
                q.write(out / "report.json", report)
        q.require([r["spec"] for r in report["cases"]] == selected and [r["spec"] for r in report["controls"]] == controls, "QDI_SEQUENCE_INVENTORY")
        baseline, mutant = report["controls"]
        q.require(baseline["hashes"]["bench.sv"] == mutant["hashes"]["bench.sv"], "QDI_SEQUENCE_CONTROL_BENCH")
        report["status"] = "PASS"
    except BaseException as error:
        report.update(status="ERROR", error=str(error))
        q.write(out / "report.json", report)
        raise
    q.write(out / "report.json", report)
    print(f'QDI sequences: {len(report["cases"])} cases and paired reservation control PASS', flush=True)


if __name__ == "__main__": main()
