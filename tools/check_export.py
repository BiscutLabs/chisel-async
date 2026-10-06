# SPDX-License-Identifier: Apache-2.0
"""Resolve the qualified export through Icarus elaboration and active RTL anchor probes.

The VVP reader accepts the pinned Icarus 13 module/port/parameter format, not arbitrary
SystemVerilog syntax. Actual compilation rejects unbound instances and duplicate views.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "verification"))
from run import read_sources

OPTIONS = ["-O=release", "--strip-fir-debug-info",
           "--lowering-options=disallowPortDeclSharing,disallowLocalVariables"]
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
    shape(manifest, "schema time_unit time_range top toolchain resources rtl_semantic_sha256 probe_abi port_abi design")
    require(document["semantic_sha256"] == semantic_hash(manifest), "SEMANTIC_HASH_MISMATCH")
    require(manifest["schema"] == "chisel-async-contract-v3" and manifest["time_unit"] == "fs"
            and manifest["time_range"] == "0..9223372036854775807", "UNSUPPORTED_SCHEMA")
    require(manifest["toolchain"] == {"chisel": "7.16.0", "scala": "2.13.18", "firtool": "1.160.0", "options": manifest["toolchain"]["options"]},
            "UNQUALIFIED_COMPILER")
    require(re.fullmatch(IDENT, manifest["top"]), "INVALID_TOP")
    require(manifest["toolchain"]["options"] in (OPTIONS, ["-O=debug", "--no-dedup", "--preserve-values=named", *OPTIONS[1:]]), "UNQUALIFIED_TOOLCHAIN")
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
            shape(item, "id rtl_path width source probe")
            require(item["rtl_path"].startswith(path + ".") and
                    re.fullmatch(IDENT, item["rtl_path"][len(path) + 1:]), "INVALID_ENDPOINT_PATH")
            require(item["rtl_path"] not in all_paths, "AMBIGUOUS_RTL_PATH")
            all_paths.add(item["rtl_path"])
            require(item["rtl_path"].endswith(f'.ca_p_{len(item["id"])}_{item["id"]}'), "ENDPOINT_MISMATCH")
            require(type(item["width"]) is int and item["width"] > 0, "INVALID_ENDPOINT_WIDTH")
        for channel in node["channels"]:
            common = "id protocol role reset_domain layout phases environment token_contract "
            if channel["protocol"] == "four-phase-bundled-v1":
                shape(channel, common + "request data acknowledge")
                refs, payload, controls = ("request", "data", "acknowledge"), "data", ("request", "acknowledge")
                phases = ["00", "10", "11", "01", "00"]
            elif channel["protocol"] == "dual-rail-rtz-v1":
                shape(channel, common + "zero one acknowledge")
                refs, payload, controls = ("zero", "one", "acknowledge"), "one", ("acknowledge",)
                phases = ["spacer", "data", "acknowledged", "spacer", "idle"]
            elif channel["protocol"] == "decoupled-v1":
                shape(channel, common + "valid data ready clock")
                refs, payload, controls = ("valid", "data", "ready", "clock"), "data", ("valid", "ready", "clock")
                phases = ["rising-edge-fire"]
            else:
                raise ValueError("INVALID_CHANNEL")
            require(channel["reset_domain"] == domain, "RESET_DOMAIN_MISMATCH")
            require(channel["role"] in ("input", "output") and channel["phases"] == phases and
                    channel["token_contract"] == "ordered-lossless-reset-abort-v1", "INVALID_CHANNEL")
            require(all(channel[ref] in endpoints for ref in refs),
                    "MISSING_CHANNEL_ENDPOINT")
            require(all(channel[ref] == channel["id"] + "_" + ref for ref in refs), "CHANNEL_ENDPOINT_ASSOCIATION")
            require(all(endpoints[channel[c]]["width"] == 1 for c in controls), "INVALID_CHANNEL_CONTROL")
            offset = 0
            for field in channel["layout"]:
                shape(field, "field lsb width signed source")
                require(type(field["signed"]) is bool, "INVALID_PAYLOAD_LAYOUT")
                require(type(field["lsb"]) is int and field["lsb"] == offset and type(field["width"]) is int and field["width"] > 0,
                        "INVALID_PAYLOAD_LAYOUT")
                offset += field["width"]
            require(offset == endpoints[channel[payload]]["width"], "INVALID_PAYLOAD_LAYOUT")
            if channel["protocol"] == "dual-rail-rtz-v1":
                require(offset == endpoints[channel["zero"]]["width"], "INVALID_PAYLOAD_LAYOUT")
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
            require(primitive["view"] in ("behavioral", "constraint-marker") and primitive["version"] == 1, "INVALID_VIEW")
            require((primitive["view"] == "constraint-marker") == (primitive["model"] == "ChiselAsyncTimingMarker_v1"), "INVALID_VIEW")
            require(re.fullmatch(r"ChiselAsync[A-Za-z0-9]+_v1", primitive["model"]), "INVALID_MODEL")
            require(primitive["resource"] == f'chiselasync/sv/{primitive["model"]}.sv', "INVALID_RESOURCE")
            require(primitive["rtl_path"].startswith(path + ".") and
                    re.fullmatch(IDENT, primitive["rtl_path"][len(path) + 1:]), "INVALID_PRIMITIVE_PATH")
            require(primitive["rtl_path"] not in all_paths, "AMBIGUOUS_RTL_PATH")
            all_paths.add(primitive["rtl_path"])
            resources.add(primitive["resource"])
        for timing in node["timing"]:
            if timing.get("kind") == "long-hold-bundling-v2":
                shape(timing, "id kind marker mode request input_data latch_data latch_closed acknowledge output_request output_data "
                      "matched_delay_fs data_delay control_delays latch_delay output_delay_fs provenance assumptions")
                refs = ("request", "input_data", "latch_data", "latch_closed", "acknowledge", "output_request", "output_data")
                times = ("matched_delay_fs", "output_delay_fs")
                require(timing["mode"] in ("functional-only", "digital-model"), "UNSUPPORTED_TIMING")
            else:
                shape(timing, "id kind marker launch transaction data_valid capture captured setup_fs hold_fs mode provenance pulse_policy")
                require(timing["kind"] == "bundled-setup-hold-v1" and timing["mode"] == "digital-model", "UNSUPPORTED_TIMING")
                refs = ("launch", "transaction", "data_valid", "capture", "captured")
                times = ("setup_fs", "hold_fs")
            require(all(timing[ref] in endpoints for ref in refs), "MISSING_TIMING_ENDPOINT")
            marker = next((p for p in node["primitives"] if p["id"] == timing["marker"]), None)
            require(marker and marker["view"] == "constraint-marker", "MISSING_TIMING_MARKER")
            for name in times:
                require(type(timing[name]) is str and re.fullmatch(r"0|[1-9][0-9]*", timing[name])
                        and int(timing[name]) <= 2**63 - 1, "INVALID_MODEL_TIME")
            if timing["kind"] == "long-hold-bundling-v2":
                matched, output = (int(timing[n]) for n in times)
                shape(timing["control_delays"], "a b acknowledge long_hold")
                bounds = {**timing["control_delays"], "data_delay": timing["data_delay"], "payload": timing["latch_delay"]}
                for bound in bounds.values():
                    shape(bound, "min_fs max_fs model_fs")
                    require(all(type(v) is str and re.fullmatch(r"0|[1-9][0-9]*", v) and int(v) <= 2**63-1
                                for v in bound.values()), "INVALID_MODEL_TIME")
                    require(int(bound["min_fs"]) <= int(bound["model_fs"]) <= int(bound["max_fs"]), "INVALID_DELAY_BOUNDS")
                maxima = {k: int(v["max_fs"]) for k,v in bounds.items()}
                worst = max(maxima[k] for k in timing["control_delays"])
                require((timing["mode"] == "functional-only" and not any([matched, output, *maxima.values()])) or
                        (timing["mode"] == "digital-model" and matched > maxima["data_delay"] and output > 2*worst+maxima["payload"] and
                         all(int(v["min_fs"]) > 0 for k,v in bounds.items() if k != "data_delay")), "INVALID_BUNDLING_POLICY")
                # The declared model times must agree with actual preserved cell parameters.
                primitives = {p["id"]: p for p in node["primitives"]}
                model_delays = {k: int(v["model_fs"]) for k,v in bounds.items()}
                model_delays.update(request_delay=matched, output_delay=output)
                for cell_id, delay in model_delays.items():
                    require(cell_id in primitives and primitives[cell_id]["parameters"].get("DELAY_FS") == str(delay),
                            "BUNDLING_PARAMETER_MISMATCH")
            require(marker["parameters"] == marker_parameters(timing, endpoints), "TIMING_MARKER_PARAMETER_MISMATCH")
        for child in node["children"]:
            shape(child, "id contract")
    require(resources == set(manifest["resources"]), "RESOURCE_INVENTORY_MISMATCH")
    return manifest


def timing_refs(timing):
    return (("request", "input_data", "latch_data", "latch_closed", "acknowledge", "output_request", "output_data")
            if timing["kind"] == "long-hold-bundling-v2" else
            ("launch", "transaction", "data_valid", "capture", "captured"))


def marker_parameters(timing, endpoints):
    roles = ("A", "B", "ACKNOWLEDGE", "LONG_HOLD", "DATA", "LATCH")
    result = {name: "0" for name in ("KIND", "WIDTH", "SETUP_FS", "HOLD_FS", "MATCHED_FS", "OUTPUT_FS")}
    result.update({f"{r}_{b}_FS": "0" for r in roles for b in ("MIN", "MAX", "MODEL")})
    result["WIDTH"] = str(sum(endpoints[timing[ref]]["width"] for ref in timing_refs(timing)))
    if timing["kind"] == "long-hold-bundling-v2":
        result.update(KIND="2", MATCHED_FS=timing["matched_delay_fs"], OUTPUT_FS=timing["output_delay_fs"])
        bounds = {**{k.upper(): v for k,v in timing["control_delays"].items()}, "DATA": timing["data_delay"], "LATCH": timing["latch_delay"]}
        for role, values in bounds.items():
            for bound in ("min", "max", "model"):
                result[f"{role}_{bound.upper()}_FS"] = values[bound+"_fs"]
    else:
        result.update(KIND="1", SETUP_FS=timing["setup_fs"], HOLD_FS=timing["hold_fs"])
    return result


def read_probe_abi(text, top):
    macros = {}
    for line in text.splitlines():
        if not line.strip() or line.startswith("//"):
            continue
        match = re.fullmatch(r"`define ref_" + re.escape(top) + "_(" + IDENT + ") (" + IDENT + r"(?:\." + IDENT + ")*)", line)
        require(match, "UNSUPPORTED_PROBE_ABI")
        require(match[1] not in macros, "AMBIGUOUS_PROBE_ABI")
        macros[match[1]] = match[2]
    require(macros, "EMPTY_PROBE_ABI")
    return macros


def read_vvp(contents):
    require(':ivl_version "13.0 ' in contents, "UNQUALIFIED_SIMULATOR")
    scopes, paths, current = {}, {}, None
    for line in contents.splitlines():
        scope = re.match(r'(S_\w+) \.scope (\w+), "([^"\\]+)" "([^"\\]+)" (.*);$', line)
        if scope:
            key, kind, name, model, tail = scope.groups()
            parent = re.search(r", (S_\w+)$", tail)
            parent_path = scopes[parent[1]]["path"] + "." if parent else ""
            current = {"path": parent_path + name, "kind": kind, "model": model, "ports": {}, "parameters": {}, "registers": {}, "nets": {}}
            require(key not in scopes and current["path"] not in paths, "AMBIGUOUS_ELABORATED_SCOPE")
            scopes[key] = paths[current["path"]] = current
        elif ".scope " in line and not line.lstrip().startswith(".scope"):
            raise ValueError("UNSUPPORTED_ELABORATED_SCOPE")
        port = re.match(r'\s*\.port_info \d+ /(INPUT|OUTPUT|INOUT) (\d+) "(' + IDENT + r')";', line)
        if port and current:
            direction, width, name = port.groups()
            require(name not in current["ports"], "AMBIGUOUS_ELABORATED_PORT")
            current["ports"][name] = {"name": name, "direction": direction.lower(), "width": int(width)}
        net = re.match(r'v\w+ \.(?:net(?:/\w+)?|var) "(' + IDENT + r')", (\d+) (\d+),?', line)
        if net and current:
            current["nets"][net[1]] = int(net[2]) - int(net[3]) + 1
        register = re.match(r'v\w+ \.var "(' + IDENT + r')", (\d+) 0;', line)
        if register and current:
            current["registers"][register[1]] = int(register[2]) + 1
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
        layouts = {}
        endpoint_by_id = {e["id"]: e for e in node["endpoints"]}
        for channel in node["channels"]:
            if channel["protocol"] == "dual-rail-rtz-v1":
                layouts[channel["one"]] = channel["layout"]
                one = endpoint_by_id[channel["one"]]["source"]
                zero = endpoint_by_id[channel["zero"]]["source"]
                require(all(f["source"].startswith(one) for f in channel["layout"]), "INVALID_PAYLOAD_LAYOUT")
                layouts[channel["zero"]] = [{**f, "source": zero + f["source"][len(one):]} for f in channel["layout"]]
            else:
                layouts[channel["data"]] = channel["layout"]
        for endpoint in node["endpoints"]:
            fields = layouts.get(endpoint["id"], [{"source": endpoint["source"], "lsb": 0, "width": endpoint["width"]}])
            # Public boundary/packing references remain an independent oracle.
            # For internal timing nodes optimized away, use the marker's wired
            # endpoint slice; behavioral timing tests separately exercise the path.
            source = source_path(node, endpoint["source"])
            if not fields[0]["source"] == endpoint["source"] or source.rsplit(".",1)[1] in scopes[node["rtl_path"]]["nets"]:
                expr = "{" + ", ".join(source_path(node, f["source"]) for f in reversed(fields)) + "}"
            else:
                candidates = []
                for timing in node["timing"]:
                    offset = 0
                    marker = next(p for p in node["primitives"] if p["id"] == timing["marker"])
                    for ref in timing_refs(timing):
                        width = endpoint_by_id[timing[ref]]["width"]
                        if timing[ref] == endpoint["id"]:
                            candidates.append(f'{marker["rtl_path"]}.values[{offset} +: {width}]')
                        offset += width
                require(candidates, "UNRESOLVED_SOURCE_TARGET")
                expr = candidates[0]
            path, width, index = endpoint["rtl_path"], endpoint["width"], len(coverage)
            lines.append(f"reg [{width-1}:0] ones_{index}=0, zeros_{index}=0;")
            comparisons.append(f'if ({path} !== {expr}) $fatal(1, "ENDPOINT_MAPPING_MISMATCH:{path}");')
            comparisons.append(f'if ($bits({path}) != {width}) $fatal(1, "ENDPOINT_WIDTH_MISMATCH");')
            for bit in range(width):
                value = path if width == 1 else f"{path}[{bit}]"
                comparisons += [f"if ({value} === 1'b1) ones_{index}[{bit}] = 1'b1;",
                                f"if ({value} === 1'b0) zeros_{index}[{bit}] = 1'b1;"]
            coverage.append(f"if (ones_{index} !== {width}'h{(1<<width)-1:x} || "
                            f"zeros_{index} !== {width}'h{(1<<width)-1:x}) "
                            f'$fatal(1, "INACTIVE_ENDPOINT:{path}");')
        for timing in node["timing"]:
            marker = next(p for p in node["primitives"] if p["id"] == timing["marker"])
            expression = "{" + ", ".join(endpoint_by_id[timing[ref]]["rtl_path"] for ref in reversed(timing_refs(timing))) + "}"
            comparisons.append(f'if ({marker["rtl_path"]}.values !== {expression}) $fatal(1, "TIMING_MARKER_BINDING_MISMATCH");')
        if node["rtl_path"] == top:
            drivers += [(top + "." + name, p["width"])
                        for name, p in scopes[top]["ports"].items() if p["direction"] == "input"]
        if any(c["protocol"] == "decoupled-v1" for c in node["channels"]):
            # Mapping-only stimulus for native Chisel registers, analogous to forcing
            # primitive q ports below. Behavioral runs never force these registers.
            drivers += [(node["rtl_path"] + "." + name, width)
                        for name, width in scopes[node["rtl_path"]]["registers"].items()]
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


def validate_port_abi(directory, manifest, scopes):
    abi = manifest["port_abi"]
    shape(abi, "file sha256")
    require(abi["file"] == "ports.json", "INVALID_PORT_ABI")
    path = directory / abi["file"]
    require(path.is_file(), "MISSING_PORT_ABI")
    content = path.read_text(encoding="utf-8")
    require(sha(content.encode()) == abi["sha256"], "PORT_ABI_HASH_MISMATCH")
    data = json.loads(content, object_pairs_hook=unique_json)
    shape(data, "schema top nodes")
    require(data["schema"] == "chisel-async-port-abi-v1" and data["top"] == manifest["top"], "INVALID_PORT_ABI")
    inventory = {}
    for node in data["nodes"]:
        shape(node, "rtl_path module ports")
        require(node["rtl_path"] not in inventory, "DUPLICATE_PORT_ABI_NODE")
        inventory[node["rtl_path"]] = node
    require(set(inventory) == {n["rtl_path"] for n in nodes(manifest["design"])}, "PORT_ABI_NODE_INVENTORY")
    for node in nodes(manifest["design"]):
        actual = inventory[node["rtl_path"]]
        require(actual["module"] == node["module"], "PORT_ABI_MODULE_MISMATCH")
        ports, flattened = {}, {}
        for port in actual["ports"]:
            shape(port, "source width signed direction clock")
            require(type(port["width"]) is int and port["width"] > 0
                    and type(port["signed"]) is bool and type(port["clock"]) is bool
                    and port["direction"] in ("input", "output"), "INVALID_PORT_ABI")
            name = source_path(node, port["source"]).rsplit(".", 1)[1]
            require(port["source"] not in ports and name not in flattened, "DUPLICATE_PORT_ABI_SOURCE")
            ports[port["source"]] = port
            flattened[name] = {"name": name, "width": port["width"], "direction": port["direction"]}
        require(flattened == scopes[node["rtl_path"]]["ports"], "PORT_ABI_RTL_MISMATCH")
        endpoints = {e["id"]: e for e in node["endpoints"]}
        for channel in node["channels"]:
            protocol = channel["protocol"]
            if protocol == "four-phase-bundled-v1":
                members, forward, reverse, payload = {"request": "req", "data": "bits", "acknowledge": "ack"}, ("request",), "acknowledge", "data"
            elif protocol == "dual-rail-rtz-v1":
                members, forward, reverse, payload = {"zero": "zero", "one": "one", "acknowledge": "ack"}, (), "acknowledge", "one"
            else:
                members, forward, reverse, payload = {"valid": "valid", "data": "bits", "ready": "ready"}, ("valid",), "ready", "data"
            roots = []
            for ref, member in members.items():
                source = endpoints[channel[ref]]["source"]
                require(source.endswith("." + member), "CHANNEL_SOURCE_ASSOCIATION")
                roots.append(source[:-(len(member) + 1)])
            require(len(set(roots)) == 1, "CHANNEL_SOURCE_ASSOCIATION")
            def check_port(source, direction, width, diagnostic="CHANNEL_PORT_MISMATCH"):
                require(source in ports, diagnostic)
                port = ports[source]
                require(port["width"] == width, "PAYLOAD_LEAF_WIDTH_MISMATCH" if diagnostic == "PAYLOAD_SOURCE_MISMATCH" else diagnostic)
                require(port["direction"] == direction, "CHANNEL_DIRECTION_MISMATCH")
                return port
            role = channel["role"]
            for ref in forward:
                check_port(endpoints[channel[ref]]["source"], role, 1)
            check_port(endpoints[channel[reverse]]["source"], "output" if role == "input" else "input", 1)
            if protocol == "decoupled-v1":
                require(check_port(endpoints[channel["clock"]]["source"], "input", 1)["clock"], "CHANNEL_CLOCK_TYPE")
            root = endpoints[channel[payload]]["source"]
            expected_leaves = {s for s in ports if s == root or s.startswith(root + ".") or s.startswith(root + "[")}
            fields = channel["layout"]
            require(len({f["source"] for f in fields}) == len(fields)
                    and {f["source"] for f in fields} == expected_leaves, "PAYLOAD_SOURCE_MISMATCH")
            for field in fields:
                require(field["field"] == "bits" + field["source"][len(root):], "PAYLOAD_FIELD_MISMATCH")
                port = check_port(field["source"], role, field["width"], "PAYLOAD_SOURCE_MISMATCH")
                require(field["signed"] == port["signed"] and not port["clock"], "PAYLOAD_SIGNEDNESS_MISMATCH")
                if protocol == "dual-rail-rtz-v1":
                    zero = endpoints[channel["zero"]]["source"] + field["source"][len(root):]
                    other = check_port(zero, role, field["width"], "PAYLOAD_SOURCE_MISMATCH")
                    require(other["signed"] == port["signed"], "PAYLOAD_SIGNEDNESS_MISMATCH")


def validate_export(directory: Path):
    directory = directory.resolve()
    output = directory / "resolved.json"
    output.write_text('{"status":"RUNNING"}\n', encoding="utf-8")
    document = json.loads((directory / "contract.json").read_text(), object_pairs_hook=unique_json)
    manifest = validate_manifest(document)
    sources = read_sources(directory)
    abi = manifest["probe_abi"]
    shape(abi, "file sha256")
    require(abi["file"] == f'ref_{manifest["top"]}.sv', "INVALID_PROBE_ABI")
    abi_path = directory / abi["file"]
    require(abi_path.is_file(), "MISSING_PROBE_ABI")
    abi_text = abi_path.read_text()
    require(sha(abi_text.encode()) == abi["sha256"], "PROBE_ABI_HASH_MISMATCH")
    macros = read_probe_abi(abi_text, manifest["top"])
    expected_probes = [e["probe"] for n in nodes(manifest["design"]) for e in n["endpoints"]]
    require(len(expected_probes) == len(set(expected_probes)), "AMBIGUOUS_PROBE")
    require(set(macros) == set(expected_probes), "ENDPOINT_MISMATCH")
    # Keep the source contract immutable; lower only a copy for active checks.
    manifest = copy.deepcopy(manifest)
    for node in nodes(manifest["design"]):
        for endpoint in node["endpoints"]:
            endpoint["rtl_path"] = manifest["top"] + "." + macros[endpoint["probe"]]
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
        require(not any(name.startswith("ca_") for name in scopes[node["rtl_path"]]["ports"]), "HARDWARE_OBSERVATION_PORT")
        expected_scopes.add(node["rtl_path"])
        for endpoint in node["endpoints"]:
            path, name = endpoint["rtl_path"].rsplit(".", 1)
            require(path in scopes and scopes[path]["nets"].get(name) == endpoint["width"], "ENDPOINT_MISMATCH")
            resolved.append(endpoint["rtl_path"])
        for primitive in node["primitives"]:
            expected_scopes.add(primitive["rtl_path"])
            actual = scopes.get(primitive["rtl_path"])
            require(actual and actual["model"] == primitive["model"], "PRIMITIVE_MISMATCH")
            require(actual["parameters"] == primitive["parameters"], "PRIMITIVE_PARAMETER_MISMATCH")
            require(actual["ports"] == {p["name"]: p for p in primitive["ports"]}, "PRIMITIVE_PORT_MISMATCH")
    require(set(scopes) == expected_scopes, "UNREGISTERED_MODULE_OR_PRIMITIVE")
    validate_port_abi(directory, manifest, scopes)
    probe, checks = probe_source(manifest, scopes)
    (directory / "contract_probe.sv").write_text(probe, encoding="utf-8")
    built = subprocess.run(command[:1] + ["-s", "ContractProbe"] + command[1:] + ["contract_probe.sv"], cwd=directory,
                           text=True, capture_output=True, timeout=60)
    (directory / "contract_build.log").write_text(built.stdout + built.stderr, encoding="utf-8")
    require(built.returncode == 0, "RTL_PROBE_ELABORATION_FAILED")
    simulation = subprocess.run(["vvp", "contract_probe.vvp"], cwd=directory, text=True, capture_output=True, timeout=60)
    (directory / "contract_simulation.log").write_text(simulation.stdout + simulation.stderr, encoding="utf-8")
    for diagnostic in ("RESET_BINDING_MISMATCH", "TIMING_MARKER_BINDING_MISMATCH"):
        require(diagnostic not in simulation.stdout, diagnostic)
    require(simulation.returncode == 0 and f"CONTRACT_PROBES_PASS:{checks}" in simulation.stdout,
            "ENDPOINT_MAPPING_MISMATCH")
    result = {"status": "PASS", "semantic_sha256": document["semantic_sha256"], "endpoints": resolved,
              "mapping_checks": checks,
              "module_definitions": sorted({s["model"] for s in scopes.values()}),
              "instances": {path: scope["model"] for path, scope in scopes.items()},
              "probe_abi_sha256": abi["sha256"],
              "port_abi_sha256": manifest["port_abi"]["sha256"],
              "probe_paths": {e["probe"]: e["rtl_path"] for n in nodes(manifest["design"]) for e in n["endpoints"]}, "source_sha256": {s.name: sha(s.read_bytes()) for s in sources},
              "hw_ir_sha256": sha((directory / "design.hw.mlir").read_bytes()),
              "resolver_sha256": sha(Path(__file__).read_bytes()), "simulator": "Icarus 13.0"}
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directories", type=Path, nargs="*")
    args = parser.parse_args()
    fixtures = ("buffer", "wide", "packet", "pipeline", "celement", "latch", "transport", "inertial",
                "timed_early", "timed_equal", "timed_late", "structural", "structural_wide",
                "structural_packet", "structural_pipeline", "transform", "longhold", "longhold_wide",
                "longhold_packet", "longhold_pipeline", "longhold_comparison", "longhold_sum", "longhold_signed",
                "dualrail", "to_async", "to_clocked", "bridge_roundtrip", "replicated", "replicated_debug")
    directories = args.directories or [ROOT / "target/generated" / name for name in fixtures]
    require(bool(directories), "EMPTY_EXPORT_INVENTORY")
    for path in directories:
        directory = path.parent if path.name == "contract.json" else path
        result = validate_export(directory)
        print(f"{directory.name}: {len(result['endpoints'])} resolved endpoints; {result['mapping_checks']} RTL mapping checks")


if __name__ == "__main__":
    main()
