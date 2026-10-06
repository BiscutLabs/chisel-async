# SPDX-License-Identifier: Apache-2.0
"""Check the emitted primitive connectivity against the inspected Fig. 15.

Restricted to the pinned emitted RTL dialect, not a general Verilog parser.
The independent STG oracle checks temporal behavior separately.
"""
import re


def check_topology(source):
    source = re.sub(r"//[^\n]*", "", source)
    aliases = {}
    def canonical(net):
        visited = set()
        while net in aliases:
            assert net not in visited, "TOPOLOGY_ALIAS_CYCLE"
            visited.add(net)
            net = aliases[net]
        return net
    for a, b in re.findall(r"(?:\bwire\s+(?:\[[^]]+\]\s*)?|\bassign\s+)(\w+)\s*=\s*(\w+)\s*;", source):
        aliases[a] = b
    cells = {}
    for match in re.finditer(r"(ChiselAsync\w+_v1)\s*#\((.*?)\)\s*ca_primitive_(\w+)\s*\((.*?)\);", source, re.S):
        model, params, name, body = match.groups()
        if model == "ChiselAsyncTimingMarker_v1":
            continue  # Passive metadata; check_export validates all parameters and bindings.
        ports = dict(re.findall(r"\.(\w+)\s*\(([^()]+)\)", body))
        numbers = dict(re.findall(r"\.(\w+)\s*\((\d+)\)", params))
        assert name not in cells, "TOPOLOGY_DUPLICATE_CELL"
        cells[name] = (model, numbers, {k: canonical(v.strip()) for k, v in ports.items()})
    expected = {
        "request_delay": ("ControlGate", {"OP": "0", "WIDTH": "1"}, {"a": "in_req"}),
        "data_delay": ("ControlGate", {"OP": "0", "WIDTH": "40"}, {"a": "in_bits"}),
        "long_hold": ("ControlGate", {"OP": "2", "WIDTH": "1"}, {"a": "a.q", "b": "out_ack"}),
        "output_delay": ("ControlGate", {"OP": "0", "WIDTH": "1"}, {"a": "a.q"}),
        "a": ("AsymmetricC", {"COMMON": "1", "RISING": "1", "FALLING": "1", "COMMON_INVERT": "1", "RISING_INVERT": "0", "FALLING_INVERT": "1"},
              {"common": "b.q", "rising": "request_delay.q", "falling": "out_ack"}),
        "b": ("AsymmetricC", {"COMMON": "1", "RISING": "0", "FALLING": "1", "COMMON_INVERT": "0", "RISING_INVERT": "0", "FALLING_INVERT": "0"},
              {"common": "acknowledge.q", "falling": "long_hold.q"}),
        "acknowledge": ("AsymmetricC", {"COMMON": "1", "RISING": "1", "FALLING": "1", "COMMON_INVERT": "1", "RISING_INVERT": "0", "FALLING_INVERT": "0"},
              {"common": "b.q", "rising": "long_hold.q", "falling": "request_delay.q"}),
        "payload": ("ClosingLatch", {"WIDTH": "40"}, {"closed": "long_hold.q", "d": "data_delay.q"}),
    }
    assert set(cells) == set(expected), "TOPOLOGY_CELL_INVENTORY"
    def resolve(ref):
        return cells[ref[:-2]][2]["q"] if ref.endswith(".q") else canonical(ref)
    for name, (model, params, connections) in expected.items():
        actual_model, actual_params, ports = cells[name]
        assert actual_model == f"ChiselAsync{model}_v1", "TOPOLOGY_CELL_MODEL"
        assert all(actual_params.get(k) == v for k, v in params.items()), "TOPOLOGY_CELL_PARAMETERS"
        assert ports["reset"] == canonical("reset"), "TOPOLOGY_RESET"
        assert all(ports.get(p) == resolve(ref) for p, ref in connections.items()), f"TOPOLOGY_CONNECTION:{name}"
    for port, ref in (("in_ack", "acknowledge.q"), ("out_req", "output_delay.q"), ("out_bits", "payload.q")):
        assert canonical(port) == resolve(ref), f"TOPOLOGY_OUTPUT:{port}"
    return {"cells": len(cells), "state_cells": 3, "source_figure": "Furber-Day Fig. 15 (atomic input bubbles)"}
