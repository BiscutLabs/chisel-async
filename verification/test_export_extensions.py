# SPDX-License-Identifier: Apache-2.0
"""Additive export validators against real compiler exports and wiring faults."""
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import re
import shutil
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from check_export import semantic_hash, validate_export, validate_manifest
import export_extensions
from export_extensions import EndpointEquality, EndpointSelector, ExportValidator, required_coverage
from test_export import edit_manifest


@pytest.fixture
def pipeline(tmp_path):
    source = ROOT / "target/generated/pipeline"
    assert (source / "contract.json").is_file(), "Required export missing; run EmitFixtures"
    directory = tmp_path / "pipeline with spaces"
    shutil.copytree(source, directory)
    return directory


def input_binding(width=None):
    return EndpointEquality("FIRST_INPUT_BINDING", EndpointSelector((), "in_data", width=width),
                            EndpointSelector(("first",), "in_data", width=width))


def test_default_path_does_not_construct_extension_context(pipeline, monkeypatch):
    def unexpected(*_):
        raise AssertionError("Default validation entered the extension API")

    for name in ("required_coverage", "resolved_export", "prepare_validators"):
        monkeypatch.setattr(export_extensions, name, unexpected)
    result = validate_export(pipeline)
    assert result["status"] == "PASS" and result["mapping_checks"] > 0
    assert "required_coverage" not in result and "extension_validation" not in result


def test_empty_probe_abi_preserves_the_existing_core_rejection(pipeline):
    def empty(manifest):
        for field in ("endpoints", "channels", "primitives", "timing", "children"):
            manifest["design"][field] = []
        manifest["resources"] = {}

    document = json.loads((pipeline / "contract.json").read_text())
    (pipeline / document["manifest"]["probe_abi"]["file"]).write_text("// no probe references\n")
    edit_manifest(pipeline, empty, refresh_rtl=True)
    assert validate_manifest(json.loads((pipeline / "contract.json").read_text()))
    # The legacy core rejects this before any extension inventory/context exists.
    # Do not turn schema-level acceptance into a vacuous successful export.
    with pytest.raises(ValueError, match="^EMPTY_PROBE_ABI$"):
        validate_export(pipeline)
    assert json.loads((pipeline / "resolved.json").read_text())["status"] != "PASS"


def test_nonempty_validators_require_an_explicit_api_version(pipeline):
    with pytest.raises(ValueError, match="^EXPORT_EXTENSION_API_REQUIRED$"):
        validate_export(pipeline, validators=[input_binding()])
    assert json.loads((pipeline / "resolved.json").read_text())["status"] != "PASS"


@pytest.mark.parametrize("validators", (None, {}, "", False))
def test_invalid_empty_validator_containers_fail_closed(pipeline, validators):
    with pytest.raises(ValueError, match="^EXTENSION_INVALID_VALIDATORS$"):
        validate_export(pipeline, validators=validators, extension_api_version=1)


def test_empty_required_inventory_has_explicit_failure(pipeline):
    document = json.loads((pipeline / "contract.json").read_text())
    manifest = document["manifest"]
    for field in ("endpoints", "channels", "primitives", "timing", "children"):
        manifest["design"][field] = []
    manifest["resources"] = {}
    document["semantic_sha256"] = semantic_hash(manifest)
    # Schema validation permits a root with no declared endpoints. The later
    # coverage API must not return a zero denominator or an empty success.
    assert validate_manifest(document) is manifest
    with pytest.raises(ValueError, match="^EMPTY_REQUIRED_COVERAGE$"):
        required_coverage(manifest)


def test_required_inventory_can_reside_only_in_a_child():
    coverage = required_coverage({"design": {"endpoints": [], "children": [
        {"id": "leaf", "contract": {"endpoints": [{"id": "data", "width": 8}], "children": []}}
    ]}})
    assert coverage["endpoint_count"] == 1 and coverage["required_bit_polarities"] == 16


