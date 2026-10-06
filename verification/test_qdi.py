# SPDX-License-Identifier: Apache-2.0
"""Independent QDI campaign and obligation-ledger checks."""
import pytest

import run_qdi as qdi


def channels(fixture="qdi_buffer"):
    c = lambda name, role, width: dict(id="Top::" + name, local_id=name, root=True, role=role,
                                     protocol="dual-rail-rtz-v1", width=width)
    if fixture == "qdi_fork": return [c("in", "input", 2), *[c("out" + str(i), "output", 2) for i in range(3)]]
    if fixture == "qdi_join": return [c("left_input", "input", 1), c("right_input", "input", 2), c("out", "output", 3)]
    if fixture == "qdi_demux": return [c("in", "input", 3), c("out0", "output", 2), c("out1", "output", 2)]
    return [c("in", "input", 3), c("out", "output", 3)]


def offer(ledger, name, value, width, ack=0, epoch=1):
    ledger.event(epoch, False, "Top::" + name, 0, ack, value, ((1 << width) - 1) ^ value)


def test_boolean_and_arithmetic_oracles_cover_all_small_words():
    assert [qdi.truth("qdi_not", x) for x in range(2)] == [1, 0]
    assert [qdi.truth("qdi_and", x) for x in range(4)] == [0, 0, 0, 1]
    assert [qdi.truth("qdi_or", x) for x in range(4)] == [0, 1, 1, 1]
    assert [qdi.truth("qdi_xor", x) for x in range(4)] == [0, 1, 1, 0]
    assert [qdi.truth("qdi_select", x) for x in range(8)] == [0, 1, 0, 1, 0, 0, 1, 1]
    assert [qdi.truth("qdi_adder", x) for x in range(8)] == [0, 1, 1, 2, 1, 2, 2, 3]
    assert {qdi.truth("qdi_constant", x) for x in range(8)} == {1}
    assert [qdi.truth("qdi_composition", x) for x in range(4)] == [0, 2, 4, 6]


def test_permutation_inventory_and_exact_activities():
    assert len(qdi.permutations(1)) == 1
    assert len(qdi.permutations(2)) == 2
    assert len(qdi.permutations(3)) == 6
    assert len(set(qdi.permutations(3))) == 6
    assert len(qdi.permutations(10)) == 2
    assert qdi.case_contract("qdi_buffer")["steady_transfers"] == 288
    assert qdi.case_contract("qdi_buffer")["deliveries"] == 295
    assert qdi.case_contract("qdi_packet")["deliveries"] == 4124
    assert qdi.case_contract("qdi_fork")["deliveries"] == 1741
    assert qdi.case_contract("qdi_join")["steady_transfers"] == 288
    assert qdi.case_contract("qdi_merge")["steady_transfers"] == 32
    assert qdi.case_contract("qdi_composition")["deliveries"] == 128


def test_output_completion_before_input_ack_is_legal():
    ledger = qdi.Ledger("qdi_buffer", channels())
    offer(ledger, "in", 5, 3)
    offer(ledger, "out", 5, 3)
    offer(ledger, "out", 5, 3, ack=1)
    assert ledger.delivered == {"Top::out": 1}
    assert ledger.completed == {}
    offer(ledger, "in", 5, 3, ack=1)
    assert ledger.completed == {"Top::in": 1}
    assert not ledger.queues["Top::out"]


def test_reset_preserves_a_completed_fork_branch_and_aborts_only_others():
    ledger = qdi.Ledger("qdi_fork", channels("qdi_fork"))
    offer(ledger, "in", 2, 2)
    for index in range(3): offer(ledger, "out" + str(index), 2, 2)
    offer(ledger, "out0", 2, 2, ack=1)
    ledger.event(1, True, "Top::in", 0, 0, 0, 0)
    assert ledger.delivered == {"Top::out0": 1}
    assert ledger.aborted == {"Top::out0": 0, "Top::out1": 1, "Top::out2": 1}
    assert not ledger.pending and not any(ledger.queues.values())


