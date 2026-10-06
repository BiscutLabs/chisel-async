# SPDX-License-Identifier: Apache-2.0
import functools
import json
import os
from pathlib import Path

import cocotb
from cocotb.handle import Immediate
from cocotb.triggers import ReadOnly, Timer
from cocotb.utils import get_sim_time
from observers import Evidence
from timing_reference import CaptureWindow, delay_trace


def now():
    return int(get_sim_time(unit="fs"))


async def tick(fs=1):
    await Timer(fs, unit="fs")


def observed(test):
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
    return cocotb.test()(run)


@observed
async def latch_contract(dut, evidence):
    async def check(expected):
        await tick()
        actual = str(dut.q.value)
        evidence.record("latch_sample", actual=actual, expected=str(expected))
        if expected == "x":
            assert not dut.q.value.is_resolvable, "LATCH_UNCERTAINTY"
        else:
            assert int(dut.q.value) == expected, "LATCH_VALUE"
    dut.reset.value, dut.enable.value, dut.d.value = 1, 0, 0
    await check(0x12)
    dut.reset.value = 0
    await check(0x12)
    for bit in range(9):
        for value in (1 << bit, 0x1ff ^ (1 << bit)):
            dut.enable.value = 1
            dut.d.value = value
            await check(value)
            dut.enable.value = 0
            await check(value)
            dut.d.value = value ^ 0x1ff
            await check(value)
    for enable in (0, 1):
        dut.reset.value, dut.enable.value = 1, enable
        await check(0x12)
        dut.reset.value = 0
        await check(int(dut.d.value) if enable else 0x12)
    dut.enable.value = 0
    await tick()
    held = int(dut.q.value)
    dut.d.value = held
    dut.enable.value = "x"
    await check(held)
    dut.d.value = held ^ 0x1ff
    await check("x")
    dut.reset.value = 1
    await check(0x12)
    dut.reset.value = "x"
    await check("x")
    dut.reset.value = 1
    await check(0x12)
    evidence.coverage["latch_checks"] = 65


@observed
async def delay_contract(dut, evidence):
    dut.reset.value, dut.d.value = 1, 0
    await tick()
    assert int(dut.q.value) == 0, "DELAY_RESET_VALUE"
    base, observed_edges = now(), []

    async def watch():
        while True:
            await dut.q.value_change
            observed_edges.append((now() - base, int(dut.q.value)))
            evidence.record("delay_delivery", relative_fs=now()-base, value=int(dut.q.value))
    task = cocotb.start_soon(watch())
    events = [(100, 0, 0), (20000, 0, 0x101), (25000, 0, 0xaa), (27000, 0, 0x55),
              (50000, 0, 0), (70000, 0, 0x1ff), (79999, 0, 0),
              (100000, 0, 0x1ff), (110000, 0, 0), (130000, 0, 0x1ff), (140001, 0, 0),
              (160000, 0, 0x77), (165000, 1, 0x77), (166000, 1, 0x22), (167000, 0, 0x22),
              (190000, 0, 0x133), (195000, 1, 0x133), (196000, 0, 0x133), (220000, 0, 0),
              (250000, 0, 0x11), (260000, 1, 0x11), (261000, 0, 0x11)]
    try:
        for timestamp, reset, data in events:
            await tick(base + timestamp - now())
            # Apply the input vector at the start of this time step, before NBA
            # deliveries. Cocotb's cached writes otherwise arrive in ReadWrite,
            # after an already-due delivery, which is a different experiment.
            dut.reset.value, dut.d.value = Immediate(reset), Immediate(data)
            evidence.record("delay_input", relative_fs=timestamp, reset=reset, value=data)
        await tick(20000)
        expected = delay_trace(events, 10000, os.environ["FIXTURE"])
        evidence.record("expected_deliveries", edges=expected)
        assert observed_edges == expected, "DELAY_TRACE_MISMATCH"
        evidence.coverage.update(input_events=len(events), deliveries=len(expected), pulse_boundaries=3,
                                 reset_pending=3, reset_at_delivery=1, release_unchanged_data=2)
    finally:
        task.cancel()