def test_equalities_and_structural_validator_preserve_required_coverage(pipeline):
    baseline = validate_export(pipeline)
    original_probe = (pipeline / "contract_probe.sv").read_text()

    def check_port(context):
        endpoint = context.endpoint(("first",), "in_data")
        return (endpoint.width == 8 and context.scope(("first",))["ports"]["in_bits"] ==
                {"name": "in_bits", "direction": "input", "width": 8})

    result = validate_export(pipeline, extension_api_version=1, validators=[input_binding(4), ExportValidator("FIRST_PORT", check_port)])
    assert "required_coverage" not in baseline and "extension_validation" not in baseline
    assert result["mapping_checks"] == baseline["mapping_checks"]
    required = result["required_coverage"]
    assert "observed_bit_polarities" not in required
    assert required["required_bit_polarities"] == 2 * required["endpoint_bits"]
    inventory = required_coverage(json.loads((pipeline / "contract.json").read_text())["manifest"])
    assert required == {**inventory, "mapping_checks": baseline["mapping_checks"]}
    extension = result["extension_validation"]
    assert extension["api_version"] == 1 and extension["structural_checks"] == 1
    assert extension["mapping_checks"] == result["mapping_checks"] // required["endpoint_count"] > 0
    probe = (pipeline / "contract_probe.sv").read_text()
    # Removing only the declared read-only comparison reproduces every base
    # driver, timing/reset comparison, coverage collector and coverage criterion.
    stripped = "\n".join(line for line in probe.splitlines() if "EXPORT_EXTENSION_FAILED:FIRST_INPUT_BINDING" not in line)
    assert stripped == original_probe


def test_connection_mutation_fails_only_the_specific_extra_binding(pipeline):
    validate_export(pipeline, extension_api_version=1, validators=[input_binding()])
    source = pipeline / "PipelineExample.sv"
    text = source.read_text()
    assert text.count(".in_bits  (in_bits)") == 1
    source.write_text(text.replace(".in_bits  (in_bits)", ".in_bits  (~in_bits)"))
    edit_manifest(pipeline, lambda _: None, refresh_rtl=True)
    # The mandatory oracle checks each endpoint against its own source. This
    # extra application connection obligation deliberately goes beyond it.
    assert validate_export(pipeline)["status"] == "PASS"
    with pytest.raises(ValueError, match="^EXPORT_EXTENSION_FAILED:FIRST_INPUT_BINDING$"):
        validate_export(pipeline, extension_api_version=1, validators=[input_binding()])
    log = (pipeline / "contract_simulation.log").read_text()
    probe = (pipeline / "contract_probe.sv").read_text().splitlines()
    line = next(i for i, text in enumerate(probe, 1) if "EXPORT_EXTENSION_FAILED:FIRST_INPUT_BINDING" in text)
    assert f"contract_probe.sv:{line}: EXPORT_EXTENSION_FAILED:FIRST_INPUT_BINDING" in log
    assert "Scope: ContractProbe.check" in log
    assert json.loads((pipeline / "resolved.json").read_text())["status"] != "PASS"


def test_failure_id_is_exact_when_diagnostic_names_share_a_prefix(pipeline):
    source = pipeline / "PipelineExample.sv"
    source.write_text(source.read_text().replace(".in_bits  (in_bits)", ".in_bits  (~in_bits)"))
    edit_manifest(pipeline, lambda _: None, refresh_rtl=True)
    passing = EndpointEquality("BINDING", EndpointSelector((), "out_data"), EndpointSelector(("second",), "out_data"))
    failing = EndpointEquality("BINDING_INPUT", EndpointSelector((), "in_data"), EndpointSelector(("first",), "in_data"))
    with pytest.raises(ValueError, match="^EXPORT_EXTENSION_FAILED:BINDING_INPUT$"):
        validate_export(pipeline, extension_api_version=1, validators=[passing, failing])


