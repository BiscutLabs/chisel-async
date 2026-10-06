# SPDX-License-Identifier: Apache-2.0
"""Directed sequence evidence must prove activity and the intended rejection."""
import copy

import pytest

import run_qdi_sequences as sequences

q = sequences.q


def channels():
    return [dict(id="Top::" + name, local_id=name, root=True, role=role,
                 protocol="dual-rail-rtz-v1", width=3) for name, role in (("in", "input"), ("out", "output"))]


def transaction(ledger, value, epoch=1):
    for name, ack, one, zero in (("in", 0, value, 7 ^ value), ("out", 0, value, 7 ^ value),
                                  ("in", 1, value, 7 ^ value), ("out", 1, value, 7 ^ value),
                                  ("in", 1, 0, 0), ("out", 1, 0, 0), ("in", 0, 0, 0), ("out", 0, 0, 0)):
        ledger.event(epoch, False, "Top::" + name, 0, ack, one, zero)


def source_ledger():
    ledger = q.Ledger("qdi_buffer", channels())
    transaction(ledger, 0)
    transaction(ledger, 7)
    ledger.witnesses = {(1, "Top::in"): 2, (1, "Top::out"): 2}
    return ledger


SOURCE = dict(kind="source", fixture="qdi_buffer", seed=17, id="source")


def test_selection_covers_every_strong_fixture_and_measured_chain_length():
    selected = sequences.selection([17, 101])
    assert len(selected) == 37 and len({s["id"] for s in selected}) == 37
    assert len(sequences.FIXTURES) == 12
    assert [(s["length"], s["seed"]) for s in selected if s["kind"] == "chain"] == [
        (n, seed) for n in range(1, 7) for seed in (17, 101)]
    assert sum(s["kind"] == "reset" for s in selected) == 1


def test_exact_two_token_activity_and_witnesses_pass():
    result = sequences.check_ledger(SOURCE, channels(), source_ledger())
    assert result["offered"] == result["accepted"] == {"Top::in": 2}
    assert result["delivered"] == {"Top::out": 2}


@pytest.mark.parametrize("fault,diagnostic", [
    ("missing_acceptance", "QDI_SEQUENCE_ACTIVITY"),
    ("missing_delivery", "QDI_SEQUENCE_ACTIVITY"),
    ("missing_offer", "QDI_SEQUENCE_OFFERS"),
    ("missing_witness", "QDI_SEQUENCE_WITNESSES"),
    ("wrong_witness", "QDI_SEQUENCE_WITNESSES"),
    ("missing_epoch", "QDI_SEQUENCE_EPOCHS"),
    ("undrained", "QDI_SEQUENCE_CONSERVATION"),
])
def test_missing_activity_cannot_pass_as_a_completed_case(fault, diagnostic):
    ledger = source_ledger()
    if fault == "missing_acceptance": ledger.completed.clear()
    elif fault == "missing_delivery": ledger.delivered["Top::out"] = 1
    elif fault == "missing_offer": ledger.offered.clear()
    elif fault == "missing_witness": ledger.witnesses.pop((1, "Top::in"))
    elif fault == "wrong_witness": ledger.witnesses[(1, "Top::in")] = 1
    elif fault == "missing_epoch": ledger.epochs.clear()
    else: ledger.queues["Top::out"].append(7)
    with pytest.raises(AssertionError, match="^" + diagnostic + "$"):
        sequences.check_ledger(SOURCE, channels(), ledger)


def test_delivery_before_acceptance_reset_does_not_invent_an_abort():
    ledger = q.Ledger("qdi_buffer", channels())
    for name, ack in (("in", 0), ("out", 0), ("out", 1)):
        ledger.event(1, False, "Top::" + name, 0, ack, 5, 2)
    ledger.event(1, True, "Top::in", 0, 0, 0, 0)
    transaction(ledger, 3, epoch=2)
    ledger.witnesses = {(1, "Top::in"): 0, (1, "Top::out"): 1, (2, "Top::in"): 1, (2, "Top::out"): 1}
    result = sequences.check_ledger(dict(SOURCE, kind="reset"), channels(), ledger)
    assert result["offered"] == {"Top::in": 2}
    assert result["accepted"] == {"Top::in": 1}
    assert result["delivered"] == {"Top::out": 2} and sum(result["aborted"].values()) == 0


