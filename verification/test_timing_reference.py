# SPDX-License-Identifier: Apache-2.0
import pytest
from timing_reference import CaptureWindow, MAX_TIME, deadline, delay_trace, model_time


@pytest.mark.parametrize("bad", [-1, MAX_TIME + 1, 1.0, True, "1000"])
def test_invalid_time(bad):
    with pytest.raises(ValueError, match="^INVALID_MODEL_TIME$"):
        model_time(bad)


def test_exact_precision_and_overflow():
    assert model_time(MAX_TIME) == MAX_TIME
    assert model_time(1000, 1000) == 1000
    with pytest.raises(ValueError, match="INEXACT_MODEL_TIME"):
        model_time(1001, 1000)
    with pytest.raises(ValueError, match="INVALID_MODEL_TIME"):
        deadline(MAX_TIME, 1)


@pytest.mark.parametrize("width,expected", [(9, []), (10, [(30, 1), (40, 0)]), (11, [(30, 1), (41, 0)])])
def test_inertial_boundary(width, expected):
    assert delay_trace([(1, 0, 0), (20, 0, 1), (20 + width, 0, 0)], 10, "inertial") == expected


def test_transport_keeps_captured_values_and_reset_cancels_due_event():
    assert delay_trace([(1, 0, 0), (20, 0, 1), (21, 0, 2), (22, 0, 3)], 10, "transport") == [(30, 1), (31, 2), (32, 3)]
    assert delay_trace([(1, 0, 0), (20, 0, 1), (30, 1, 1), (31, 0, 1)], 10, "transport") == [(41, 1)]


@pytest.mark.parametrize("capture,diagnostic", [(9, "TIMING_SETUP"), (10, None), (11, None)])
def test_setup_inequality(capture, diagnostic):
    model = CaptureWindow(2, 2, 8)
    model.launch(0, 1, 0x33)
    model.data(8, 0x133)
    if diagnostic:
        with pytest.raises(AssertionError, match=diagnostic):
            model.capture(capture, 0x133)
    else:
        model.capture(capture, 0x133)
        model.finish()


@pytest.mark.parametrize("change,diagnostic", [(11, "TIMING_HOLD"), (12, None), (13, None)])
def test_hold_includes_new_identity_with_equal_payload(change, diagnostic):
    model = CaptureWindow(2, 2, 8)
    model.launch(0, 1, 0x33)
    model.data(8, 0x133)
    model.capture(10, 0x133)
    if diagnostic:
        with pytest.raises(AssertionError, match=diagnostic):
            model.data(change, 0x233)
    else:
        model.data(change, 0x233)


def test_equal_payload_cannot_reuse_old_validity_and_reset_aborts():
    model = CaptureWindow(2, 2, 8)
    model.launch(0, 1, 0x33)
    model.data(8, 0x133)
    model.capture(10, 0x133)
    model.launch(20, 2, 0x33)
    with pytest.raises(AssertionError, match="TIMING_DATA_NOT_VALID"):
        model.capture(30, 0x133)
    model.reset()
    assert (model.launches, model.captures, model.aborted) == (2, 1, 1)
    model.finish()


def test_fresh_identity_may_be_valid_before_launch():
    model = CaptureWindow(2, 2, 8)
    model.data(0, 0x133)
    model.launch(4, 1, 0x33)
    model.capture(5, 0x133)
    model.finish()
