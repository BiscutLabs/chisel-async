# SPDX-License-Identifier: Apache-2.0
"""Passive event observation; no monitor drives a DUT signal or delays a driver."""
import json
import os
from pathlib import Path

import cocotb
from cocotb.triggers import ReadOnly
from cocotb.utils import get_sim_time

from reference import FourPhaseContract, TokenLedger


class Evidence:
    def __init__(self, case):
        self.case = case
        self.directory = Path(os.environ["EVIDENCE_DIR"])
        self.trace = self.directory / f"{case}.trace.jsonl"
        self.stream = self.trace.open("w", encoding="utf-8")
        self.observations = 0
        self.coverage = {}

    def record(self, kind, **details):
        self.observations += 1
        self.stream.write(json.dumps({"index": self.observations,
            "time_ps": int(get_sim_time(unit="ps")), "time_fs": int(get_sim_time(unit="fs")),
            "kind": kind, **details}) + "\n")
        self.stream.flush()

    def save(self, status, error=None, **details):
        self.stream.close()
        result = {"schema": 1, "case": self.case, "status": status, "error": error,
                  "observations": self.observations, "coverage": self.coverage,
                  "trace": self.trace.name, **details}
        (self.directory / f"{self.case}.evidence.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8")


class BufferMonitor:
    def __init__(self, dut, read_payload, fields, evidence, capacity, transform=lambda value: value):
        self.dut, self.read_payload, self.fields, self.evidence = dut, read_payload, fields, evidence
        self.channels = {name: FourPhaseContract() for name in ("in", "out")}
        self.ledger = TokenLedger(capacity)
        self.held = {"in": None, "out": None}
        self.launched = {"in": None, "out": None}
        self.tasks = []
        self.failure = None
        self.transform = transform

    def start(self):
        self.ledger.reset()
        self.evidence.record("initialized", epoch=self.ledger.epoch)
        self.tasks.append(cocotb.start_soon(self.watch_reset()))
        for port in self.channels:
            for signal in ("req", "ack"):
                self.tasks.append(cocotb.start_soon(self.watch_control(port, signal)))
            for field in self.fields(port):
                self.tasks.append(cocotb.start_soon(self.watch_data(port, field)))

    def guard(self, action):
        if self.failure is None:
            try:
                action()
            except (AssertionError, ValueError) as error:
                self.failure = str(error).splitlines()[0]
                self.evidence.record("violation", diagnostic=self.failure, detail=str(error), epoch=self.ledger.epoch)

    async def watch_reset(self):
        while True:
            await self.dut.reset.value_change
            asserted = int(self.dut.reset.value)
            self.evidence.record("reset", value=asserted, epoch=self.ledger.epoch)
            if asserted:
                self.ledger.reset()
                for port, channel in self.channels.items():
                    channel.reset()
                    self.held[port] = self.launched[port] = None

    async def watch_control(self, port, signal):
        handle = getattr(self.dut, f"{port}_{signal}")
        while True:
            await handle.value_change
            self.evidence.record("edge", port=port, signal=signal, value=str(handle.value),
                                 epoch=self.ledger.epoch, reset=str(self.dut.reset.value))
            if int(self.dut.reset.value):
                continue
            self.guard(lambda: self.control(port, signal, int(handle.value)))

    def control(self, port, signal, value):
        channel = self.channels[port]
        channel.edge(signal, value)
        if (signal, value) == ("req", 1):
            self.launched[port] = int(get_sim_time(unit="ps"))
            # The functional view publishes request/data atomically. Sample
            # payload after settling; keep edge listeners armed throughout.
            self.tasks.append(cocotb.start_soon(self.capture(port, self.ledger.epoch)))
        elif (signal, value) == ("ack", 1):
            value = self.read_payload(self.dut, port)
            if port == "in":
                self.ledger.accept(self.transform(value))
            else:
                self.ledger.deliver(value)
            self.evidence.record("accepted" if port == "in" else "delivered",
                                 payload=value, epoch=self.ledger.epoch)
        elif (signal, value) == ("ack", 0):
            self.held[port] = None
            if port == "out":
                self.ledger.return_idle()

    async def capture(self, port, epoch):
        await ReadOnly()
        if int(self.dut.reset.value) or epoch != self.ledger.epoch:
            return

        def sample():
            value = self.read_payload(self.dut, port)
            self.held[port] = value
            self.evidence.record("offer", port=port, payload=value, epoch=epoch)
            if port == "out":
                self.ledger.offer(value)
        self.guard(sample)

    async def watch_data(self, port, handle):
        while True:
            await handle.value_change
            self.evidence.record("data", port=port, field=handle._name, value=str(handle.value),
                                 epoch=self.ledger.epoch)
            if int(self.dut.reset.value):
                continue

            def stable():
                # Ignore only initial same-timestamp settling, not a later
                # excursion which happens to recover before the driver's check.
                if (self.channels[port].phase and self.held[port] is not None
                        and int(get_sim_time(unit="ps")) != self.launched[port]):
                    assert self.read_payload(self.dut, port) == self.held[port], "DATA_CHANGED_DURING_HANDSHAKE"
            self.guard(stable)

    def check(self):
        assert self.failure is None, self.failure
        self.ledger.check()

    def finish(self):
        self.check()
        assert all(channel.phase == 0 for channel in self.channels.values()), "INCOMPLETE_HANDSHAKE"
        assert not self.ledger.tokens and self.ledger.reserved == 0, "OUTSTANDING_TOKENS"

    def stop(self):
        for task in self.tasks:
            task.cancel()

    def summary(self):
        return {"tokens": self.ledger.summary(),
                "edges": {port: channel.counts for port, channel in self.channels.items()}}