def test_join_waits_for_both_operands_and_packs_left_high():
    ledger = qdi.Ledger("qdi_join", channels("qdi_join"))
    offer(ledger, "left_input", 1, 1)
    with pytest.raises(AssertionError, match="QDI_JOIN_EARLY"):
        offer(ledger, "out", 6, 3)
    # A checker failure consumes protocol state, so use a fresh ledger.
    ledger = qdi.Ledger("qdi_join", channels("qdi_join"))
    offer(ledger, "right_input", 2, 2)
    offer(ledger, "left_input", 1, 1)
    offer(ledger, "out", 6, 3)
    offer(ledger, "out", 6, 3, ack=1)
    assert ledger.delivered == {"Top::out": 1}
    assert not any(ledger.queues.values())


def test_demux_only_creates_obligation_for_selected_output():
    ledger = qdi.Ledger("qdi_demux", channels("qdi_demux"))
    offer(ledger, "in", 6, 3)
    assert not ledger.queues["Top::out0"]
    assert list(ledger.queues["Top::out1"]) == [2]
    with pytest.raises(AssertionError, match="QDI_UNEXPECTED_OUTPUT"):
        offer(ledger, "out0", 2, 2)


@pytest.mark.parametrize("word", (0, 1, 3, 7))
def test_wrong_values_fail_even_when_rail_codes_are_valid(word):
    ledger = qdi.Ledger("qdi_buffer", channels())
    offer(ledger, "in", word, 3)
    with pytest.raises(AssertionError, match="QDI_VALUE"):
        offer(ledger, "out", word ^ 1, 3)


def test_invalid_and_nonmonotonic_rails_have_specific_diagnostics():
    ledger = qdi.Ledger("qdi_buffer", channels())
    with pytest.raises(AssertionError, match="INVALID_RAIL"):
        ledger.event(1, False, "Top::in", 0, 0, 1, 1)
    ledger = qdi.Ledger("qdi_buffer", channels())
    ledger.event(1, False, "Top::in", 0, 0, 1, 0)
    with pytest.raises(AssertionError, match="RAIL_ORDER"):
        ledger.event(1, False, "Top::in", 0, 0, 0, 0)


@pytest.mark.parametrize("text,diagnostic", (("", "QDI_TRACE_SCHEMA"), ("STALE_PASS\n", "QDI_TRACE_SCHEMA"),
                                           ("QDI_TRACE|1\nC|1|Top::in|0\nC|1|Top::in|0\n", "QDI_DUPLICATE_WITNESS"),
                                           ("QDI_TRACE|1\nE|2|1|0|Top::in|0|0|0|0\nE|1|1|0|Top::in|0|0|0|0\n", "QDI_TRACE_ORDER")))
def test_trace_corruption_is_not_a_pass(tmp_path, text, diagnostic):
    path = tmp_path / "trace.txt"
    path.write_text(text)
    with pytest.raises(AssertionError, match=diagnostic):
        qdi.replay("qdi_buffer", channels(), path, complete=False)


def test_empty_suite_cannot_finish_as_pass():
    ledger = qdi.Ledger("qdi_buffer", channels())
    with pytest.raises(AssertionError, match="QDI_NOT_IDLE"):
        ledger.finish()


def test_incomplete_epoch_inventory_is_rejected_before_activity_count():
    ledger = qdi.Ledger("qdi_buffer", channels())
    ledger.event(1, False, "Top::in", 0, 0, 0, 0)
    with pytest.raises(AssertionError, match="QDI_EPOCH_INVENTORY"):
        ledger.finish()


def test_missing_completion_witness_rejects_a_quiescent_trace():
    ledger = qdi.Ledger("qdi_buffer", channels())
    ledger.resetting = False
    ledger.epochs = set(range(1, 7))
    with pytest.raises(AssertionError, match="QDI_COMPLETION_WITNESS"):
        ledger.finish()


def test_coincident_valid_and_ack_does_not_invent_an_unobserved_offer():
    ledger = qdi.Ledger("qdi_buffer", channels())
    # One settled row cannot prove the required earlier complete-valid phase.
    with pytest.raises(AssertionError, match="RAIL_EARLY_ACK"):
        offer(ledger, "in", 5, 3, ack=1)