class TimingMonitor:
    def __init__(self, dut, evidence):
        contract = json.loads(Path(os.environ["CONTRACT"]).read_text())["manifest"]["design"]
        refs = {e["id"]: e for e in contract["endpoints"]}
        paths = json.loads(Path(os.environ["CONTRACT"]).with_name("resolved.json").read_text())["probe_paths"]
        timing = contract["timing"][0]
        def resolve(ref):
            handle = dut
            for name in paths[refs[ref]["probe"]].split(".")[1:]:
                handle = handle[name]  # Compiler references may start with '_'.
            return handle
        self.signals = {key: resolve(timing[key]) for key in
                        ("launch", "transaction", "data_valid", "capture", "captured")}
        self.contract = CaptureWindow(int(timing["setup_fs"]), int(timing["hold_fs"]), 8)
        self.dut, self.evidence, self.failure, self.tasks = dut, evidence, None, []

    def guard(self, action):
        if self.failure is None:
            try:
                action()
            except AssertionError as error:
                self.failure = str(error)
                self.evidence.record("timing_violation", diagnostic=self.failure)

    async def watch(self, key):
        signal = self.signals[key]
        while True:
            await signal.value_change
            timestamp, word = now(), int(signal.value)
            self.evidence.record(key, value=word)
            if int(self.dut.reset.value):
                continue
            if key == "launch" and word:
                # The environment establishes ID and payload before launch.
                self.guard(lambda: self.contract.launch(timestamp, int(self.signals["transaction"].value),
                                                        int(self.dut.bits.value) ^ 0x55))
            elif key == "data_valid":
                self.guard(lambda: self.contract.data(timestamp, word))
            elif key == "capture" and word:
                # Capture time is the observed edge, never postponed to make setup pass.
                # Only the functional value is read after NBA settling.
                await ReadOnly()
                captured = int(self.signals["captured"].value)
                self.evidence.record("capture_sample", edge_time_fs=timestamp, value=captured)
                self.guard(lambda: self.contract.capture(timestamp, captured))

    async def reset(self):
        while True:
            await self.dut.reset.value_change
            if int(self.dut.reset.value):
                self.contract.reset()
                self.evidence.record("reset_epoch")

    def start(self):
        self.tasks = [cocotb.start_soon(self.watch(key)) for key in ("launch", "data_valid", "capture")]
        self.tasks.append(cocotb.start_soon(self.reset()))

    def check(self):
        assert self.failure is None, self.failure

    def stop(self):
        for task in self.tasks:
            task.cancel()


@observed
async def timing_contract(dut, evidence):
    dut.reset.value, dut.bits.value, dut.transaction.value, dut.launch.value = 1, 0, 0, 0
    await tick(100)
    dut.reset.value = 0
    await tick(20000)
    monitor = TimingMonitor(dut, evidence)
    monitor.start()
    await tick()
    capture_delay = int(os.environ["CAPTURE_FS"])
    hold_offset = os.environ.get("HOLD_OFFSET")
    try:
        if hold_offset:
            dut.bits.value, dut.transaction.value = 0x33, 1
            await tick(1)
            dut.launch.value = 1
            # Changing the identity with equal payload must still invalidate hold.
            await tick(capture_delay + int(hold_offset) - 8000)
            dut.transaction.value = 2
            await tick(20000)
            monitor.check()
            monitor.contract.finish()
            evidence.coverage.update(hold_boundary=1, equal_payload_new_identity=1,
                                     captures=monitor.contract.captures)
        else:
            # ID/payload and launch are one settled input vector. Both independent delay
            # paths start at this timestamp, so setup equality is exactly 8 ps + 2 ps.
            identities = [1 << bit for bit in range(32)] + [0xffffffff ^ (1 << bit) for bit in range(32)]
            values = [0x33, 0x33] + [1 << b for b in range(8)] + [0xff ^ (1 << b) for b in range(8)] + [0x33] * 46
            for identity, value in zip(identities, values, strict=True):
                dut.bits.value, dut.transaction.value, dut.launch.value = value, identity, 1
                launch_at = now()
                await tick(capture_delay + 3000)
                monitor.check()
                monitor.contract.finish()
                assert monitor.contract.captured_at == launch_at + capture_delay, "CAPTURE_TIME_MISMATCH"
                dut.launch.value = 0
                await tick(capture_delay + 1000)
            # Reset cancels a pending launch, then a fresh identity completes after restart.
            dut.bits.value, dut.transaction.value, dut.launch.value = 0xaa, 19, 1
            await tick(4000)
            dut.reset.value = 1
            await tick(1)
            dut.bits.value, dut.transaction.value, dut.launch.value = 0, 0, 0
            await tick(20000)
            dut.reset.value = 0
            await tick(20000)
            dut.bits.value, dut.transaction.value, dut.launch.value = 0x33, 1, 1
            await tick(capture_delay + 3000)
            monitor.check()
            monitor.contract.finish()
            evidence.coverage.update(captures=monitor.contract.captures, launches=monitor.contract.launches,
                                     aborted=monitor.contract.aborted, equal_payload_new_identity=1,
                                     payload_bits=8, identity_bits=32)
        monitor.check()
    finally:
        monitor.stop()
