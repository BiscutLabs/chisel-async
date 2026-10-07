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
import click_contract

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "verification"))
from run import read_sources

OPTIONS = ["-O=release", "--strip-fir-debug-info",
           "--lowering-options=disallowPortDeclSharing,disallowLocalVariables"]
IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
QDI_MODES = {"strong": "1", "forwarding": "2", "selected-strong": "3"}
QDI_COMPONENTS = {"storage": "1", "dims": "2", "fork": "3", "join": "4", "demux": "5", "exclusive-merge": "6"}
QDI_INDICATIONS = {"storage": "strong", "dims": "strong", "fork": "forwarding", "join": "strong",
                   "demux": "selected-strong", "exclusive-merge": "selected-strong"}
MARKER_MODELS = {"ChiselAsyncTimingMarker_v1", "ChiselAsyncQdiMarker_v1", "ChiselAsyncClickMarker_v1"}


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


def validate_qdi_timing(timing, node):
    shape(timing, "id kind marker indication component input_channels output_channels cells assumptions")
    component = timing["component"]
    require(component in QDI_COMPONENTS and timing["indication"] == QDI_INDICATIONS[component],
            "INVALID_QDI_INDICATION")
    assumptions = {"cells": "atomic-digital", "forks": "ideal-zero-skew", "reset": "coordinated-quiescent",
                   "rails": "monotonic-1-of-2-rtz",
                   "exclusive_inputs": "complete-handshake-serialized" if component == "exclusive-merge" else "not-applicable"}
    require(timing["assumptions"] == assumptions, "INVALID_QDI_ASSUMPTIONS")
    channels = {c["id"]: c for c in node["channels"]}
    covered = []
    for key, role in (("input_channels", "input"), ("output_channels", "output")):
        inventory = timing[key]
        require(type(inventory) is list and bool(inventory), "QDI_CHANNEL_INVENTORY")
        for entry in inventory:
            shape(entry, "channel zero one acknowledge")
            channel = channels.get(entry["channel"])
            require(channel and channel["protocol"] == "dual-rail-rtz-v1" and channel["role"] == role,
                    "QDI_CHANNEL_BINDING")
            require(all(entry[ref] == channel[ref] for ref in ("zero", "one", "acknowledge")), "QDI_CHANNEL_BINDING")
            covered.append(entry["channel"])
    require(len(covered) == len(set(covered)) and set(covered) == set(channels), "QDI_CHANNEL_INVENTORY")
    inputs, outputs = len(timing["input_channels"]), len(timing["output_channels"])
    arities = {"storage": inputs == 1 and outputs == 1, "dims": inputs == 1 and outputs == 1,
               "fork": inputs == 1 and outputs >= 2, "join": inputs == 2 and outputs == 1,
               "demux": inputs == 1 and outputs == 2, "exclusive-merge": inputs >= 2 and outputs == 1}
    require(arities[component], "QDI_COMPONENT_CHANNELS")
    bound = timing["cells"]
    shape(bound, "min_fs max_fs model_fs")
    require(all(type(v) is str and re.fullmatch(r"[1-9][0-9]*", v) and int(v) <= 2**63-1 for v in bound.values()),
            "INVALID_MODEL_TIME")
    require(int(bound["min_fs"]) <= int(bound["model_fs"]) <= int(bound["max_fs"]), "INVALID_DELAY_BOUNDS")
    # Bounds apply to every local delayed primitive; child contracts carry their
    # own obligations. The marker is passive and protocol guards have no delay.
    for cell in node["primitives"]:
        if cell["view"] != "behavioral":
            continue
        time_parameters = {key for key in cell["parameters"] if key.endswith("_FS")}
        require(not time_parameters or time_parameters == {"DELAY_FS"}, "QDI_UNSUPPORTED_CELL_TIMING")
        if time_parameters:
            delay = cell["parameters"]["DELAY_FS"]
            require(int(bound["min_fs"]) <= int(delay) <= int(bound["max_fs"]), "QDI_CELL_OUTSIDE_BOUNDS")


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
        shape(node, "rtl_path module reset_domain capacity endpoints channels primitives timing children" + (" memories" if "memories" in node else ""))
        if "memories" in node:
            require(type(node["memories"]) is list and bool(node["memories"]), "MEMORY_INVENTORY")
        for memory in node.get("memories", []):
            shape(memory, "id source depth word_bits mask_bits read_latency write_latency ports initial_contents reset_contents read_under_write")
            require(all(type(memory[k]) is int and memory[k] > 0 for k in ("depth", "word_bits", "mask_bits"))
                    and memory["word_bits"] % memory["mask_bits"] == 0, "MEMORY_SHAPE")
            require(type(memory["read_latency"]) is int and type(memory["write_latency"]) is int
                    and memory["read_latency"] == memory["write_latency"] == 1 and memory["ports"] == "one-read-write"
                    and memory["initial_contents"] == "unspecified" and memory["reset_contents"] == "preserved"
                    and memory["read_under_write"] == "undefined", "UNSUPPORTED_MEMORY_POLICY")
        require(node["reset_domain"] == domain, "RESET_DOMAIN_MISMATCH")
        require(node["capacity"] is None or type(node["capacity"]) is int and node["capacity"] > 0, "INVALID_CAPACITY")
        ids = [item["id"] for group in ("endpoints", "channels", "primitives", "timing", "children")
               for item in node[group]] + [m["id"] for m in node.get("memories", [])]
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
            if channel["protocol"] in ("four-phase-bundled-v1", "two-phase-bundled-v1"):
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
            require((primitive["view"] == "constraint-marker") == (primitive["model"] in MARKER_MODELS), "INVALID_VIEW")
            require(re.fullmatch(r"ChiselAsync[A-Za-z0-9]+_v1", primitive["model"]), "INVALID_MODEL")
            require(primitive["resource"] == f'chiselasync/sv/{primitive["model"]}.sv', "INVALID_RESOURCE")
            require(primitive["rtl_path"].startswith(path + ".") and
                    re.fullmatch(IDENT, primitive["rtl_path"][len(path) + 1:]), "INVALID_PRIMITIVE_PATH")
            require(primitive["rtl_path"] not in all_paths, "AMBIGUOUS_RTL_PATH")
            all_paths.add(primitive["rtl_path"])
            resources.add(primitive["resource"])
        for timing in node["timing"]:
            if timing.get("kind") == "qdi-digital-v1":
                validate_qdi_timing(timing, node)
                times = ()
            elif timing.get("kind") == "long-hold-bundling-v2":
                shape(timing, "id kind marker mode request input_data latch_data latch_closed acknowledge output_request output_data "
                      "matched_delay_fs data_delay control_delays latch_delay output_delay_fs provenance assumptions")
                refs = ("request", "input_data", "latch_data", "latch_closed", "acknowledge", "output_request", "output_data")
                times = ("matched_delay_fs", "output_delay_fs")
                require(timing["mode"] in ("functional-only", "digital-model"), "UNSUPPORTED_TIMING")
            elif timing.get("kind") == "encoding-boundary-v1":
                shape(timing, "id kind marker direction input_data input_control input_acknowledge output_data output_control output_acknowledge cells data_delay matched_delay_fs return_delay_fs assumptions")
                refs = ("input_data", "input_control", "input_acknowledge", "output_data", "output_control", "output_acknowledge")
                times = ("matched_delay_fs", "return_delay_fs")
                decode = timing["direction"] == "dual-to-bundled"
                require(timing["direction"] in ("bundled-to-dual", "dual-to-bundled"), "INVALID_ENCODING_DIRECTION")
                protocols = {c["id"]: c["protocol"] for c in node["channels"]}
                expected_protocols = ["dual-rail-rtz-v1", "four-phase-bundled-v1"]
                require([protocols.get("in"), protocols.get("out")] == (expected_protocols if decode else expected_protocols[::-1]), "INVALID_ENCODING_DIRECTION")
                expected = ("in_one", "in_zero", "in_acknowledge", "out_data", "out_request", "out_acknowledge") if decode else (
                    "in_data", "in_request", "in_acknowledge", "out_one", "out_zero", "out_acknowledge")
                require(tuple(timing[r] for r in refs) == expected, "INVALID_ENCODING_BINDING")
                for bound in (timing["cells"], timing["data_delay"]):
                    shape(bound, "min_fs max_fs model_fs")
                    require(all(type(v) is str and re.fullmatch(r"0|[1-9][0-9]*", v) and int(v) <= 2**63-1 for v in bound.values()), "INVALID_MODEL_TIME")
                    require(int(bound["min_fs"]) <= int(bound["model_fs"]) <= int(bound["max_fs"]), "INVALID_DELAY_BOUNDS")
                require(int(timing["cells"]["min_fs"]) > 0, "INVALID_DELAY_BOUNDS")
                require(all(type(timing[t]) is str and re.fullmatch(r"0|[1-9][0-9]*", timing[t]) for t in times), "INVALID_MODEL_TIME")
                owner = next((c["contract"] for c in node["children"] if c["id"] == "storage"), None)
                policy = next((t for t in owner["timing"] if t["kind"] == "long-hold-bundling-v2"), None) if owner else None
                require(policy and policy["mode"] == "digital-model" and policy["data_delay"] == timing["data_delay"] and
                        policy["matched_delay_fs"] == timing["matched_delay_fs"], "ENCODING_BUDGET_MISMATCH")
                maximum = int(timing["cells"]["max_fs"])
                require((int(timing["return_delay_fs"]) > maximum and int(timing["matched_delay_fs"]) > maximum+int(timing["data_delay"]["max_fs"]))
                        if decode else timing["return_delay_fs"] == "0", "INVALID_ENCODING_GUARD")
                for p in node["primitives"]:
                    if p["view"] == "behavioral":
                        delay = (timing["return_delay_fs"] if p["id"] == "acknowledge_guard" else
                                 timing["matched_delay_fs"] if p["id"] == "decoded_request_guard" else timing["cells"]["model_fs"])
                        require(p["parameters"].get("DELAY_FS") == delay, "ENCODING_PARAMETER_MISMATCH")
            elif timing.get("kind") == "click-bundling-v1":
                click_contract.validate(timing, node, endpoints)
                refs, times = (), ()
            elif timing.get("kind") == "phase-conversion-v2":
                shape(timing, "id kind marker direction input_request input_acknowledge output_request output_acknowledge cells return_delay_fs assumptions" +
                      (" history_closed history_closure request_delay_fs" if "history_closure" in timing else ""))
                refs, times = ("input_request", "input_acknowledge", "output_request", "output_acknowledge"), ("return_delay_fs",)
                require(tuple(timing[r] for r in refs) == ("in_request", "in_acknowledge", "out_request", "out_acknowledge"), "INVALID_PHASE_BINDING")
                bound = timing["cells"]
                shape(bound, "min_fs max_fs model_fs")
                require(all(type(v) is str and re.fullmatch(r"[1-9][0-9]*", v) and int(v) <= 2**63-1 for v in bound.values()), "INVALID_MODEL_TIME")
                require(int(bound["min_fs"]) <= int(bound["model_fs"]) <= int(bound["max_fs"]), "INVALID_DELAY_BOUNDS")
                direction = timing["direction"]
                require(direction in ("two-to-four", "four-to-two"), "INVALID_PHASE_DIRECTION")
                protocols = {c["id"]: c["protocol"] for c in node["channels"]}
                expected = ["two-phase-bundled-v1", "four-phase-bundled-v1"]
                require([protocols.get("in"), protocols.get("out")] == (expected if direction == "two-to-four" else expected[::-1]), "INVALID_PHASE_DIRECTION")
                require(type(timing["return_delay_fs"]) is str and re.fullmatch(r"0|[1-9][0-9]*", timing["return_delay_fs"]), "INVALID_MODEL_TIME")
                guard = int(timing["return_delay_fs"])
                require((guard > int(bound["max_fs"]) if direction == "two-to-four" else guard == 0), "INVALID_PHASE_RETURN_GUARD")
                primitives = {p["id"]: p for p in node["primitives"]}
                names = ("master_close", "phase", "returned", "request") if direction == "two-to-four" else ("history", "request_phase", "acknowledge")
                for name in names:
                    require(name in primitives and primitives[name]["parameters"].get("DELAY_FS") == bound["model_fs"], "PHASE_PARAMETER_MISMATCH")
                if direction == "two-to-four":
                    require(primitives.get("return_guard", {}).get("parameters", {}).get("DELAY_FS") == str(guard), "PHASE_PARAMETER_MISMATCH")
                    for name, model, parameters in (
                        ("master_close", "ChiselAsyncControlGate_v1", {"WIDTH": "1", "OP": "1", "RESET_VALUE": "1"}),
                        ("phase", "ChiselAsyncClosingLatch_v1", {"WIDTH": "1"}),
                        ("returned", "ChiselAsyncClosingLatch_v1", {"WIDTH": "1"}),
                        ("request", "ChiselAsyncXor_v1", {}),
                        ("return_guard", "ChiselAsyncControlGate_v1", {"WIDTH": "1", "OP": "0", "RESET_VALUE": "0"}),
                    ):
                        cell = primitives[name]
                        require(cell["model"] == model and all(cell["parameters"].get(k) == v for k, v in parameters.items()),
                                "PHASE_GUARD_CELL_MISMATCH")
                if direction == "four-to-two":
                    require(timing.get("history_closed") == "history_closed", "MISSING_PHASE_CLOSURE")
                    closure = timing["history_closure"]
                    shape(closure, "min_fs max_fs model_fs")
                    require(all(type(v) is str and re.fullmatch(r"0|[1-9][0-9]*", v) and int(v) <= 2**63-1 for v in closure.values()), "INVALID_MODEL_TIME")
                    require(int(closure["min_fs"]) <= int(closure["model_fs"]) <= int(closure["max_fs"]), "INVALID_DELAY_BOUNDS")
                    request_guard = timing["request_delay_fs"]
                    require(type(request_guard) is str and re.fullmatch(r"[1-9][0-9]*", request_guard) and int(request_guard) <= 2**63-1, "INVALID_MODEL_TIME")
                    require(int(request_guard) > int(closure["max_fs"]), "INVALID_PHASE_CLOSURE_GUARD")
                    for name, value in (("history_close", closure["model_fs"]), ("request_guard", request_guard)):
                        require(primitives.get(name, {}).get("parameters", {}).get("DELAY_FS") == value, "PHASE_PARAMETER_MISMATCH")
                        p = primitives[name]
                        require(p['model'] == 'ChiselAsyncControlGate_v1' and
                                all(p['parameters'].get(k) == v for k,v in {'WIDTH':'1','OP':'0','RESET_VALUE':'0'}.items()), 'PHASE_GUARD_CELL_MISMATCH')
                    refs += ("history_closed",)
                else:
                    require("history_closure" not in timing, "INVALID_PHASE_DIRECTION")
            elif timing.get("kind") == "bundled-data-path-v1":
                shape(timing, "id kind marker source sink logic logic_model_fs budget delay_owner delay_cell accounting")
                refs, times = ("source", "sink"), ("logic_model_fs",)
                require(timing["logic_model_fs"] == "0" and timing["accounting"] ==
                        "included-in-delay-cell; replace-model-with-mapped-path; not-additive", "INVALID_DATA_PATH_ACCOUNTING")
                expected = {"chisel-transform-including-decode": ([], "data_delay", "in_data", "latch_data"),
                            "controlled-multiplexer-input-mux": (["storage"], "data_delay", "mux_sources", "mux_result"),
                            "exclusive-merge-input-mux": (["storage"], "data_delay", "mux_sources", "mux_result"),
                            "initial-token-literal-mux": ([], "data", "mux_state", "out_data")}
                require(timing["logic"] in expected and
                        (timing["delay_owner"], timing["delay_cell"], timing["source"], timing["sink"]) == expected[timing["logic"]],
                        "INVALID_DATA_PATH_BINDING")
                budget_owner = node
                for child_id in timing["delay_owner"]:
                    matches = [c["contract"] for c in budget_owner["children"] if c["id"] == child_id]
                    require(len(matches) == 1, "MISSING_DATA_PATH_OWNER")
                    budget_owner = matches[0]
                budget = timing["budget"]
                shape(budget, "min_fs max_fs model_fs")
                require(all(type(v) is str and re.fullmatch(r"0|[1-9][0-9]*", v) and int(v) <= 2**63-1
                            for v in budget.values()), "INVALID_MODEL_TIME")
                require(int(budget["min_fs"]) <= int(budget["model_fs"]) <= int(budget["max_fs"]), "INVALID_DELAY_BOUNDS")
                cell = next((p for p in budget_owner["primitives"] if p["id"] == timing["delay_cell"]), None)
                require(cell and cell["parameters"].get("DELAY_FS") == budget["model_fs"], "DATA_PATH_PARAMETER_MISMATCH")
                require(cell["model"] == "ChiselAsyncControlGate_v1" and
                        all(cell["parameters"].get(k) == v for k, v in {"OP": "0", "RESET_VALUE": "0"}.items()),
                        "DATA_PATH_CELL_MISMATCH")
                owner_policy = next((t for t in budget_owner["timing"] if t["kind"] == "long-hold-bundling-v2"), None)
                if owner_policy:
                    require(budget == owner_policy["data_delay"], "DATA_PATH_BUDGET_MISMATCH")
                else:
                    request = next((p for p in budget_owner["primitives"] if p["id"] == "request_delay"), None)
                    require(request and int(request["parameters"]["DELAY_FS"]) > int(budget["max_fs"]), "INVALID_BUNDLING_POLICY")
            elif timing.get("kind") == "long-hold-fork-v1":
                shape(timing, "id kind marker aout state_a early_pin late_pin relation model_wire_skew_fs a_min_fs")
                refs, times = ("aout", "state_a"), ("model_wire_skew_fs", "a_min_fs")
                require((timing["aout"], timing["state_a"], timing["early_pin"], timing["late_pin"], timing["relation"],
                         timing["model_wire_skew_fs"]) == ("out_acknowledge", "state_a", "long_hold.b", "long_hold.a",
                         "Aout+ strictly before A- at OR inputs", "0"), "INVALID_HOLD_FORK")
                policy = next((t for t in node["timing"] if t["kind"] == "long-hold-bundling-v2"), None)
                require(policy and timing["a_min_fs"] == policy["control_delays"]["a"]["min_fs"], "HOLD_FORK_BOUND_MISMATCH")
                hold = next((p for p in node["primitives"] if p["id"] == "long_hold"), None)
                require(hold and hold["model"] == "ChiselAsyncControlGate_v1" and
                        all(hold["parameters"].get(k) == v for k, v in {"WIDTH": "1", "OP": "2", "RESET_VALUE": "0"}.items()),
                        "HOLD_FORK_CELL_MISMATCH")
                state = next((p for p in node["primitives"] if p["id"] == "a"), None)
                state_parameters = {"COMMON": "1", "RISING": "1", "FALLING": "1", "COMMON_INVERT": "1",
                                    "RISING_INVERT": "0", "FALLING_INVERT": "1", "RESET_VALUE": "0"}
                require(state and state["model"] == "ChiselAsyncAsymmetricC_v1" and
                        all(state["parameters"].get(k) == v for k, v in state_parameters.items()),
                        "HOLD_FORK_CELL_MISMATCH")
            else:
                shape(timing, "id kind marker launch transaction data_valid capture captured setup_fs hold_fs mode provenance pulse_policy")
                require(timing["kind"] == "bundled-setup-hold-v1" and timing["mode"] == "digital-model", "UNSUPPORTED_TIMING")
                refs = ("launch", "transaction", "data_valid", "capture", "captured")
                times = ("setup_fs", "hold_fs")
            require(all(ref in endpoints for ref in timing_refs(timing)), "MISSING_TIMING_ENDPOINT")
            marker = next((p for p in node["primitives"] if p["id"] == timing["marker"]), None)
            require(marker and marker["view"] == "constraint-marker", "MISSING_TIMING_MARKER")
            require(marker["model"] == ("ChiselAsyncClickMarker_v1" if timing["kind"] == "click-bundling-v1" else
                                        "ChiselAsyncQdiMarker_v1" if timing["kind"] == "qdi-digital-v1"
                                        else "ChiselAsyncTimingMarker_v1"), "TIMING_MARKER_MODEL_MISMATCH")
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
            require(marker["parameters"] == marker_parameters(timing, endpoints),
                    "QDI_MARKER_PARAMETER_MISMATCH" if timing["kind"] == "qdi-digital-v1" else "TIMING_MARKER_PARAMETER_MISMATCH")
        # Required obligations cannot be silently deleted and rehashed.
        kinds = [t["kind"] for t in node["timing"]]
        qdi_markers = [p for p in node["primitives"] if p["model"] == "ChiselAsyncQdiMarker_v1"]
        if qdi_markers or "qdi-digital-v1" in kinds:
            require(len(qdi_markers) == kinds.count("qdi-digital-v1") == 1, "QDI_CONSTRAINT_INVENTORY")
        primitive_ids = {p["id"] for p in node["primitives"]}
        if any(p['model'] == 'ChiselAsyncClickMarker_v1' for p in node['primitives']) or {'fire','input_phase','payload'} <= primitive_ids:
            require(kinds.count('click-bundling-v1') == 1, 'MISSING_CLICK_CONSTRAINT')
        if {"selected0", "rendezvous0"} <= primitive_ids:
            require(any(t.get("logic") == "controlled-multiplexer-input-mux" for t in node["timing"]), "MISSING_MUX_CONSTRAINT")
        if "request_phase" in primitive_ids or {"master_close", "phase", "returned"} <= primitive_ids:
            require(kinds.count("phase-conversion-v2") == 1, "MISSING_PHASE_CONSTRAINT")
        if "decoded" in primitive_ids or {"zero0", "one0"} <= primitive_ids and any(c["id"] == "storage" for c in node["children"]):
            require(kinds.count("encoding-boundary-v1") == 1, "MISSING_ENCODING_CONSTRAINT")
        if "long-hold-bundling-v2" in kinds or {"a", "b", "acknowledge", "long_hold", "payload"} <= primitive_ids:
            require(kinds.count("long-hold-bundling-v2") == 1 and kinds.count("long-hold-fork-v1") == 1 and
                    sum(t.get("logic") == "chisel-transform-including-decode" for t in node["timing"]) == 1,
                    "MISSING_LONG_HOLD_PATH_CONSTRAINT")
        for primitive in node["primitives"]:
            if primitive["id"] == "exclusivity":
                require(any(t.get("logic") == "exclusive-merge-input-mux" for t in node["timing"]), "MISSING_MUX_CONSTRAINT")
            if primitive["id"] == "accepted0":
                require(any(t.get("logic") == "initial-token-literal-mux" for t in node["timing"]), "MISSING_MUX_CONSTRAINT")
        # Cell inventory is checked against elaborated RTL below. Semantic name
        # changes must not hide a retained marker or reuse one for two obligations.
        markers = {p["id"] for p in node["primitives"] if p["view"] == "constraint-marker"}
        references = [t["marker"] for t in node["timing"]]
        require(len(references) == len(set(references)) and set(references) == markers,
                "TIMING_MARKER_INVENTORY")
        for child in node["children"]:
            shape(child, "id contract")
    require(resources == set(manifest["resources"]), "RESOURCE_INVENTORY_MISMATCH")
    return manifest


