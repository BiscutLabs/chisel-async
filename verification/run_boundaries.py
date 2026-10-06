# SPDX-License-Identifier: Apache-2.0
"""CA-09: actual exported RTL, independent byte-memory oracle, and exact fault controls."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

from run import ROOT, read_sources
sys.path.insert(0, str(ROOT / "tools"))
from check_export import validate_export
from run_architecture import execute as architecture_execute

FIXTURES = {"memory_ram": "MemoryRamExample", "memory_rom": "MemoryRomExample",
            "pending_events": "PendingEventsExample", "memory_port": "AsyncMemoryPort"}


def require(ok, diagnostic):
    if not ok:
        raise ValueError(diagnostic)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_memory(log, rom):
    """Reference is a byte array and transaction ledger, not RTL state equations."""
    memory = [None] * 32
    if rom:
        memory = [b for i in range(16) for b in (((i * 0x1235 + 0x5a3c) & 255),
                                               ((i * 0x1235 + 0x5a3c) >> 8) & 255)]
    pending = None
    accepted = delivered = effects = expected_effects = aborted = resets = 0
    effect_due = False
    for line in log.splitlines():
        if not line.startswith("BND "):
            continue
        words = line.split()[1:]
        kind = words[0]
        require(kind == "W" or not effect_due, "MEMORY_MISSING_EFFECT")
        if kind == "A":
            require(pending is None, "MEMORY_CAPACITY")
            require(len(words) == 5 and all(w.isdecimal() for w in words[1:]), "MEMORY_TRACE")
            write, address, data, mask = map(int, words[1:])
            require(write in (0, 1) and 0 <= address < 64 and 0 <= data < 65536 and 0 <= mask < 4, "MEMORY_TRACE")
            error = address % 2 != 0 or address >= 32 or rom and write
            value = 0
            if not error:
                if write:
                    for byte in range(2):
                        if mask & (1 << byte):
                            memory[address + byte] = (data >> (byte * 8)) & 255
                    effect_due = bool(mask)
                    expected_effects += effect_due
                else:
                    require(all(b is not None for b in memory[address:address+2]), "MEMORY_UNINITIALIZED_READ")
                    value = memory[address] + 256 * memory[address+1]
            pending = value, int(error)
            accepted += 1
        elif kind == "W":
            require(words == ["W"] and effect_due, "MEMORY_EXTRA_EFFECT")
            effects += 1
            effect_due = False
        elif kind == "D":
            require(len(words) == 3 and all(w.isdecimal() for w in words[1:]), "MEMORY_TRACE")
            require(pending is not None, "MEMORY_UNSOLICITED")
            require(tuple(map(int, words[1:])) == pending, "MEMORY_PAYLOAD")
            delivered += 1
            pending = None
        elif kind == "R":
            require(words == ["R", str(int(pending is not None))], "MEMORY_RESET_ACCOUNTING")
            aborted += pending is not None
            pending = None
            resets += 1
        else:
            raise ValueError("MEMORY_TRACE")
    require(not effect_due and pending is None and accepted == delivered + aborted and effects == expected_effects,
            "MEMORY_ACCOUNTING")
    require((accepted, delivered, aborted, resets) == (164, 162, 2, 7), "MEMORY_ACTIVITY")
    marker = f"BOUNDARY_PASS memory accepted={accepted} delivered={delivered} effects={effects} resets={resets}"
    require(log.splitlines().count(marker) == 1, "MEMORY_SUMMARY")
    return dict(accepted=accepted, delivered=delivered, aborted=aborted, effects=effects, resets=resets)


def audit_events(log):
    events = [line for line in log.splitlines() if line.startswith("BND ")]
    deliveries = [int(line[6:]) for line in events if re.fullmatch(r"BND D [0-9]+", line)]
    require(deliveries == list(range(1, 16)) + [5, 1, 7, 2, 8, 1, 2, 15, 4], "EVENT_PAYLOAD")
    require(events.count("BND S") == 25 and events.count("BND R") == 3, "EVENT_ACTIVITY")
    require(len(events) == 52, "EVENT_TRACE")
    require(log.splitlines().count("BOUNDARY_PASS events delivered=24 snapshots=25 resets=3") == 1, "EVENT_SUMMARY")
    return dict(delivered=24, snapshots=25, resets=3)


def probe(directory, top, endpoint):
    text = (directory / f"ref_{top}.sv").read_text()
    name = f"ref_{top}_ca_p_" + "_".join(f"{len(part)}_{part}" for part in endpoint.split("/"))
    matches = re.findall(r"^`define " + re.escape(name) + r" (\S+)$", text, re.M)
    require(len(matches) == 1, "BOUNDARY_PROBE")
    # Paths come only from the compiler ABI already verified by validate_export.
    return "dut." + matches[0]


def execute(name, sources, bench, output, parameters, oracle, diagnostic=None):
    directory = output / name
    directory.mkdir(parents=True)
    path = directory / "bench.sv"
    path.write_text(bench, encoding="utf-8")
    executable = directory / "bench.vvp"
    command = ["iverilog", "-g2012", "-s", "BoundaryBench", *parameters, "-o", str(executable), str(path), *map(str, sources)]
    build = subprocess.run(command, capture_output=True, text=True, timeout=30)
    (directory / "compile.log").write_text(build.stdout + build.stderr, encoding="utf-8")
    require(build.returncode == 0, "BOUNDARY_COMPILE")
    result = subprocess.run(["vvp", str(executable)], cwd=directory, capture_output=True, text=True, timeout=30)
    log = result.stdout + result.stderr
    (directory / "simulation.log").write_text(log, encoding="utf-8")
    fatals = re.findall(r"^FATAL: [^\n]*?: (\w+)", log, re.M)
    actual = None
    activity = None
    if result.returncode:
        require(result.returncode == 1 and len(fatals) == 1, "BOUNDARY_SIMULATION")
        actual = fatals[0]
    else:
        require(not fatals, "BOUNDARY_SIMULATION")
        try:
            activity = oracle(log)
        except ValueError as error:
            actual = str(error)
    require(actual == diagnostic, f"BOUNDARY_WRONG_RESULT:{name}:{actual}:expected={diagnostic}")
    record = dict(case=name, status="EXPECTED_REJECTION" if diagnostic else "PASS", diagnostic=diagnostic,
                  activity=activity, compile=command, files={p.name: sha(p) for p in directory.iterdir() if p.is_file()},
                  sources={p.name: sha(p) for p in sources})
    (directory / "case.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


def mutate(sources, filename, pattern, replacement, destination):
    original = next(p for p in sources if p.name == filename)
    changed, count = re.subn(pattern, replacement, original.read_text())
    require(count == 1, "BOUNDARY_MUTATION_TARGET")
    destination.write_text(changed, encoding="utf-8")
    return [destination if p == original else p for p in sources]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generated", type=Path, default=ROOT / "target/generated")
    parser.add_argument("--output", type=Path, default=ROOT / "target/verification/boundaries")
    parser.add_argument("--quick", action="store_true", help="Four phase points per fixture; all controls retained")
    args = parser.parse_args()
    output = args.output.resolve()
    # Retain prior evidence; a repeated invocation must choose a new directory.
    output.mkdir(parents=True, exist_ok=False)
    report = output / "report.json"
    record = dict(status="RUNNING", platform=platform.platform(), cases=[], exports={},
                  checker_sha256=sha(Path(__file__)), benches={p.name: sha(p) for p in (ROOT / "verification/boundaries").glob("*.sv")},
                  rom_image_sha256=hashlib.sha256(b"".join(((i * 0x1235 + 0x5a3c) & 65535).to_bytes(2, "little") for i in range(16))).hexdigest())
    def save(): report.write_text(json.dumps(record, indent=2) + "\n")
    save()
    try:
        sources, benches = {}, {}
        for fixture, top in FIXTURES.items():
            directory = output / "exports" / fixture
            shutil.copytree(args.generated.resolve() / fixture, directory)
            record["exports"][fixture] = validate_export(directory)
            sources[fixture] = read_sources(directory)
            if fixture == "memory_port":
                continue
            bench = (ROOT / "verification/boundaries" / ("events.sv" if fixture == "pending_events" else "memory.sv")).read_text()
            bench = bench.replace("TOP", top)
            def fire(path):
                return "(" + probe(directory, top, path + "_valid") + " & " + probe(directory, top, path + "_ready") + ")"
            if fixture == "pending_events":
                bench = bench.replace("SNAPSHOT", fire("sender/in"))
            else:
                bench = bench.replace("BACKEND_FIRE", fire("port/backendRequest"))
                bench = bench.replace("WRITE_COMMIT", "1'b0" if fixture == "memory_rom" else
                                      "(dut.memory_ext.RW0_en & dut.memory_ext.RW0_wmode & |dut.memory_ext.RW0_wmask)")
            benches[fixture] = bench
        points = [(half, phase) for half in (3, 5, 7, 11) for phase in (0, 1, half-1, half, 2*half-1)]
        if args.quick:
            points = [(3, 0), (5, 1), (7, 7), (11, 21)]
        for fixture in benches:
            oracle = audit_events if fixture == "pending_events" else lambda log, f=fixture: audit_memory(log, f == "memory_rom")
            for half, phase in points:
                params = [f"-PBoundaryBench.HALF={half}", f"-PBoundaryBench.PHASE={phase}"]
                name = f"{fixture}_{half}_{phase}"
                record["cases"].append(execute(name, sources[fixture], benches[fixture], output, params, oracle))
        # Actual RTL faults paired with the same positive bench and oracle.
        faults = [
            ("memory_ram", "response_corruption", "MemoryRamExample.sv", r"assign response_bits_data = ([^;]+);", r"assign response_bits_data = \1 ^ 16'h1;", "MEMORY_PAYLOAD"),
            ("memory_ram", "wrong_byte_mask", "MemoryRamExample.sv", r"\.RW0_wmask \(_ca_child_port_backendRequest_bits_mask\)", ".RW0_wmask ({_ca_child_port_backendRequest_bits_mask[0], _ca_child_port_backendRequest_bits_mask[1]})", "MEMORY_PAYLOAD"),
            ("memory_ram", "held_request_reexecutes", "MemoryRamExample.sv", r"\.RW0_en\s+\([\s\S]*?\),", ".RW0_en (request_req),", "MEMORY_EXTRA_EFFECT"),
            ("pending_events", "clear_wins", "PendingEventsExample.sv", r"pending <=\s+\([^;]+;", "pending <= (_ca_child_sender_in_ready & ca_child_sender_in_valid) ? 4'h0 : (pending | (sampled & ~previous));", "EVENT_MISSING"),
            ("pending_events", "ack_clears_new_events", "PendingEventsExample.sv", r"pending <=\s+\([^;]+;", "pending <= out_ack ? 4'h0 : (((_ca_child_sender_in_ready & ca_child_sender_in_valid) ? 4'h0 : pending) | (sampled & ~previous));", "EVENT_MISSING"),
        ]
        for fixture, name, filename, pattern, replacement, diagnostic in faults:
            mutant = mutate(sources[fixture], filename, pattern, replacement, output / (name + ".sv"))
            oracle = audit_events if fixture == "pending_events" else lambda log: audit_memory(log, False)
            record["cases"].append(execute(name, mutant, benches[fixture], output, [], oracle, diagnostic))
        # Expand existing two-clock/reset/backpressure campaign with deterministic
        # ratios and phase offsets; preserve its exact 144-delivery/2-abort oracle.
        trip_dir = output / "exports/bridge_roundtrip"
        shutil.copytree(args.generated.resolve() / "bridge_roundtrip", trip_dir)
        record["exports"]["bridge_roundtrip"] = validate_export(trip_dir)
        trip = (ROOT / "verification/architecture/roundtrip.sv").read_text()
        ratios = [(3, 17), (17, 3), (5, 5), (7, 11)]
        for source, sink in ratios:
            for phase in ((0,) if args.quick else (0, 1, sink-1, sink, 2*sink-1)):
                name = f"clock_phase_{source}_{sink}_{phase}"
                params = [f"-PArchitectureBench.{key}={value}" for key, value in (("SOURCE_HALF",source),("SINK_HALF",sink),("SINK_PHASE",phase))]
                # Move assertion/release relative to both clocks, without altering
                # its reset protocol or oracle.
                bench = trip.replace("#1;initialize();", f"#{phase+0.137};initialize();")
                record["cases"].append(architecture_execute(name, read_sources(trip_dir), bench, output/name, params))
        record["status"] = "PASS"
    except BaseException as error:
        record.update(status="ERROR", error=str(error))
        save()
        raise
    save()
    print(f"Boundaries PASS: {len(record['cases'])} cases; {report}")


if __name__ == "__main__":
    main()
