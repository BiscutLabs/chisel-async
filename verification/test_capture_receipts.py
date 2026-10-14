# SPDX-License-Identifier: Apache-2.0
"""Independent receiver trace oracle: empty, changed, duplicated and lost data fail."""
import pytest
from run_capture_receipts import audit, fixtures


def transcript(click, width=8):
    mask = (1 << width) - 1
    values = [mask, 0, 0, mask]
    for bit in range(width):
        values += [1 << bit, mask ^ (1 << bit)]
    values += [1] * (1 if click else 2)
    if click:
        values += [mask, mask, 0]
    values += [0, mask]
    lines = [f"CAPTURE D {value:x}" for value in values]
    lines += [f"CAPTURE_PASS delivered={2*width+6+2*click} accepted={len(values)} resets={7 if click else 6} stopped={2*width+5+2*click}"]
    return "\n".join(lines)


@pytest.mark.parametrize("click", (0, 1))
def test_exact_trace_inventory(click):
    result = audit(transcript(click), dict(click=click, width=8))
    assert result["delivered"] == (24 if click else 22) and result["accepted"] == (26 if click else 24)


@pytest.mark.parametrize("fault", ("empty", "data", "missing", "duplicate", "activity", "failure"))
def test_oracle_rejects_faults(fault):
    text = transcript(1)
    text = {"empty": "", "data": text.replace("CAPTURE D ff", "CAPTURE D fe", 1),
            "missing": text.replace("CAPTURE D 0\n", "", 1),
            "duplicate": "CAPTURE D ff\n" + text,
            "activity": text.replace("stopped=23", "stopped=0"),
            "failure": text + "\nFATAL: unrelated"}[fault]
    with pytest.raises(ValueError, match="^CAPTURE_TRACE_"):
        audit(text, dict(click=1, width=8))


def test_fixture_inventory_is_closed():
    cases = list(fixtures())
    assert len(cases) == len({case["id"] for case in cases}) == 24
    assert {(case["click"], case["stages"], case["settling"], case["mask"]) for case in cases} == {
        (click, stages, settling, mask) for click in (0, 1) for stages in (2, 3)
        for settling in (0, 1, 3) for mask in (0, 1)}