def timing_refs(timing):
    """Endpoint IDs in marker packing order, least-significant first."""
    if timing["kind"] == "click-bundling-v1":
        return tuple(timing['endpoints'])
    if timing["kind"] == "qdi-digital-v1":
        return tuple(c[ref] for c in timing["input_channels"] + timing["output_channels"]
                     for ref in ("zero", "one", "acknowledge"))
    if timing["kind"] == "encoding-boundary-v1":
        fields = ("input_data", "input_control", "input_acknowledge", "output_data", "output_control", "output_acknowledge")
    elif timing["kind"] == "phase-conversion-v2":
        fields = ("input_request", "input_acknowledge", "output_request", "output_acknowledge") + (("history_closed",) if timing["direction"] == "four-to-two" else ())
    elif timing["kind"] == "bundled-data-path-v1": fields = ("source", "sink")
    elif timing["kind"] == "long-hold-fork-v1": fields = ("aout", "state_a")
    else:
        fields = (("request", "input_data", "latch_data", "latch_closed", "acknowledge", "output_request", "output_data")
                  if timing["kind"] == "long-hold-bundling-v2" else
                  ("launch", "transaction", "data_valid", "capture", "captured"))
    return tuple(timing[ref] for ref in fields)


def marker_parameters(timing, endpoints):
    width = str(sum(endpoints[ref]["width"] for ref in timing_refs(timing)))
    if timing["kind"] == "click-bundling-v1":
        return click_contract.marker_parameters(timing, endpoints)
    if timing["kind"] == "qdi-digital-v1":
        return {"MODE": QDI_MODES[timing["indication"]], "COMPONENT": QDI_COMPONENTS[timing["component"]],
                "WIDTH": width, **{f"CELL_{b.upper()}_FS": timing["cells"][b + "_fs"] for b in ("min", "max", "model")}}
    roles = ("A", "B", "ACKNOWLEDGE", "LONG_HOLD", "DATA", "LATCH")
    result = {name: "0" for name in ("KIND", "WIDTH", "SETUP_FS", "HOLD_FS", "MATCHED_FS", "OUTPUT_FS")}
    result.update({f"{r}_{b}_FS": "0" for r in roles for b in ("MIN", "MAX", "MODEL")})
    result["WIDTH"] = width
    if timing["kind"] == "encoding-boundary-v1":
        result.update(KIND="7" if timing["direction"] == "dual-to-bundled" else "6",
                      OUTPUT_FS=timing["return_delay_fs"], MATCHED_FS=timing["matched_delay_fs"])
        for role, key in (("A", "cells"), ("DATA", "data_delay")):
            result.update({f"{role}_{b.upper()}_FS": timing[key][b+"_fs"] for b in ("min", "max", "model")})
    elif timing["kind"] == "phase-conversion-v2":
        result.update(KIND="5", OUTPUT_FS=timing["return_delay_fs"])
        if timing["direction"] == "four-to-two":
            result.update(MATCHED_FS=timing["request_delay_fs"])
            result.update({f"B_{b.upper()}_FS": timing["history_closure"][b+"_fs"] for b in ("min", "max", "model")})
        result.update({f"A_{b.upper()}_FS": timing["cells"][b+"_fs"] for b in ("min", "max", "model")})
    elif timing["kind"] == "long-hold-bundling-v2":
        result.update(KIND="2", MATCHED_FS=timing["matched_delay_fs"], OUTPUT_FS=timing["output_delay_fs"])
        bounds = {**{k.upper(): v for k,v in timing["control_delays"].items()}, "DATA": timing["data_delay"], "LATCH": timing["latch_delay"]}
        for role, values in bounds.items():
            for bound in ("min", "max", "model"):
                result[f"{role}_{bound.upper()}_FS"] = values[bound+"_fs"]
    elif timing["kind"] == "bundled-data-path-v1":
        result.update(KIND="3")
        for bound in ("min", "max", "model"):
            result[f"DATA_{bound.upper()}_FS"] = timing["budget"][bound+"_fs"]
    elif timing["kind"] == "long-hold-fork-v1":
        result.update(KIND="4", A_MIN_FS=timing["a_min_fs"])
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
            current = {"path": parent_path + name, "kind": kind, "model": model, "ports": {}, "parameters": {}, "registers": {}, "nets": {}, "memories": {}}
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
        memory = re.match(r'v\w+ \.array "(' + IDENT + r')", (\d+) 0, (\d+) 0;', line)
        if memory and current:
            current["memories"][memory[1]] = (int(memory[2]) + 1, int(memory[3]) + 1)
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


