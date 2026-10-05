# SPDX-License-Identifier: Apache-2.0
"""Transaction-based checks, independent of the production SV state machine."""
import itertools
import functools
import os
import random

import cocotb
from cocotb.triggers import ReadOnly, Timer, with_timeout
from observers import BufferMonitor, Evidence
from reference import reset_prefixes, two_token_schedules

FIXTURE = os.environ["FIXTURE"]
IS_CELEMENT = FIXTURE == "celement"
IS_PACKET = FIXTURE in ("packet", "structural_packet")
IS_SINGLE = FIXTURE not in ("pipeline", "structural_pipeline", "celement")


def expected_payload(value):
    # Independent integer oracle for the fixture's declared byte-wise transform.
    return value ^ 0x55 if FIXTURE == "transform" else value


def observed_test(*, single=False):
    def decorate(test):
        @functools.wraps(test)
        async def run(dut):
            evidence = Evidence(test.__name__)
            monitor = BufferMonitor(dut, payload, lambda port: payload_fields(dut, port),
                                    evidence, 1 if IS_SINGLE else 2, expected_payload)
            try:
                await reset_buffer(dut, evidence)
                monitor.start()
                # Let listeners arm without changing the design's behavior.
                await tick()
                await test(dut, monitor)
                monitor.finish()
            except BaseException as error:
                evidence.save("FAIL", monitor.failure or str(error), **monitor.summary())
                if monitor.failure:
                    raise AssertionError(monitor.failure) from error
                raise
            else:
                evidence.save("PASS", **monitor.summary())
            finally:
                monitor.stop()
        return cocotb.test(skip=IS_CELEMENT or (single and not IS_SINGLE))(run)
    return decorate


def celement_test(test):
    @functools.wraps(test)
    async def run(dut):
        evidence = Evidence(test.__name__)
        try:
            await test(dut, evidence)
        except BaseException as error:
            evidence.save("FAIL", str(error))
            raise
        else:
            evidence.save("PASS")
    return cocotb.test(skip=not IS_CELEMENT)(run)


async def tick(delay=1):
    # A testbench delay, never a design clock or a simulation of physical gate delay.
    await Timer(delay, unit="ns")


async def wait_value(signal, target):
    async def wait():
        while int(signal.value) != target:
            await signal.value_change
    await with_timeout(wait(), 1000, "ns")


def payload(dut, prefix):
    if IS_PACKET:
        return tuple(int(getattr(dut, f"{prefix}_bits_{suffix}").value)
                     for suffix in ("tag", "signed", "lanes_0", "lanes_1"))
    return int(getattr(dut, f"{prefix}_bits").value)


def payload_fields(dut, prefix):
    if IS_PACKET:
        return [getattr(dut, f"{prefix}_bits_{suffix}")
                for suffix in ("tag", "signed", "lanes_0", "lanes_1")]
    return [getattr(dut, f"{prefix}_bits")]


def drive_payload(dut, value):
    if IS_PACKET:
        for suffix, part in zip(("tag", "signed", "lanes_0", "lanes_1"), value):
            getattr(dut, f"in_bits_{suffix}").value = part
    else:
        dut.in_bits.value = value


def values(dut):
    if IS_PACKET:
        return [(0, 0, 0, 0), (7, 0x1FF, 31, 17), (7, 0x1FF, 31, 17),
                (1, 0x100, 2, 3), (2, 0x0FF, 4, 31)] * 8
    width = len(dut.in_bits)
    maximum = (1 << width) - 1
    return [0, maximum, maximum, 0, 1 << (width - 1), 1, 0x55 & maximum, 0xAA & maximum] * 5


async def reset_buffer(dut, evidence=None):
    # Assert reset before withdrawing offers or changing held data.
    dut.reset.value = 1
    dut.in_req.value = 0
    dut.out_ack.value = 0
    drive_payload(dut, values(dut)[0])
    await tick()
    if evidence:
        evidence.record("reset_check", payload=payload(dut, "out"),
                        ack=str(dut.in_ack.value), req=str(dut.out_req.value))
    assert int(dut.in_ack.value) == 0
    assert int(dut.out_req.value) == 0
    assert all(int(field.value) == 0 for field in payload_fields(dut, "out")), "RESET_DATA_MISMATCH"
    dut.reset.value = 0
    await tick()


