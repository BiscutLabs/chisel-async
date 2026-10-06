# SPDX-License-Identifier: Apache-2.0
"""Protocol properties and transaction accounting, independent of the SV controller.

No production state names, transition functions, or simulator helpers are imported.
The schedule generator enumerates linear extensions of a two-token environment
contract. It is a bounded experiment, not a proof over arbitrary circuits.
"""
from collections import deque


class FourPhaseContract:
    ORDER = (("req", 1), ("ack", 1), ("req", 0), ("ack", 0))

    def __init__(self):
        self.phase = 0
        self.counts = {"req+": 0, "ack+": 0, "req-": 0, "ack-": 0}

    def edge(self, signal, value):
        if (signal, value) == ("req", 0) and self.phase == 1:
            raise AssertionError("REQUEST_WITHDRAWN")
        if (signal, value) == ("ack", 0) and self.phase == 2:
            raise AssertionError("ACK_EARLY_RELEASE")
        assert (signal, value) == self.ORDER[self.phase], "PROTOCOL_ORDER"
        self.counts[signal + ("+" if value else "-")] += 1
        self.phase = (self.phase + 1) % 4

    def reset(self):
        self.phase = 0


class TwoPhaseContract:
    """Contract only: each acknowledgement transition completes one token."""

    def __init__(self):
        self.req = self.ack = self.delivered = 0

    def edge(self, signal, value):
        expected = "req" if self.req == self.ack else "ack"
        assert signal == expected and value == 1 - getattr(self, expected), "TWO_PHASE_ORDER"
        setattr(self, signal, value)
        if signal == "ack":
            self.delivered += 1

    def reset(self):
        self.req = self.ack = 0


class TokenLedger:
    def __init__(self, capacity):
        self.capacity = capacity
        self.tokens = deque()
        self.accepted = self.delivered = self.returned = self.aborted = 0
        self.reserved = self.peak_reserved = self.epoch = 0

    def accept(self, payload):
        assert self.reserved < self.capacity, "CAPACITY_EXCEEDED"
        self.tokens.append(payload)
        self.accepted += 1
        self.reserved += 1
        self.peak_reserved = max(self.peak_reserved, self.reserved)
        self.check()

    def offer(self, payload):
        assert self.tokens, "UNEXPECTED_TOKEN"
        assert self.tokens[0] == payload, "PAYLOAD_MISMATCH"

    def deliver(self, payload):
        self.offer(payload)
        self.tokens.popleft()
        self.delivered += 1
        self.check()

    def return_idle(self):
        assert self.reserved > 0, "UNEXPECTED_COMPLETION"
        self.reserved -= 1
        self.returned += 1
        self.check()

    def reset(self):
        # Receiver acknowledgement is the delivery point. Already delivered
        # tokens are not retrospectively counted as aborted by a reset.
        self.aborted += len(self.tokens)
        self.tokens.clear()
        self.reserved = 0
        self.epoch += 1
        self.check()

    def check(self):
        assert self.accepted == self.delivered + self.aborted + len(self.tokens), "TOKEN_CONSERVATION"
        assert 0 <= len(self.tokens) <= self.reserved <= self.capacity, "CAPACITY_EXCEEDED"

    def summary(self):
        self.check()
        return {key: getattr(self, key) for key in
                ("capacity", "accepted", "delivered", "returned", "aborted",
                 "reserved", "peak_reserved", "epoch")} | {"outstanding": len(self.tokens)}


def two_token_schedules():
    # p: offer input, r: return input request, a: acknowledge output,
    # z: return output acknowledgement. A pending p1 may precede z0,
    # but r1 must await acceptance after the first output frees storage.
    dependencies = {"p0": (), "r0": ("p0",), "a0": ("p0",), "z0": ("a0",),
                    "p1": ("r0",), "r1": ("p1", "z0"),
                    "a1": ("p1", "z0"), "z1": ("a1",)}

    def extend(prefix):
        if len(prefix) == len(dependencies):
            yield prefix
        else:
            for event, parents in dependencies.items():
                if event not in prefix and all(parent in prefix for parent in parents):
                    yield from extend(prefix + (event,))
    return tuple(extend(()))


def reset_prefixes():
    return tuple(sorted({schedule[:length] for schedule in two_token_schedules()
                         for length in range(9)}, key=lambda prefix: (len(prefix), prefix)))
