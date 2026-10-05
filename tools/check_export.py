# SPDX-License-Identifier: Apache-2.0
"""Resolve the qualified export through Icarus elaboration and active RTL anchor probes.

The VVP reader accepts the pinned Icarus 13 module/port/parameter format, not arbitrary
SystemVerilog syntax. Actual compilation rejects unbound instances and duplicate views.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "verification"))
from run import read_sources

OPTIONS = ["-O=debug", "--no-dedup", "--preserve-values=named", "--strip-fir-debug-info",
           "--lowering-options=disallowPortDeclSharing"]
IDENT = r"[A-Za-z_][A-Za-z0-9_]*"


def require(condition, diagnostic):
    if not condition:
        raise ValueError(diagnostic)


def shape(value, fields):
    require(type(value) is dict and set(value) == set(fields.split()), "UNSUPPORTED_CONTRACT_FIELDS")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def semantic_hash(manifest):
    return sha(json.dumps(manifest, separators=(",", ":"), ensure_ascii=False).encode())


def rtl_hash(source):
    # Remove only firtool's tab-prefixed source-location comments and trailing whitespace.
    return sha(("\n".join(line.split("\t//", 1)[0].rstrip() for line in source.read_text().splitlines()).rstrip() + "\n").encode())


def unique_json(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def nodes(node):
    yield node
    for child in node["children"]:
        yield from nodes(child["contract"])


def validate_manifest(document):
    shape(document, "semantic_sha256 manifest")
    manifest = document["manifest"]
    shape(manifest, "schema time_unit time_range top toolchain resources rtl_semantic_sha256 design")
    require(document["semantic_sha256"] == semantic_hash(manifest), "SEMANTIC_HASH_MISMATCH")
    require(manifest["schema"] == "chisel-async-contract-v1" and manifest["time_unit"] == "fs"
            and manifest["time_range"] == "0..9223372036854775807", "UNSUPPORTED_SCHEMA")
    require(manifest["toolchain"] == {"chisel": "7.16.0", "scala": "2.13.18", "firtool": "1.160.0", "options": OPTIONS},
            "UNQUALIFIED_COMPILER")
    require(re.fullmatch(IDENT, manifest["top"]), "INVALID_TOP")
    require(manifest["design"]["rtl_path"] == manifest["top"], "TOP_PATH_MISMATCH")
    all_paths, resources = set(), set()
    domain = manifest["design"]["reset_domain"]
    for node in nodes(manifest["design"]):
        shape(node, "rtl_path module reset_domain capacity endpoints channels primitives timing children")
        require(node["reset_domain"] == domain, "RESET_DOMAIN_MISMATCH")
        require(node["capacity"] is None or type(node["capacity"]) is int and node["capacity"] > 0, "INVALID_CAPACITY")
        ids = [item["id"] for group in ("endpoints", "channels", "primitives", "timing", "children")
               for item in node[group]]
        require(len(ids) == len(set(ids)), "DUPLICATE_SEMANTIC_ID")
        require(all(re.fullmatch(IDENT, item) for item in ids), "INVALID_SEMANTIC_ID")
        path = node["rtl_path"]
        require(re.fullmatch(IDENT + r"(?:\." + IDENT + ")*", path), "INVALID_RTL_PATH")
        require(path not in all_paths, "AMBIGUOUS_RTL_PATH")
        all_paths.add(path)
        endpoints = {item["id"]: item for item in node["endpoints"]}
        for item in endpoints.values():
            shape(item, "id rtl_path width source")
            require(item["rtl_path"].startswith(path + ".") and
                    re.fullmatch(IDENT, item["rtl_path"][len(path) + 1:]), "INVALID_ENDPOINT_PATH")
            require(item["rtl_path"] not in all_paths, "AMBIGUOUS_RTL_PATH")
            all_paths.add(item["rtl_path"])
            require(type(item["width"]) is int and item["width"] > 0, "INVALID_ENDPOINT_WIDTH")
        for channel in node["channels"]:
            shape(channel, "id protocol role request data acknowledge reset_domain layout phases environment")
            require(channel["reset_domain"] == domain, "RESET_DOMAIN_MISMATCH")
            require(channel["protocol"] == "four-phase-bundled-v1" and
                    channel["role"] in ("input", "output") and
                    channel["phases"] == ["00", "10", "11", "01", "00"], "INVALID_CHANNEL")
            require(all(channel[ref] in endpoints for ref in ("request", "data", "acknowledge")),
                    "MISSING_CHANNEL_ENDPOINT")
            offset = 0
            for field in channel["layout"]:
                shape(field, "field lsb width signed source")
                require(type(field["signed"]) is bool, "INVALID_PAYLOAD_LAYOUT")
                require(field["lsb"] == offset and type(field["width"]) is int and field["width"] > 0,
                        "INVALID_PAYLOAD_LAYOUT")
                offset += field["width"]
            require(offset == endpoints[channel["data"]]["width"], "INVALID_PAYLOAD_LAYOUT")
        for primitive in node["primitives"]:
            shape(primitive, "id rtl_path model view version resource parameters reset reset_domain effects ports")
            require(len({p["name"] for p in primitive["ports"]}) == len(primitive["ports"]), "DUPLICATE_PRIMITIVE_PORT")
            for port in primitive["ports"]:
                shape(port, "name width direction")
                require(type(port["width"]) is int and port["width"] > 0 and port["direction"] in ("input", "output"),
                        "INVALID_PRIMITIVE_PORT")
            require(all(type(v) is str and re.fullmatch(r"-?[0-9]+", v) for v in primitive["parameters"].values()),
                    "INVALID_PRIMITIVE_PARAMETER")
            require(primitive["reset_domain"] == domain, "RESET_DOMAIN_MISMATCH")
            require(primitive["reset"] in endpoints and endpoints[primitive["reset"]]["width"] == 1,
                    "MISSING_RESET_ENDPOINT")
            require(primitive["view"] == "behavioral" and primitive["version"] == 1, "INVALID_VIEW")
            require(re.fullmatch(r"ChiselAsync[A-Za-z0-9]+_v1", primitive["model"]), "INVALID_MODEL")
            require(primitive["resource"] == f'chiselasync/sv/{primitive["model"]}.sv', "INVALID_RESOURCE")
            require(primitive["rtl_path"].startswith(path + ".") and
                    re.fullmatch(IDENT, primitive["rtl_path"][len(path) + 1:]), "INVALID_PRIMITIVE_PATH")
            require(primitive["rtl_path"] not in all_paths, "AMBIGUOUS_RTL_PATH")
            all_paths.add(primitive["rtl_path"])
            resources.add(primitive["resource"])
        for timing in node["timing"]:
            shape(timing, "id kind launch transaction data_valid capture captured setup_fs hold_fs mode provenance pulse_policy")
            require(timing["kind"] == "bundled-setup-hold-v1" and timing["mode"] == "digital-model",
                    "UNSUPPORTED_TIMING")
            require(all(timing[ref] in endpoints for ref in
                        ("launch", "transaction", "data_valid", "capture", "captured")), "MISSING_TIMING_ENDPOINT")
            for name in ("setup_fs", "hold_fs"):
                require(type(timing[name]) is str and re.fullmatch(r"0|[1-9][0-9]*", timing[name])
                        and int(timing[name]) <= 2**63 - 1, "INVALID_MODEL_TIME")
        for child in node["children"]:
            shape(child, "id contract")
    require(resources == set(manifest["resources"]), "RESOURCE_INVENTORY_MISMATCH")
    return manifest


def read_vvp(contents):
    require(':ivl_version "13.0 ' in contents, "UNQUALIFIED_SIMULATOR")
    scopes, paths, current = {}, {}, None
    for line in contents.splitlines():
        scope = re.match(r'(S_\w+) \.scope (\w+), "([^"\\]+)" "([^"\\]+)" (.*);$', line)
        if scope:
            key, kind, name, model, tail = scope.groups()
            parent = re.search(r", (S_\w+)$", tail)
            parent_path = scopes[parent[1]]["path"] + "." if parent else ""
            current = {"path": parent_path + name, "kind": kind, "model": model, "ports": {}, "parameters": {}}
            require(key not in scopes and current["path"] not in paths, "AMBIGUOUS_ELABORATED_SCOPE")
            scopes[key] = paths[current["path"]] = current
        elif ".scope " in line and not line.lstrip().startswith(".scope"):
            raise ValueError("UNSUPPORTED_ELABORATED_SCOPE")
        port = re.match(r'\s*\.port_info \d+ /(INPUT|OUTPUT|INOUT) (\d+) "(' + IDENT + r')";', line)
        if port and current:
            direction, width, name = port.groups()
            require(name not in current["ports"], "AMBIGUOUS_ELABORATED_PORT")
            current["ports"][name] = {"name": name, "direction": direction.lower(), "width": int(width)}
        param = re.match(r'P_\w+ \.param/l "(' + IDENT + r')" 0 \d+ \d+, (\+?)C4<([01]+)>;', line)
        if param and current:
            name, signed, bits = param.groups()
            number = int(bits, 2)
            if signed and bits[0] == "1":
                number -= 2**len(bits)
            current["parameters"][name] = str(number)
    return {path: scope for path, scope in paths.items() if scope["kind"] == "module"}


def source_path(node, target):
    # Qualified mode preserves flattened ports/values; unsupported source forms fail closed.
    require(target.count(">") == 1 and target.startswith(f'~|{node["module"]}>'), "UNSUPPORTED_SOURCE_TARGET")
    field = target.split(">")[1]
    require(re.fullmatch(IDENT + r"(?:\." + IDENT + r"|\[[0-9]+\])*", field), "UNSUPPORTED_SOURCE_TARGET")
    return node["rtl_path"] + "." + field.replace(".", "_").replace("[", "_").replace("]", "")


def probe_source(manifest, scopes):
    top = manifest["top"]
    lines = ["module ContractProbe; timeunit 1fs; timeprecision 1fs;"]
    comparisons, coverage, drivers = [], [], []
    for node in nodes(manifest["design"]):
        comparisons.append(f'if ({node["rtl_path"]}.reset !== {top}.reset) $fatal(1, "RESET_BINDING_MISMATCH");')
        layouts = {ch["data"]: ch["layout"] for ch in node["channels"]}
        for endpoint in node["endpoints"]:
            fields = layouts.get(endpoint["id"], [{"source": endpoint["source"], "lsb": 0, "width": endpoint["width"]}])
            expr = "{" + ", ".join(source_path(node, f["source"]) for f in reversed(fields)) + "}"
            path, width, index = endpoint["rtl_path"], endpoint["width"], len(coverage)
            lines.append(f"reg [{width-1}:0] ones_{index}=0, zeros_{index}=0;")
            comparisons.append(f'if ({path} !== {expr}) $fatal(1, "ENDPOINT_MAPPING_MISMATCH:{path}");')
            for bit in range(width):
                value = path if width == 1 else f"{path}[{bit}]"
                comparisons += [f"if ({value} === 1'b1) ones_{index}[{bit}] = 1'b1;",
                                f"if ({value} === 1'b0) zeros_{index}[{bit}] = 1'b1;"]
            coverage.append(f"if (ones_{index} !== {width}'h{(1<<width)-1:x} || "
                            f"zeros_{index} !== {width}'h{(1<<width)-1:x}) "
                            f'$fatal(1, "INACTIVE_ENDPOINT:{path}");')
        if node["rtl_path"] == top:
            drivers += [(top + "." + name, p["width"])
                        for name, p in scopes[top]["ports"].items() if p["direction"] == "input"]
        for primitive in node["primitives"]:
            drivers += [(primitive["rtl_path"] + "." + p["name"], p["width"])
                        for p in primitive["ports"] if p["direction"] == "output"]
            reset_endpoint = next(e for e in node["endpoints"] if e["id"] == primitive["reset"])
            comparisons.append(f'if ({primitive["rtl_path"]}.reset !== {reset_endpoint["rtl_path"]} || '
                               f'{reset_endpoint["rtl_path"]} !== {node["rtl_path"]}.reset) '
                               '$fatal(1, "RESET_BINDING_MISMATCH");')
    lines += ["task check; begin", *comparisons, "end endtask", "initial begin",
              f"force {top}.reset = 1'b1; #1;"]
    checks = 0
    for src, width in drivers:
        for bit in range(width):
            for value in (1 << bit, ((1 << width) - 1) ^ (1 << bit)):
                lines += [f"force {src} = {width}'h{value:x};", "#1; check;"]
                checks += len(coverage)
        lines += [f"release {src};", f"force {top}.reset = 1'b1; #1;"]
    lines += coverage
    lines += [f'$display("CONTRACT_PROBES_PASS:{checks}"); $finish; end endmodule']
    return "\n".join(lines), checks


def validate_export(directory: Path):
    directory = directory.resolve()
    output = directory / "resolved.json"
    output.write_text('{"status":"RUNNING"}\n', encoding="utf-8")
    document = json.loads((directory / "contract.json").read_text(), object_pairs_hook=unique_json)
    manifest = validate_manifest(document)
    sources = read_sources(directory)
    require(manifest["rtl_semantic_sha256"] == {s.name: rtl_hash(s) for s in sources}, "RTL_HASH_MISMATCH")
    for source in sources:
        require(source.read_text().startswith("// Generated by CIRCT firtool-1.160.0\n"), "UNQUALIFIED_RTL")
    for resource, expected in manifest["resources"].items():
        matches = [source for source in sources if source.name == Path(resource).name]
        require(len(matches) == 1, "MISSING_OR_AMBIGUOUS_RESOURCE")
        content = matches[0].read_text().split("\n", 1)[1].rstrip() + "\n"
        require(sha(content.encode()) == expected, "RESOURCE_HASH_MISMATCH")
    command = ["iverilog", "-g2012", "-s", manifest["top"], "-o", "contract_probe.vvp",
               *(str(source) for source in sources)]
    built = subprocess.run(command, cwd=directory, text=True, capture_output=True, timeout=60)
    (directory / "contract_build.log").write_text(built.stdout + built.stderr, encoding="utf-8")
    require(built.returncode == 0, "RTL_ELABORATION_FAILED")
    scopes = read_vvp((directory / "contract_probe.vvp").read_text())
    expected_scopes = set()
    resolved = []
    for node in nodes(manifest["design"]):
        require(node["rtl_path"] in scopes, "MISSING_MODULE")
        require(node["module"] == scopes[node["rtl_path"]]["model"], "MODULE_MISMATCH")
        expected_scopes.add(node["rtl_path"])
        for endpoint in node["endpoints"]:
            port = scopes[node["rtl_path"]]["ports"].get(endpoint["rtl_path"].rsplit(".", 1)[1])
            require(port and port["direction"] == "output" and port["width"] == endpoint["width"], "ENDPOINT_MISMATCH")
            resolved.append(endpoint["rtl_path"])
        for primitive in node["primitives"]:
            expected_scopes.add(primitive["rtl_path"])
            actual = scopes.get(primitive["rtl_path"])
            require(actual and actual["model"] == primitive["model"], "PRIMITIVE_MISMATCH")
            require(actual["parameters"] == primitive["parameters"], "PRIMITIVE_PARAMETER_MISMATCH")
            require(actual["ports"] == {p["name"]: p for p in primitive["ports"]}, "PRIMITIVE_PORT_MISMATCH")
    require(set(scopes) == expected_scopes, "UNREGISTERED_MODULE_OR_PRIMITIVE")
    probe, checks = probe_source(manifest, scopes)
    (directory / "contract_probe.sv").write_text(probe, encoding="utf-8")
    built = subprocess.run(command[:1] + ["-s", "ContractProbe"] + command[1:] + ["contract_probe.sv"], cwd=directory,
                           text=True, capture_output=True, timeout=60)
    (directory / "contract_build.log").write_text(built.stdout + built.stderr, encoding="utf-8")
    require(built.returncode == 0, "RTL_PROBE_ELABORATION_FAILED")
    simulation = subprocess.run(["vvp", "contract_probe.vvp"], cwd=directory, text=True, capture_output=True, timeout=60)
    (directory / "contract_simulation.log").write_text(simulation.stdout + simulation.stderr, encoding="utf-8")
    require("RESET_BINDING_MISMATCH" not in simulation.stdout, "RESET_BINDING_MISMATCH")
    require(simulation.returncode == 0 and f"CONTRACT_PROBES_PASS:{checks}" in simulation.stdout,
            "ENDPOINT_MAPPING_MISMATCH")
    result = {"status": "PASS", "semantic_sha256": document["semantic_sha256"], "endpoints": resolved,
              "mapping_checks": checks, "source_sha256": {s.name: sha(s.read_bytes()) for s in sources},
              "hw_ir_sha256": sha((directory / "design.hw.mlir").read_bytes()),
              "resolver_sha256": sha(Path(__file__).read_bytes()), "simulator": "Icarus 13.0"}
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directories", type=Path, nargs="*")
    args = parser.parse_args()
    fixtures = ("buffer", "wide", "packet", "pipeline", "celement", "latch", "transport", "inertial",
                "timed_early", "timed_equal", "timed_late")
    directories = args.directories or [ROOT / "target/generated" / name for name in fixtures]
    require(bool(directories), "EMPTY_EXPORT_INVENTORY")
    for path in directories:
        directory = path.parent if path.name == "contract.json" else path
        result = validate_export(directory)
        print(f"{directory.name}: {len(result['endpoints'])} resolved endpoints; {result['mapping_checks']} RTL mapping checks")


if __name__ == "__main__":
    main()