@observed_test()
async def transaction_stream(dut, monitor):
    expected = values(dut)
    accepted = 0
    completed = 0
    source_rng = random.Random(0xA51)
    sink_rng = random.Random(0xB82)

    async def source():
        nonlocal accepted
        for value in expected:
            drive_payload(dut, value)
            await tick(source_rng.randint(1, 4))
            dut.in_req.value = 1
            await wait_value(dut.in_ack, 1)
            accepted += 1
            await tick(source_rng.randint(1, 3))
            dut.in_req.value = 0
            await wait_value(dut.in_ack, 0)
            await tick()

    async def sink():
        nonlocal completed
        for value in expected:
            await wait_value(dut.out_req, 1)
            await ReadOnly()
            assert payload(dut, "out") == expected_payload(value), "PAYLOAD_MISMATCH"
            await tick(sink_rng.randint(2, 9))
            assert int(dut.out_req.value) == 1, "REQUEST_WITHDRAWN"
            assert payload(dut, "out") == expected_payload(value), "DATA_CHANGED_UNDER_BACKPRESSURE"
            dut.out_ack.value = 1
            await wait_value(dut.out_req, 0)
            await tick(sink_rng.randint(1, 3))
            assert payload(dut, "out") == expected_payload(value), "DATA_CHANGED_BEFORE_RETURN_IDLE"
            dut.out_ack.value = 0
            completed += 1
            await tick()

    sender = cocotb.start_soon(source())
    receiver = cocotb.start_soon(sink())
    await with_timeout(sender, 20000, "ns")
    await with_timeout(receiver, 20000, "ns")
    assert accepted == completed == len(expected) == 40, "VACUOUS_OR_INCOMPLETE_STREAM"
    assert monitor.ledger.accepted == monitor.ledger.delivered == monitor.ledger.returned == 40
    monitor.evidence.coverage["stream_transactions"] = completed
    await tick(10)
    assert int(dut.out_req.value) == int(dut.in_ack.value) == 0, "DUPLICATE_OR_STALE_TOKEN"


@observed_test(single=True)
async def pending_request_and_capacity(dut, monitor):
    first, second = values(dut)[1], values(dut)[3]
    drive_payload(dut, first)
    await tick()
    dut.in_req.value = 1
    await tick()
    assert int(dut.in_ack.value) == int(dut.out_req.value) == 1
    dut.in_req.value = 0
    await tick()
    assert int(dut.in_ack.value) == 0
    drive_payload(dut, second)
    await tick()
    dut.in_req.value = 1
    await tick(5)
    assert int(dut.in_ack.value) == 0, "CAPACITY_EXCEEDED"
    assert payload(dut, "out") == expected_payload(first), "OVERWROTE_FULL_BUFFER"
    dut.out_ack.value = 1
    await tick()
    assert int(dut.out_req.value) == 0
    assert payload(dut, "out") == expected_payload(first)
    assert int(dut.in_ack.value) == 0
    dut.out_ack.value = 0
    await tick()
    assert int(dut.in_ack.value) == int(dut.out_req.value) == 1
    assert payload(dut, "out") == expected_payload(second), "PENDING_REQUEST_LOST"
    dut.in_req.value = 0
    await tick()
    dut.out_ack.value = 1
    await tick()
    dut.out_ack.value = 0
    await tick()
    assert int(dut.out_req.value) == int(dut.in_ack.value) == 0


@observed_test()
async def reset_aborts_and_restarts(dut, monitor):
    # Reset at idle, offered/accepted, input return, output ack and output return.
    for phase in range(5):
        await reset_buffer(dut, monitor.evidence)
        drive_payload(dut, values(dut)[1])
        await tick()
        if phase >= 1:
            dut.in_req.value = 1
            await tick()
        if phase >= 2:
            dut.in_req.value = 0
            await tick()
        if phase >= 3:
            dut.out_ack.value = 1
            await tick()
        if phase >= 4:
            dut.out_ack.value = 0
            await tick()
        before = monitor.ledger.summary()
        await reset_buffer(dut, monitor.evidence)
        assert monitor.ledger.aborted - before["aborted"] == (1 if phase in (1, 2) else 0), "RESET_ABORT_ACCOUNTING"
        await tick(5)
        assert int(dut.out_req.value) == int(dut.in_ack.value) == 0, "STALE_TOKEN_AFTER_RESET"
        fresh = values(dut)[4]
        drive_payload(dut, fresh)
        await tick()
        dut.in_req.value = 1
        await tick()
        assert int(dut.out_req.value) == 1, "RESET_PREVENTED_PROGRESS"
        assert payload(dut, "out") == expected_payload(fresh), "PAYLOAD_MISMATCH"
        dut.in_req.value = 0
        await tick()
        dut.out_ack.value = 1
        await tick()
        dut.out_ack.value = 0
        await tick()
        monitor.finish()
    monitor.evidence.coverage["reset_phases"] = 5


