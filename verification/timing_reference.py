# SPDX-License-Identifier: Apache-2.0
"""Independent, integer-time reference contracts; no RTL scheduler or signal driving."""
import heapq

MAX_TIME = 2**63 - 1


def model_time(value, precision=1):
    if type(value) is not int or not 0 <= value <= MAX_TIME:
        raise ValueError("INVALID_MODEL_TIME")
    if type(precision) is not int or precision <= 0 or value % precision:
        raise ValueError("INEXACT_MODEL_TIME")
    return value


def deadline(now, interval):
    return model_time(model_time(now) + model_time(interval))


def delay_trace(events, delay, policy):
    """Initially reset=1, data=0, q=0. Reset dominates; otherwise due events precede input.

    Input events are (time_fs, reset, data), at most one settled input vector per timestamp.
    The queue is a reference specification, independent of the SV packet-NBA implementation.
    """
    model_time(delay)
    assert delay > 0 and policy in ("transport", "inertial")
    queue, result = [], []
    reset, data, output, epoch, serial, previous = 1, 0, 0, 0, 0, -1

    def deliver(until, inclusive):
        nonlocal output
        while queue and (queue[0][0] < until or inclusive and queue[0][0] == until):
            due, generation, candidate, value = heapq.heappop(queue)
            if not reset and generation == epoch and (policy == "transport" or candidate == serial):
                if value != output:
                    result.append((due, value))
                    output = value

    for now, new_reset, new_data in events:
        model_time(now)
        assert now > previous, "MULTIPLE_INPUT_VECTORS_AT_ONE_TIMESTAMP"
        previous = now
        deliver(now, not new_reset)
        if (new_reset, new_data) == (reset, data):
            continue
        reset, data = new_reset, new_data
        if reset:
            epoch += 1
            if output != 0:
                result.append((now, 0))
                output = 0
        else:
            serial += 1
            heapq.heappush(queue, (deadline(now, delay), epoch, serial, data))
    deliver(MAX_TIME, True)
    return result


class CaptureWindow:
    def __init__(self, setup, hold, payload_width):
        self.setup, self.hold = model_time(setup), model_time(hold)
        self.width = payload_width
        self.captures = self.launches = self.aborted = 0
        self.reset()

    def reset(self):
        if getattr(self, "pending", None) is not None:
            self.aborted += 1
        self.pending = self.valid = self.captured_at = None
        self.used = set()

    def launch(self, now, identity, expected_payload):
        model_time(now)
        assert identity > 0 and identity not in self.used, "TIMING_TRANSACTION_ID"
        assert self.pending is None, "TIMING_OVERLAPPING_LAUNCH"
        self.used.add(identity)
        self.pending = (identity, expected_payload, now)
        self.launches += 1

    def data(self, now, word):
        model_time(now)
        if self.captured_at is not None:
            assert now >= deadline(self.captured_at, self.hold), "TIMING_HOLD"
        self.valid = (word >> self.width, word & ((1 << self.width) - 1), now)

    def capture(self, now, word):
        model_time(now)
        assert self.pending is not None, "TIMING_CAPTURE_WITHOUT_LAUNCH"
        identity, expected_payload, _ = self.pending
        assert self.valid is not None and self.valid[0] == identity, "TIMING_DATA_NOT_VALID"
        assert now >= deadline(self.valid[2], self.setup), "TIMING_SETUP"
        assert word == (identity << self.width) | expected_payload, "TIMING_CAPTURED_VALUE"
        self.pending = None
        self.captured_at = now
        self.captures += 1

    def finish(self):
        assert self.pending is None, "TIMING_MISSING_CAPTURE"
        assert self.launches == self.captures + self.aborted, "TIMING_TOKEN_ACCOUNTING"