def test_extra_successes_cannot_replace_mandatory_polarity_activity(pipeline):
    source = pipeline / "PipelineExample.sv"
    text = source.read_text()
    assert text.count(".in_bits  (in_bits)") == 1
    source.write_text(text.replace(".in_bits  (in_bits)", ".in_bits  (8'b0)"))
    edit_manifest(pipeline, lambda _: None, refresh_rtl=True)
    called = []
    # Identical low bits satisfy an added relation but cannot make the dead
    # first input pass the library's independent both-polarity requirement.
    comparison = EndpointEquality("CONSTANT_BITS_MATCH", EndpointSelector(("first",), "in_data", 0, 1),
                                   EndpointSelector(("first",), "in_data", 1, 1))
    with pytest.raises(ValueError, match="^ENDPOINT_MAPPING_MISMATCH$"):
        validate_export(pipeline, extension_api_version=1, validators=[comparison, ExportValidator("CANNOT_OVERRIDE", lambda _: called.append(1) or True)])
    assert not called
    assert "INACTIVE_ENDPOINT:PipelineExample.ca_child_first.in_bits" in (pipeline / "contract_simulation.log").read_text()
    assert json.loads((pipeline / "resolved.json").read_text())["status"] != "PASS"


def test_deduplicated_instances_keep_semantic_identity(tmp_path):
    directory = tmp_path / "replicated"
    shutil.copytree(ROOT / "target/generated/replicated", directory)
    observed = []

    def inspect(context):
        a = context.endpoint(("lane0", "first"), "in_data")
        b = context.endpoint(("lane2", "first"), "in_data")
        observed.extend([a, b])
        return (a.compiled_module == b.compiled_module and a.instance != b.instance and
                a.instance_path != b.instance_path and a.rtl_path != b.rtl_path and
                context.scope(("lane0",))["model"] == context.scope(("lane2",))["model"])

    result = validate_export(directory, extension_api_version=1, validators=[ExportValidator("DEDUP_IDENTITIES", inspect)])
    assert result["extension_validation"]["structural_checks"] == 1 and len(observed) == 2


@pytest.mark.parametrize("validator,diagnostic", [
    (EndpointEquality("BAD_REFERENCE", EndpointSelector(("missing",), "in_data"), EndpointSelector((), "in_data")), "EXTENSION_UNRESOLVED_ENDPOINT"),
    (EndpointEquality("BAD_WIDTH", EndpointSelector((), "in_data", width=3), EndpointSelector(("first",), "in_data", width=4)), "EXTENSION_WIDTH_MISMATCH"),
    (EndpointEquality("BAD_SLICE", EndpointSelector((), "in_data", 7, 2), EndpointSelector(("first",), "in_data", 7, 2)), "EXTENSION_INVALID_SLICE"),
    (EndpointEquality("NO_CHECK", EndpointSelector((), "in_data"), EndpointSelector((), "in_data")), "EXTENSION_VACUOUS_EQUALITY"),
    (ExportValidator('BAD"); $finish;', lambda _: True), "EXTENSION_INVALID_DIAGNOSTIC"),
    (ExportValidator("NOT_CALLABLE", None), "EXTENSION_INVALID_CALLBACK"),
    (object(), "EXTENSION_INVALID_VALIDATOR"),
])
def test_invalid_extensions_fail_closed(pipeline, validator, diagnostic):
    with pytest.raises(ValueError, match=f"^{re.escape(diagnostic)}$"):
        validate_export(pipeline, extension_api_version=1, validators=[validator])


@pytest.mark.parametrize("result,diagnostic", [(False, "EXPORT_EXTENSION_FAILED"), (1, "EXPORT_EXTENSION_INVALID_RESULT"),
                                              (None, "EXPORT_EXTENSION_INVALID_RESULT"), ({"status": "PASS"}, "EXPORT_EXTENSION_INVALID_RESULT")])
