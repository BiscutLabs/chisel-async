# SPDX-License-Identifier: Apache-2.0
import pytest

from trace_contract import validate_events


def event(index=1, time=1001):
    return {"index": index, "time_fs": time, "time_ps": time // 1000, "kind": "edge"}


def test_same_timestamp_and_subpicosecond_forward_order():
    validate_events([event(), event(2), event(3, 1002)])


def test_subpicosecond_backwards_time_is_rejected():
    with pytest.raises(RuntimeError, match="OBSERVATION_TIME_ORDER"):
        validate_events([event(1, 1002), event(2, 1001)])


@pytest.mark.parametrize("field,value", [("index", True), ("index", 2),
    ("time_fs", None), ("time_fs", 1.5), ("time_fs", -1), ("time_fs", 2**63),
    ("time_ps", 1001), ("time_ps", True), ("kind", ""), ("kind", " "), ("kind", 3)])
def test_malformed_envelope_is_rejected(field, value):
    with pytest.raises(RuntimeError, match="INVALID_OBSERVATION_ENVELOPE"):
        validate_events([event() | {field: value}])


def test_empty_trace_is_rejected():
    with pytest.raises(RuntimeError, match="EMPTY_OBSERVATION_TRACE"):
        validate_events([])