def test_separated_valid_and_ack_records_both_events():
    ledger = qdi.Ledger("qdi_buffer", channels())
    offer(ledger, "in", 5, 3)
    assert ledger.offered == {"Top::in": 1} and not ledger.completed
    offer(ledger, "in", 5, 3, ack=1)
    assert ledger.completed == {"Top::in": 1}


def test_coincident_spacer_and_ack_return_obeys_rtz_convention():
    ledger = qdi.Ledger("qdi_buffer", channels())
    offer(ledger, "in", 5, 3)
    offer(ledger, "in", 5, 3, ack=1)
    ledger.event(1, False, "Top::in", 0, 0, 0, 0)
    assert ledger.monitors["Top::in"].idle()
    assert ledger.completed == {"Top::in": 1}


def timing_manifest():
    primitives = [dict(id="cell" + str(i), model="ChiselAsyncControlGate_v1", rtl_path="Top.cell" + str(i), parameters={"DELAY_FS": 1000000}) for i in range(40)]
    return dict(top="Top", design=dict(rtl_path="Top", primitives=primitives, children=[],
                timing=[dict(kind="qdi-digital-v1", cells=dict(min_fs="1000000", max_fs="10000000", model_fs="1000000"))]))


def test_delay_samples_cover_every_declared_qdi_cell_reproducibly():
    manifest = timing_manifest()
    first = qdi.checked_overrides(manifest, 17)
    assert len(first) == 40 and first == qdi.checked_overrides(manifest, 17)
    assert first != qdi.checked_overrides(manifest, 18)
    assert len({line.rsplit("=", 1)[1] for line in first}) > 1
    assert qdi.checked_overrides(manifest, 0) == []
    assert all(line.endswith("=1000000;") for line in qdi.checked_overrides(manifest, 1))
    assert all(line.endswith("=10000000;") for line in qdi.checked_overrides(manifest, 2))


def test_out_of_bound_nominal_delay_is_rejected():
    manifest = timing_manifest()
    manifest["design"]["primitives"][0]["parameters"]["DELAY_FS"] = 0
    with pytest.raises(AssertionError, match="QDI_DELAY_OUTSIDE_BOUNDS"):
        qdi.checked_overrides(manifest, 0)


def test_missing_sample_for_a_qdi_cell_is_rejected(monkeypatch):
    monkeypatch.setattr(qdi, "delay_overrides", lambda *a: [])
    with pytest.raises(AssertionError, match="QDI_UNVARIED_PRIMITIVE"):
        qdi.checked_overrides(timing_manifest(), 17)


def test_raw_source_corruption_rejects_stale_pass_summary(tmp_path):
    source = tmp_path / "model.sv"
    source.write_text("original")
    row = {"status": "PASS", "sources": {source.name: qdi.sha(source)}}
    qdi.write(tmp_path / "case.json", row)
    source.write_text("changed")
    with pytest.raises(AssertionError, match="QDI_SOURCE_HASH"):
        qdi.audit_case(row, tmp_path, {})


def test_raw_trace_corruption_rejects_stale_pass_summary(tmp_path):
    row = {"status": "PASS", "sources": {}}
    for name, field in (("bench.sv", "bench_sha256"), ("trace.txt", "trace_sha256"), ("simulation.log", "log_sha256")):
        p = tmp_path / name
        p.write_text("original")
        row[field] = qdi.sha(p)
    qdi.write(tmp_path / "case.json", row)
    (tmp_path / "trace.txt").write_text("changed")
    with pytest.raises(AssertionError, match="QDI_ARTIFACT_HASH"):
        qdi.audit_case(row, tmp_path, {})


def test_existing_attempt_cannot_be_overwritten(monkeypatch, tmp_path):
    path = tmp_path / "report.json"
    path.write_text('{"status":"ERROR","error":"retained"}')
    before = path.read_bytes()
    monkeypatch.setattr(qdi.sys, "argv", ["run_qdi.py", "--output", str(tmp_path)])
    with pytest.raises(AssertionError, match="QDI_OUTPUT_EXISTS"):
        qdi.main()
    assert path.read_bytes() == before