def test_strict_structural_results(pipeline, result, diagnostic):
    with pytest.raises(ValueError, match=f"^{diagnostic}:LOCAL_CHECK$"):
        validate_export(pipeline, extension_api_version=1, validators=[ExportValidator("LOCAL_CHECK", lambda _: result)])
    assert json.loads((pipeline / "resolved.json").read_text())["status"] != "PASS"


def test_callback_observations_are_detached_and_read_only(pipeline):
    def attempt_changes(context):
        with pytest.raises(TypeError):
            context.scope(("first",))["ports"]["in_bits"]["width"] = 0
        with pytest.raises(TypeError):
            context.contracts[()]["endpoints"][0]["width"] = 0
        with pytest.raises(FrozenInstanceError):
            context.endpoint((), "in_data").width = 0
        # Python callbacks are trusted code, not a sandbox. Even deliberately
        # bypassing dataclass freezing must not mutate the checker or next view.
        object.__setattr__(context.endpoint((), "in_data"), "width", 0)
        return True

    result = validate_export(pipeline, extension_api_version=1, validators=[ExportValidator("READ_ONLY", attempt_changes),
        ExportValidator("FRESH_VIEW", lambda c: c.endpoint((), "in_data").width == 8)])
    assert result["extension_validation"]["structural_checks"] == 2


def test_callback_cannot_rewrite_validated_evidence(pipeline):
    def change_source(_):
        path = pipeline / "PipelineExample.sv"
        path.write_text(path.read_text() + "// extension modified source\n")
        return True

    with pytest.raises(ValueError, match="^EXPORT_EXTENSION_MODIFIED_EVIDENCE$"):
        validate_export(pipeline, extension_api_version=1, validators=[ExportValidator("BAD_WRITER", change_source)])


def test_callback_cannot_install_a_success_report(pipeline):
    def fake_report(_):
        (pipeline / "resolved.json").write_text('{"status":"PASS"}')
        return True

    with pytest.raises(ValueError, match="^EXPORT_EXTENSION_MODIFIED_EVIDENCE$"):
        validate_export(pipeline, extension_api_version=1, validators=[ExportValidator("BAD_REPORT", fake_report)])
    assert json.loads((pipeline / "resolved.json").read_text())["status"] == "FAIL"


def test_callback_exception_has_named_diagnostic(pipeline):
    def broken(_):
        raise RuntimeError("validator bug")

    with pytest.raises(ValueError, match="^EXPORT_EXTENSION_ERROR:BROKEN$") as error:
        validate_export(pipeline, extension_api_version=1, validators=[ExportValidator("BROKEN", broken)])
    assert isinstance(error.value.__cause__, RuntimeError)


def test_duplicate_ids_and_unknown_api_are_rejected(pipeline):
    with pytest.raises(ValueError, match="^EXTENSION_DUPLICATE_DIAGNOSTIC$"):
        validate_export(pipeline, extension_api_version=1, validators=[input_binding(), input_binding()])
    for version in (0, 2, True, "1"):
        with pytest.raises(ValueError, match="^UNSUPPORTED_EXPORT_EXTENSION_API$"):
            validate_export(pipeline, extension_api_version=version)


@pytest.mark.parametrize("instance,endpoint,lsb,width,diagnostic", [
    (["first"], "in_data", 0, None, "EXTENSION_INVALID_INSTANCE"),
    (("first;force",), "in_data", 0, None, "EXTENSION_INVALID_INSTANCE"),
    ((), "in_data; $finish", 0, None, "EXTENSION_INVALID_ENDPOINT"),
    ((), "in_data", True, None, "EXTENSION_INVALID_SLICE"),
    ((), "in_data", 0, False, "EXTENSION_INVALID_SLICE"),
])
def test_no_raw_verilog_reference_or_invalid_slice(instance, endpoint, lsb, width, diagnostic):
    with pytest.raises(ValueError, match=f"^{diagnostic}$"):
        EndpointSelector(instance, endpoint, lsb, width)