def probe_source(manifest, scopes, paired=False):
    top = manifest["top"]
    lines = ["module ContractProbe; timeunit 1fs; timeprecision 1fs;"]
    comparisons, timing_bindings, coverage, drivers = [], [], [], []
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
                        width = endpoint_by_id[ref]["width"]
                        if ref == endpoint["id"]:
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
            expression = "{" + ", ".join(endpoint_by_id[ref]["rtl_path"] for ref in reversed(timing_refs(timing))) + "}"
            diagnostic = "QDI_MARKER_BINDING_MISMATCH" if timing["kind"] == "qdi-digital-v1" else "TIMING_MARKER_BINDING_MISMATCH"
            comparisons.append(f'if ({marker["rtl_path"]}.values !== {expression}) $fatal(1, "{diagnostic}");')
            if timing['kind'] == 'click-bundling-v1':
                comparisons += [f'if ({a} !== {b}) $fatal(1,"CLICK_BINDING_MISMATCH");'
                                for a,b in click_contract.bindings(timing,node,endpoint_by_id)]
            if timing["kind"] == "bundled-data-path-v1":
                owner = node
                for child_id in timing["delay_owner"]:
                    owner = next(c["contract"] for c in owner["children"] if c["id"] == child_id)
                cell = next(p for p in owner["primitives"] if p["id"] == timing["delay_cell"])["rtl_path"]
                sink = endpoint_by_id[timing["sink"]]["rtl_path"]
                if timing["logic"] in ("exclusive-merge-input-mux", "controlled-multiplexer-input-mux"):
                    storage_input = next(e for e in owner["endpoints"] if e["id"] == "in_data")["rtl_path"]
                    pairs = [(sink, storage_input), (sink, cell + ".a")]
                else:
                    pairs = [(sink, cell + ".q")]
                if timing["logic"] == "chisel-transform-including-decode":
                    payload = next(p for p in node["primitives"] if p["id"] == "payload")["rtl_path"]
                    pairs += [(sink, payload + ".d"),
                              (endpoint_by_id["latch_closed"]["rtl_path"], payload + ".closed")]
                timing_bindings += [f'if ({a} !== {b}) $fatal(1, "DATA_PATH_BINDING_MISMATCH");' for a, b in pairs]
            if timing["kind"] == "long-hold-fork-v1":
                hold = next(p for p in node["primitives"] if p["id"] == "long_hold")
                state = next(p for p in node["primitives"] if p["id"] == "a")
                comparisons.append(f'if ({hold["rtl_path"]}.b !== {endpoint_by_id[timing["aout"]]["rtl_path"]} || '
                                   f'{hold["rtl_path"]}.a !== {endpoint_by_id[timing["state_a"]]["rtl_path"]} || '
                                   f'{state["rtl_path"]}.falling !== {endpoint_by_id[timing["aout"]]["rtl_path"]} || '
                                   f'{state["rtl_path"]}.q !== {endpoint_by_id[timing["state_a"]]["rtl_path"]}) '
                                   '$fatal(1, "HOLD_FORK_BINDING_MISMATCH");')
            if timing['kind'] == 'phase-conversion-v2' and timing['direction'] == 'two-to-four':
                cells = {p['id']: p['rtl_path'] for p in node['primitives']}
                endpoint = lambda key: endpoint_by_id[timing[key]]['rtl_path']
                pairs = [(cells['master_close'] + '.a', endpoint('output_acknowledge')),
                         (cells['master_close'] + '.q', cells['phase'] + '.closed'),
                         (cells['phase'] + '.d', endpoint('input_request')),
                         (cells['phase'] + '.q', cells['returned'] + '.d'),
                         (cells['returned'] + '.closed', endpoint('output_acknowledge')),
                         (cells['returned'] + '.q', cells['return_guard'] + '.a'),
                         (cells['return_guard'] + '.q', endpoint('input_acknowledge')),
                         (cells['request'] + '.a', endpoint('input_request')),
                         (cells['request'] + '.b', cells['phase'] + '.q'),
                         (cells['request'] + '.q', endpoint('output_request'))]
                comparisons += [f'if ({a} !== {b}) $fatal(1, "PHASE_RETURN_BINDING_MISMATCH");' for a, b in pairs]
            if timing['kind'] == 'phase-conversion-v2' and timing['direction'] == 'four-to-two':
                cells = {p['id']:p['rtl_path'] for p in node['primitives']}
                endpoint = lambda key: endpoint_by_id[timing[key]]['rtl_path']
                pairs = [(cells['history_close']+'.a', endpoint('input_request')),
                         (cells['request_phase']+'.trigger', endpoint('input_request')),
                         (cells['history']+'.closed', endpoint('history_closed')),
                         (cells['history_close']+'.q', endpoint('history_closed')),
                         (cells['request_guard']+'.a', cells['request_phase']+'.q'),
                         (cells['request_guard']+'.q', endpoint('output_request')),
                         (cells['history']+'.d', endpoint('output_acknowledge')),
                         (cells['acknowledge']+'.a', endpoint('output_acknowledge')),
                         (cells['acknowledge']+'.b', cells['history']+'.q'),
                         (cells['acknowledge']+'.q', endpoint('input_acknowledge'))]
                comparisons += [f'if ({a} !== {b}) $fatal(1,"PHASE_CLOSURE_BINDING_MISMATCH");' for a,b in pairs]
        if node["rtl_path"] == top:
            drivers += [(top + "." + name, p["width"])
                        for name, p in scopes[top]["ports"].items() if p["direction"] == "input"]
        # Mapping-only stimulus for native Chisel registers, including clocked
        # backends behind an async public port. Behavioral runs never force them.
        drivers += [(node["rtl_path"] + "." + name, width)
                    for name, width in scopes[node["rtl_path"]]["registers"].items()]
        for primitive in node["primitives"]:
            drivers += [(primitive["rtl_path"] + "." + p["name"], p["width"])
                        for p in primitive["ports"] if p["direction"] == "output"]
            reset_endpoint = next(e for e in node["endpoints"] if e["id"] == primitive["reset"])
            comparisons.append(f'if ({primitive["rtl_path"]}.reset !== {reset_endpoint["rtl_path"]} || '
                               f'{reset_endpoint["rtl_path"]} !== {node["rtl_path"]}.reset) '
                               '$fatal(1, "RESET_BINDING_MISMATCH");')
    # Establish each probe's source mapping before comparing it across a child
    # boundary, so a bad child alias retains its precise mapping diagnostic.
    lines += ["task check; begin", *comparisons, *timing_bindings, "end endtask", "initial begin",
              f"force {top}.reset = 1'b1; #1;"]
    checks = 0
    # A mux needs simultaneous control and data activity. Independent uninitialized
    # forces cannot exercise its selected payload. Both backgrounds are deterministic;
    # no public/child endpoint itself is forced to conceal an incorrect mapping.
    for controls in (0, 1):
        for src, width in drivers:
            lines.append(f"force {src} = {width}'h{controls if width == 1 else 0:x};")
        lines.append("#1;")
        for src, width in drivers:
            for bit in range(width):
                for value in (1 << bit, ((1 << width) - 1) ^ (1 << bit)):
                    lines += [f"force {src} = {width}'h{value:x};", "#1; check;"]
                    checks += len(coverage)
            lines += [f"force {src} = {width}'h{controls if width == 1 else 0:x};", "#1;"]
    if paired:
        # Nested ready/valid gates can require two independently stored controls.
        # Keep every mapping comparison active; never force a derived endpoint.
        for src, width in drivers:
            lines.append(f"force {src} = {width}'h0;")
        for first, (a, aw) in enumerate(drivers):
            for b, bw in drivers[first+1:]:
                for av in sorted({1, (1 << aw)-1}):
                    for bv in sorted({1, (1 << bw)-1}):
                        lines += [f"force {a} = {aw}'h{av:x};", f"force {b} = {bw}'h{bv:x};", "#1; check;"]
                        checks += len(coverage)
                lines += [f"force {a} = {aw}'h0;", f"force {b} = {bw}'h0;"]
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
    require(data["schema"] == "chisel-async-port-abi-v2" and data["top"] == manifest["top"], "INVALID_PORT_ABI")
    inventory = {}
    for node in data["nodes"]:
        shape(node, "rtl_path module ports channels")
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
        bindings = {}
        for binding in actual["channels"]:
            shape(binding, "source protocol")
            source, protocol = binding["source"], binding["protocol"]
            require(source not in bindings, "DUPLICATE_CHANNEL_ABI_SOURCE")
            require(protocol in ("four-phase-bundled-v1", "two-phase-bundled-v1", "dual-rail-rtz-v1", "decoupled-v1")
                    and any(s.startswith(source + ".") for s in ports), "INVALID_CHANNEL_ABI")
            bindings[source] = protocol
        endpoints = {e["id"]: e for e in node["endpoints"]}
        registered_roots = []
        for channel in node["channels"]:
            protocol = channel["protocol"]
            if protocol in ("four-phase-bundled-v1", "two-phase-bundled-v1"):
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
            require(bindings.get(roots[0]) == protocol, "CHANNEL_PROTOCOL_MISMATCH")
            registered_roots.append(roots[0])
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
        if any(t["kind"] == "qdi-digital-v1" for t in node["timing"]):
            require(len(registered_roots) == len(set(registered_roots)) and set(registered_roots) == set(bindings),
                    "QDI_CHANNEL_ABI_INVENTORY")


