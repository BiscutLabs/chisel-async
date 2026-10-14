# SPDX-License-Identifier: Apache-2.0
"""Version 1 additive export validators; no stimulus or reset-policy hooks.

Callbacks are trusted local Python, not sandboxed plugins. They receive detached,
read-only observations, never the mutable manifest, probe plan or coverage state.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from types import MappingProxyType
from typing import Callable, Mapping

API_VERSION = 1
_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"


def _require(condition, diagnostic):
    if not condition:
        raise ValueError(diagnostic)


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class EndpointSelector:
    """Semantic child-ID path and endpoint ID; optional unsigned packed slice."""
    instance: tuple[str, ...]
    endpoint: str
    lsb: int = 0
    width: int | None = None

    def __post_init__(self):
        _require(type(self.instance) is tuple and
                 all(type(part) is str and re.fullmatch(_IDENT, part) for part in self.instance),
                 "EXTENSION_INVALID_INSTANCE")
        _require(type(self.endpoint) is str and re.fullmatch(_IDENT, self.endpoint),
                 "EXTENSION_INVALID_ENDPOINT")
        _require(type(self.lsb) is int and self.lsb >= 0 and
                 (self.width is None or type(self.width) is int and self.width > 0),
                 "EXTENSION_INVALID_SLICE")


@dataclass(frozen=True)
class ResolvedEndpoint:
    instance: tuple[str, ...]
    endpoint: str
    rtl_path: str
    width: int
    instance_path: str
    compiled_module: str

    def slice(self, lsb: int = 0, width: int | None = None) -> ResolvedSlice:
        width = self.width - lsb if width is None and type(lsb) is int else width
        _require(type(lsb) is int and type(width) is int and lsb >= 0 and
                 width > 0 and lsb + width <= self.width, "EXTENSION_INVALID_SLICE")
        return ResolvedSlice(self, lsb, width)


@dataclass(frozen=True)
class ResolvedSlice:
    endpoint: ResolvedEndpoint
    lsb: int
    width: int

    @property
    def rtl_expression(self):
        if self.lsb == 0 and self.width == self.endpoint.width:
            return self.endpoint.rtl_path
        return f"{self.endpoint.rtl_path}[{self.lsb} +: {self.width}]"


@dataclass(frozen=True)
class ResolvedExport:
    """Detached observations of a validated manifest and compiled scopes."""
    top: str
    endpoints: Mapping
    instances: Mapping
    scopes: Mapping
    contracts: Mapping

    def endpoint(self, instance: tuple[str, ...], endpoint: str) -> ResolvedEndpoint:
        EndpointSelector(instance, endpoint)
        _require((instance, endpoint) in self.endpoints, "EXTENSION_UNRESOLVED_ENDPOINT")
        return self.endpoints[instance, endpoint]

    def resolve(self, selector: EndpointSelector) -> ResolvedSlice:
        _require(type(selector) is EndpointSelector, "EXTENSION_INVALID_SELECTOR")
        return self.endpoint(selector.instance, selector.endpoint).slice(selector.lsb, selector.width)

    def scope(self, instance: tuple[str, ...]):
        _require(type(instance) is tuple and instance in self.instances, "EXTENSION_UNRESOLVED_INSTANCE")
        return self.scopes[self.instances[instance]]


@dataclass(frozen=True)
class EndpointEquality:
    """Read-only equality at every existing mandatory mapping-probe sample."""
    diagnostic_id: str
    left: EndpointSelector
    right: EndpointSelector


@dataclass(frozen=True)
class ExportValidator:
    """A structural check returning exactly bool after mandatory probes pass."""
    diagnostic_id: str
    validate: Callable[[ResolvedExport], bool]


def resolved_export(manifest, scopes):
    endpoints, instances, contracts = {}, {}, {}

    def visit(node, identity):
        path = node["rtl_path"]
        _require(path in scopes, "EXTENSION_UNRESOLVED_INSTANCE")
        instances[identity] = path
        contracts[identity] = _freeze(node)
        for endpoint in node["endpoints"]:
            rtl_path = endpoint["rtl_path"]
            _require(re.fullmatch(_IDENT + r"(?:\." + _IDENT + r")*", rtl_path),
                     "EXTENSION_INVALID_RTL_REFERENCE")
            owner, name = rtl_path.rsplit(".", 1)
            _require(owner in scopes and scopes[owner]["nets"].get(name) == endpoint["width"],
                     "EXTENSION_UNRESOLVED_ENDPOINT")
            endpoints[identity, endpoint["id"]] = ResolvedEndpoint(
                identity, endpoint["id"], rtl_path, endpoint["width"], path, scopes[path]["model"])
        for child in node["children"]:
            visit(child["contract"], (*identity, child["id"]))

    visit(manifest["design"], ())
    return ResolvedExport(manifest["top"], MappingProxyType(endpoints), MappingProxyType(instances),
                          _freeze(scopes), MappingProxyType(contracts))


def prepare_validators(validators, context):
    _require(type(validators) in (tuple, list), "EXTENSION_INVALID_VALIDATORS")
    equalities, structural, seen = [], [], set()
    for validator in validators:
        _require(type(validator) in (EndpointEquality, ExportValidator), "EXTENSION_INVALID_VALIDATOR")
        diagnostic = validator.diagnostic_id
        _require(type(diagnostic) is str and re.fullmatch(r"[A-Z][A-Z0-9_]{0,95}", diagnostic),
                 "EXTENSION_INVALID_DIAGNOSTIC")
        _require(diagnostic not in seen, "EXTENSION_DUPLICATE_DIAGNOSTIC")
        seen.add(diagnostic)
        if type(validator) is EndpointEquality:
            left, right = context.resolve(validator.left), context.resolve(validator.right)
            _require(left.width == right.width, "EXTENSION_WIDTH_MISMATCH")
            _require(left.rtl_expression != right.rtl_expression, "EXTENSION_VACUOUS_EQUALITY")
            equalities.append((diagnostic, left, right))
        else:
            _require(callable(validator.validate), "EXTENSION_INVALID_CALLBACK")
            structural.append(validator)
    return tuple(equalities), tuple(structural)


def equality_statements(equalities):
    # Only internally resolved references reach Verilog. Extensions cannot emit
    # code, change drivers, reset relationships, coverage collectors or criteria.
    return [f'if ({left.rtl_expression} !== {right.rtl_expression}) '
            f'$fatal(1, "EXPORT_EXTENSION_FAILED:{diagnostic}");'
            for diagnostic, left, right in equalities]


def required_coverage(manifest):
    """Library-owned inventory, independent of all extension declarations."""
    inventory = []

    def visit(node, identity):
        inventory.extend([list(identity), endpoint["id"], endpoint["width"]]
                         for endpoint in node["endpoints"])
        for child in node["children"]:
            visit(child["contract"], (*identity, child["id"]))

    visit(manifest["design"], ())
    _require(bool(inventory), "EMPTY_REQUIRED_COVERAGE")
    bits = sum(item[2] for item in inventory)
    return {"endpoint_count": len(inventory), "endpoint_bits": bits,
            "required_bit_polarities": 2 * bits,
            "inventory_sha256": hashlib.sha256(json.dumps(inventory, separators=(",", ":")).encode()).hexdigest()}


def validate_structural(validators, manifest, scopes):
    results = []
    for validator in validators:
        try:
            # Recreate each snapshot so even a callback bypassing frozen fields
            # cannot alter another validator's observations or core evidence.
            result = validator.validate(resolved_export(manifest, scopes))
        except Exception as error:
            raise ValueError(f"EXPORT_EXTENSION_ERROR:{validator.diagnostic_id}") from error
        _require(type(result) is bool, f"EXPORT_EXTENSION_INVALID_RESULT:{validator.diagnostic_id}")
        _require(result, f"EXPORT_EXTENSION_FAILED:{validator.diagnostic_id}")
        results.append({"diagnostic_id": validator.diagnostic_id, "kind": "structural", "checks": 1, "status": "PASS"})
    return results