@pytest.mark.parametrize("code,diagnostic,activation", [
    (1, "QDI_SEQUENCE_DEADLINE", True), (1, "QDI_SEQUENCE_VALUE", True),
    (0, sequences.DIAGNOSTIC, True), (1, sequences.DIAGNOSTIC, False),
])
def test_timeout_wrong_failure_or_unactivated_control_is_rejected(code, diagnostic, activation):
    log = ("QDI_SEQUENCE:ACCEPTED\n" if activation else "") + f"FATAL: bench.sv:42: {diagnostic}\n"
    with pytest.raises(AssertionError, match="^QDI_SEQUENCE_WRONG_REJECTION$"):
        sequences.check_log(dict(SOURCE, mutant=True), code, log)


def test_pass_text_without_required_sequence_activity_is_rejected():
    with pytest.raises(AssertionError, match="^QDI_SEQUENCE_MARKERS$"):
        sequences.check_log(SOURCE, 0, "QDI_SEQUENCE_PASS\n")
    with pytest.raises(AssertionError, match="^QDI_SEQUENCE_CAPACITY_EVIDENCE$"):
        sequences.check_log(dict(SOURCE, kind="chain", length=3), 0, "QDI_SEQUENCE_CAPACITY:1\nQDI_SEQUENCE_PASS\n")


@pytest.fixture
def paired_cases(tmp_path):
    directory = q.ROOT / "target/generated/qdi_buffer"
    assert (directory / "contract.json").is_file(), "Required QDI export missing; run EmitQdi"
    manifest = q.read(directory / "contract.json")["manifest"]
    ports = q.read(directory / "ports.json")["nodes"][0]["ports"]
    sources = {p.name: p.read_text(encoding="utf-8") for p in q.read_sources(directory)}
    rows = []
    for mutant in (False, True):
        spec = dict(SOURCE, seed=0, mutant=mutant)
        output = tmp_path / ("mutant" if mutant else "baseline")
        rows.append((sequences.execute(spec, manifest, ports, sources, output), output))
    return rows, q.channel_catalog(manifest)


def test_actual_rtl_reservation_mutation_has_same_bench_and_exact_failure(paired_cases):
    ((baseline, _), (mutant, _)), _ = paired_cases
    assert baseline["status"] == "PASS" and mutant["status"] == "EXPECTED_REJECTION"
    assert baseline["hashes"]["bench.sv"] == mutant["hashes"]["bench.sv"]
    changed = [name for name in baseline["hashes"] if name.endswith(".sv") and baseline["hashes"][name] != mutant["hashes"][name]]
    assert changed == ["DualRailStrongBuffer.sv"]
    assert sum(baseline["evidence"]["accepted"].values()) == sum(baseline["evidence"]["delivered"].values()) == 2
    assert mutant["evidence"] == {"diagnostic": sequences.DIAGNOSTIC}


@pytest.mark.parametrize("artifact", ["bench.sv", "simulation.log", "trace.txt", "DualRailStrongBuffer.sv"])
def test_altered_raw_evidence_cannot_reuse_a_pass_summary(paired_cases, artifact):
    ((row, directory), _), catalog = paired_cases
    with (directory / artifact).open("a", encoding="utf-8") as stream: stream.write("\nchanged\n")
    with pytest.raises(AssertionError, match="^QDI_SEQUENCE_ARTIFACT_HASH$"):
        sequences.audit_case(row, directory, catalog)


def test_rehashed_missing_delivery_still_fails_replay(paired_cases):
    ((original, directory), _), catalog = paired_cases
    row = copy.deepcopy(original)
    row["evidence"]["delivered"] = {}
    q.write(directory / "case.json", row)
    with pytest.raises(AssertionError, match="^QDI_SEQUENCE_REPLAY_SUMMARY$"):
        sequences.audit_case(row, directory, catalog)


def test_existing_attempt_is_retained(monkeypatch, tmp_path):
    path = tmp_path / "report.json"
    path.write_text('{"status":"ERROR","error":"retained"}', encoding="utf-8")
    original = path.read_bytes()
    monkeypatch.setattr(sequences.sys, "argv", ["run_qdi_sequences.py", "--output", str(tmp_path)])
    with pytest.raises(AssertionError, match="^QDI_SEQUENCE_OUTPUT_EXISTS"):
        sequences.main()
    assert path.read_bytes() == original