def validate_memories(directory, node, scopes):
    """Only declared, one-RW-port SyncReadMem lowerings enter the scope inventory.

    Cross-check dimensions/latency in compiler IR and the actual elaborated array
    and pin ABI. Behavioral read/write, masks and reset persistence are exercised
    separately by the boundary campaign; this is not a general RAM equivalence proof.
    """
    memories = node.get("memories", [])
    if not memories:
        return set()
    model = scopes[node["rtl_path"]]["model"]
    ir = (directory / "design.hw.mlir").read_text()
    bodies = re.findall(r"^  hw.module (?:private )?@" + re.escape(model) + r"\([^\n]*\) \{\n(.*?)^  }", ir, re.M | re.S)
    require(len(bodies) == 1, "MEMORY_HW_MODULE")
    declared = re.findall(r"^    %(\w+) = seq.firmem 1, 1, undefined, port_order : <(\d+) x (\d+), mask (\d+)>$", bodies[0], re.M)
    require(len(declared) == len(memories), "MEMORY_HW_INVENTORY")
    result = set()
    for memory in memories:
        source = source_path(node, memory["source"])
        name = source.rsplit(".", 1)[1]
        depth, width, mask = (memory[k] for k in ("depth", "word_bits", "mask_bits"))
        require((name, str(depth), str(width), str(mask)) in declared, "MEMORY_HW_SHAPE")
        port_lines = [line for line in bodies[0].splitlines() if re.search(r"seq.firmem\.\w+ %" + re.escape(name) + r"\[", line)]
        require(len(port_lines) == 1 and "seq.firmem.read_write_port" in port_lines[0], "MEMORY_HW_PORTS")
        path = source + "_ext"
        actual = scopes.get(path)
        require(actual is not None and actual["memories"] == {"Memory": (depth, width)}, "MEMORY_RTL_SHAPE")
        pins = {key: {"name": key, "width": bits, "direction": "output" if key == "RW0_rdata" else "input"}
                for key, bits in (("RW0_addr", max(1, (depth-1).bit_length())), ("RW0_en",1), ("RW0_clk",1),
                                  ("RW0_wmode",1), ("RW0_wdata",width), ("RW0_rdata",width), ("RW0_wmask",mask))}
        require(actual["ports"] == pins and not actual["parameters"], "MEMORY_RTL_PORTS")
        result.add(path)
    return result


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
    # Mapping forces intentionally violate protocols. Only these probes disable
    # simulation assumption guards; every behavioral campaign keeps them enabled.
    command = ["iverilog", "-g2012", "-DCHISEL_ASYNC_MAPPING", "-s", manifest["top"], "-o", "contract_probe.vvp",
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
        expected_scopes.update(validate_memories(directory, node, scopes))
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
    if "INACTIVE_ENDPOINT:" in simulation.stdout:
        probe, checks = probe_source(manifest, scopes, paired=True)
        (directory / "contract_probe.sv").write_text(probe, encoding="utf-8")
        built = subprocess.run(command[:1] + ["-s", "ContractProbe"] + command[1:] + ["contract_probe.sv"], cwd=directory,
                               text=True, capture_output=True, timeout=60)
        (directory / "contract_build.log").write_text(built.stdout + built.stderr, encoding="utf-8")
        require(built.returncode == 0, "RTL_PROBE_ELABORATION_FAILED")
        simulation = subprocess.run(["vvp", "contract_probe.vvp"], cwd=directory, text=True, capture_output=True, timeout=60)
    (directory / "contract_simulation.log").write_text(simulation.stdout + simulation.stderr, encoding="utf-8")
    for diagnostic in ("RESET_BINDING_MISMATCH", "TIMING_MARKER_BINDING_MISMATCH", "PHASE_CLOSURE_BINDING_MISMATCH",
                       "PHASE_RETURN_BINDING_MISMATCH", "DATA_PATH_BINDING_MISMATCH", "HOLD_FORK_BINDING_MISMATCH",
                       "QDI_MARKER_BINDING_MISMATCH", "CLICK_BINDING_MISMATCH"):
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
              "resolver_sha256": sha(Path(__file__).read_bytes()),
              "resolver_dependencies": {"click_contract.py": sha(Path(click_contract.__file__).read_bytes())},
              "simulator": "Icarus 13.0"}
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
                "dualrail", "to_async", "to_clocked", "bridge_roundtrip", "replicated", "replicated_debug",
                "fifo_one", "fifo", "initialized_fifo", "initial_tokens", "initial_wide", "fork", "join", "select",
                "merge", "fork_join", "feedback", "phase_to_four", "phase_to_two", "arbiter",
                "two_buffer", "two_wide", "two_fifo", "two_initialized", "two_initial", "two_fork", "two_join",
                "two_select", "two_merge", "two_arbiter", "two_transform", "encoding_to_dual",
                "encoding_from_dual", "encoding_roundtrip", "phase_roundtrip", "reference_behavioral",
                "reference_bundled", "reference_qdi", "reference_gals", "reference_core",
                "qdi_buffer", "qdi_packet", "qdi_not", "qdi_and", "qdi_or", "qdi_xor", "qdi_select",
                "qdi_adder", "qdi_constant", "qdi_fork", "qdi_join", "qdi_demux", "qdi_merge", "qdi_composition",
                "memory_ram", "memory_rom", "memory_port", "pending_events",
                "click_standard", "click_decoupled", "click_seeded", "click_fifo", "click_decoupled_fifo", "click_ring")
    directories = args.directories or [ROOT / "target/generated" / name for name in fixtures]
    require(bool(directories), "EMPTY_EXPORT_INVENTORY")
    for path in directories:
        directory = path.parent if path.name == "contract.json" else path
        result = validate_export(directory)
        print(f"{directory.name}: {len(result['endpoints'])} resolved endpoints; {result['mapping_checks']} RTL mapping checks")


if __name__ == "__main__":
    main()
