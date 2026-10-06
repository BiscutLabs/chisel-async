# SPDX-License-Identifier: Apache-2.0
import pytest

from reference import FourPhaseContract, TwoPhaseContract, TokenLedger, reset_prefixes, two_token_schedules


@pytest.mark.parametrize("prefix,legal", [
    ([], ("req", 1)), ([("req", 1)], ("ack", 1)),
    ([("req", 1), ("ack", 1)], ("req", 0)),
    ([("req", 1), ("ack", 1), ("req", 0)], ("ack", 0)),
])
def test_two_phase_state_table_and_reset(prefix, legal):
    for edge in (("req", 0), ("req", 1), ("ack", 0), ("ack", 1)):
        model = TwoPhaseContract()
        for prior in prefix:
            model.edge(*prior)
        if edge == legal:
            model.edge(*edge)
        else:
            with pytest.raises(AssertionError, match="TWO_PHASE_ORDER"):
                model.edge(*edge)
        delivered = model.delivered
        model.reset()
        assert (model.req, model.ack, model.delivered) == (0, 0, delivered)
        model.edge("req", 1)
        model.edge("ack", 1)
        assert model.delivered == delivered + 1


def test_two_phase_counts_both_polarities_as_tokens():
    model = TwoPhaseContract()
    for edge in (("req", 1), ("ack", 1), ("req", 0), ("ack", 0)) * 3:
        model.edge(*edge)
    assert model.delivered == 6 and model.req == model.ack == 0


@pytest.mark.parametrize("phase", range(4))
def test_every_illegal_handshake_edge_is_rejected(phase):
    for edge in FourPhaseContract.ORDER:
        model = FourPhaseContract()
        for prior in FourPhaseContract.ORDER[:phase]:
            model.edge(*prior)
        if edge == FourPhaseContract.ORDER[phase]:
            model.edge(*edge)
        else:
            with pytest.raises(AssertionError):
                model.edge(*edge)


def test_reset_starts_a_new_handshake_from_each_phase():
    for phase in range(4):
        model = FourPhaseContract()
        for edge in FourPhaseContract.ORDER[:phase]:
            model.edge(*edge)
        model.reset()
        for edge in FourPhaseContract.ORDER:
            model.edge(*edge)
        assert model.phase == 0


def test_ledger_repeated_values_delivery_reset_and_capacity():
    model = TokenLedger(2)
    model.accept(7)
    model.accept(7)
    with pytest.raises(AssertionError, match="CAPACITY_EXCEEDED"):
        model.accept(7)
    model.deliver(7)
    # Delivered-but-not-returned still reserves capacity and is not aborted.
    model.reset()
    assert model.summary() == {"capacity": 2, "accepted": 2, "delivered": 1,
        "returned": 0, "aborted": 1, "reserved": 0, "peak_reserved": 2,
        "epoch": 1, "outstanding": 0}
    model.accept(9)
    model.deliver(9)
    model.return_idle()
    assert model.accepted == model.delivered + model.aborted == 3


def test_ledger_rejects_unsolicited_and_wrong_payloads():
    model = TokenLedger(1)
    with pytest.raises(AssertionError, match="UNEXPECTED_TOKEN"):
        model.offer(1)
    model.accept(3)
    with pytest.raises(AssertionError, match="PAYLOAD_MISMATCH"):
        model.offer(4)
    model.deliver(3)
    with pytest.raises(AssertionError, match="CAPACITY_EXCEEDED"):
        model.accept(4)
    model.return_idle()
    with pytest.raises(AssertionError, match="UNEXPECTED_COMPLETION"):
        model.return_idle()


def test_schedules_include_each_source_sink_order_and_pending_requests():
    schedules = two_token_schedules()
    assert len(schedules) == len(set(schedules)) == 18
    # Hand-derived representative cases, not generated expected controller states.
    for example in (("p0", "r0", "p1", "a0", "z0", "r1", "a1", "z1"),
                    ("p0", "a0", "z0", "r0", "p1", "a1", "z1", "r1"),
                    ("p0", "a0", "r0", "z0", "p1", "a1", "r1", "z1")):
        assert example in schedules
    prefixes = reset_prefixes()
    assert len(prefixes) == 68
    assert () in prefixes
    assert ("p0", "r0", "p1") in prefixes  # full storage plus unaccepted offer
    assert all(schedule in prefixes for schedule in schedules)