async def transfer(dut, value):
    drive_payload(dut, value)
    await tick()
    dut.in_req.value = 1
    await wait_value(dut.in_ack, 1)
    await wait_value(dut.out_req, 1)
    await tick()
    assert payload(dut, "out") == expected_payload(value), "PAYLOAD_MISMATCH"
    dut.in_req.value = 0
    await wait_value(dut.in_ack, 0)
    await tick()
    dut.out_ack.value = 1
    await wait_value(dut.out_req, 0)
    await tick()
    dut.out_ack.value = 0
    await tick()


@observed_test()
async def payload_bit_coverage(dut, monitor):
    widths = [len(field) for field in payload_fields(dut, "in")]
    maxima = [(1 << width) - 1 for width in widths]
    count = 0
    for leaf, width in enumerate(widths):
        for bit in range(width):
            for walking_zero in (False, True):
                # Every field varies independently, including signed leaves and
                # each Vec element. Positions above 64 get the same coverage.
                parts = maxima.copy() if walking_zero else [0] * len(widths)
                parts[leaf] ^= 1 << bit
                value = tuple(parts) if IS_PACKET else parts[0]
                await transfer(dut, value)
                monitor.check()
                count += 1
    assert count == monitor.ledger.delivered == 2 * sum(widths)
    monitor.evidence.coverage["payload_bits_each_polarity"] = sum(widths)
    monitor.evidence.coverage["payload_transfers"] = count


@observed_test()
async def reset_full_capacity(dut, monitor):
    for _ in range(monitor.ledger.capacity):
        drive_payload(dut, values(dut)[1])  # identical tokens still count separately
        await tick()
        dut.in_req.value = 1
        await wait_value(dut.in_ack, 1)
        await tick()
        dut.in_req.value = 0
        await wait_value(dut.in_ack, 0)
        await tick()
    drive_payload(dut, values(dut)[3])
    await tick()
    dut.in_req.value = 1
    await tick(5)
    assert int(dut.in_ack.value) == 0, "CAPACITY_EXCEEDED"
    assert monitor.ledger.accepted == monitor.ledger.capacity
    await reset_buffer(dut, monitor.evidence)
    assert monitor.ledger.aborted == monitor.ledger.capacity, "RESET_ABORT_ACCOUNTING"
    assert monitor.ledger.delivered == 0
    await transfer(dut, values(dut)[4])
    assert monitor.ledger.delivered == monitor.ledger.returned == 1
    monitor.evidence.coverage["full_capacity_with_pending_reset"] = 1


async def apply_event(dut, event, tokens):
    action, index = event[0], int(event[1])
    if action == "p":
        drive_payload(dut, tokens[index])
        await tick()  # establish data before request, as required by the contract
        dut.in_req.value = 1
    elif action == "r":
        assert int(dut.in_ack.value) == 1, "EXPECTED_ACCEPTANCE"
        dut.in_req.value = 0
    elif action == "a":
        assert int(dut.out_req.value) == 1, "EXPECTED_OFFER"
        assert payload(dut, "out") == expected_payload(tokens[index]), "PAYLOAD_MISMATCH"
        dut.out_ack.value = 1
    else:
        assert int(dut.out_req.value) == 0, "EXPECTED_OUTPUT_RETURN"
        dut.out_ack.value = 0
    await tick()


@observed_test(single=True)
async def bounded_handshake_schedules(dut, monitor):
    schedules, prefixes = two_token_schedules(), reset_prefixes()
    for same_payload in (False, True):
        tokens = [values(dut)[1], values(dut)[1 if same_payload else 3]]
        for schedule in schedules:
            await reset_buffer(dut, monitor.evidence)
            before = monitor.ledger.delivered
            monitor.evidence.record("schedule", actions=schedule, equal_payloads=same_payload)
            for event in schedule:
                await apply_event(dut, event, tokens)
                monitor.check()
            monitor.finish()
            assert monitor.ledger.delivered - before == 2
    for prefix in prefixes:
        await reset_buffer(dut, monitor.evidence)
        monitor.evidence.record("reset_prefix", actions=prefix)
        for event in prefix:
            await apply_event(dut, event, [values(dut)[1], values(dut)[3]])
            monitor.check()
        # Independent environment accounting: p1 is accepted only once z0 has
        # occurred, whereas offering a request alone does not imply acceptance.
        accepted = int("p0" in prefix) + int("p1" in prefix and "z0" in prefix)
        delivered = int("a0" in prefix) + int("a1" in prefix)
        aborted = monitor.ledger.aborted
        await reset_buffer(dut, monitor.evidence)
        assert monitor.ledger.aborted - aborted == accepted - delivered, "RESET_ABORT_ACCOUNTING"
        await transfer(dut, values(dut)[4])
        monitor.finish()
    # Two independent boundary pairs: source return versus sink acceptance,
    # and a new offer versus prior output return. Exercise both orders and a
    # shared timestamp at the qualified 1 ps precision.
    for boundary in ("source_return", "next_offer"):
        for offset in (-1, 0, 1):
            await reset_buffer(dut, monitor.evidence)
            drive_payload(dut, values(dut)[1])
            await tick()
            dut.in_req.value = 1
            await tick()
            if boundary == "source_return":
                first, second = dut.in_req, dut.out_ack
                first_value, second_value = 0, 1
            else:
                dut.in_req.value = 0
                await tick()
                dut.out_ack.value = 1
                await tick()
                drive_payload(dut, values(dut)[3])
                await tick()
                first, second = dut.in_req, dut.out_ack
                first_value, second_value = 1, 0
            monitor.evidence.record("boundary_pair", boundary=boundary, offset_ps=offset)
            if offset <= 0:
                first.value = first_value
                if offset:
                    await Timer(1, unit="ps")
                second.value = second_value
            else:
                second.value = second_value
                await Timer(1, unit="ps")
                first.value = first_value
            await tick()
            if boundary == "next_offer":
                assert int(dut.in_ack.value) == int(dut.out_req.value) == 1
                dut.in_req.value = 0
                await tick()
                dut.out_ack.value = 1
                await tick()
            dut.out_ack.value = 0
            await tick()
            monitor.finish()
    monitor.evidence.coverage.update(two_token_schedules=len(schedules),
        equal_and_distinct_schedule_runs=2 * len(schedules), reset_prefixes=len(prefixes),
        boundary_pairs=6)


@celement_test
async def celement_exhaustive_boolean_sequences(dut, evidence):
    observed = 0
    # Four possible input pairs over four transitions: 256 sequences from reset.
    for sequence in itertools.product(range(4), repeat=4):
        dut.reset.value = 1
        dut.a.value = dut.b.value = 0
        await tick()
        assert int(dut.q.value) == 0
        dut.reset.value = 0
        await tick()
        expected = 0
        for pair in sequence:
            a, b = pair >> 1, pair & 1
            # Independent characteristic equation, not the production branching structure.
            expected = (a & b) | (expected & (a | b))
            dut.a.value = a
            dut.b.value = b
            await tick()
            evidence.record("boolean_transition", a=a, b=b, expected=expected, q=str(dut.q.value))
            assert int(dut.q.value) == expected, "CELEMENT_STATE_MISMATCH"
            observed += 1
    assert observed == 1024
    evidence.coverage["boolean_transitions"] = observed


@celement_test
async def celement_unknowns_and_reset_dominance(dut, evidence):
    dut.reset.value = 1
    dut.a.value = dut.b.value = 1
    await tick()
    evidence.record("reset_dominance", q=str(dut.q.value))
    assert int(dut.q.value) == 0
    dut.reset.value = 0
    await tick()
    evidence.record("unanimous_release", q=str(dut.q.value))
    assert int(dut.q.value) == 1
    dut.a.value = "X"
    await tick()
    evidence.record("known_resolution", q=str(dut.q.value))
    assert int(dut.q.value) == 1  # b=1; either resolution of a retains/asserts 1.
    dut.b.value = 0
    await tick()
    evidence.record("unknown_resolution", q=str(dut.q.value))
    assert not dut.q.value.is_resolvable
    dut.reset.value = 1
    await tick()
    evidence.record("reset_recovery", q=str(dut.q.value))
    assert int(dut.q.value) == 0
    evidence.coverage["four_state_checks"] = 5
