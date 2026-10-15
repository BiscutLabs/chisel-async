# SPDX-License-Identifier: Apache-2.0
"""Mandatory sampled-waveform checks shared by the campaign and replay audit."""
import math

TRANSIENT_COLUMNS = ["time", "v(r0)", "v(r1)", "v(reset)", "v(g0)", "v(g1)",
                     "v(xd.n0)", "v(xd.n1)", "v(xd.f0)", "v(xd.f1)"]
FILTER_COLUMNS = ["vdd", "v(n0)", "v(n1)", "v(f0)", "v(f1)", "v(g0)", "v(g1)"]


def data(path):
    lines = path.read_text().splitlines()
    if len(lines) < 2:
        raise ValueError("MUTEX_SPICE_EMPTY_WAVEFORM")
    names = lines[0].split()
    rows = [[float(x) for x in line.split()] for line in lines[1:] if line.strip()]
    if not rows or any(len(row) != len(names) or not all(math.isfinite(v) for v in row) for row in rows):
        raise ValueError("MUTEX_SPICE_BAD_WAVEFORM")
    if names[0] == "time" and any(b[0] <= a[0] for a, b in zip(rows, rows[1:])):
        raise ValueError("MUTEX_WAVE_TIME_ORDER")
    return names, rows


def validate_transient(names, rows, finish_ns, maximum_step_ns, columns=TRANSIENT_COLUMNS):
    if names != columns:
        raise ValueError("MUTEX_WAVE_COLUMNS")
    if len(rows) < 2 or abs(rows[0][0]) > 1e-18 or abs(rows[-1][0] - finish_ns * 1e-9) > 1e-15:
        raise ValueError("MUTEX_WAVE_TRUNCATED")
    if any(b[0] <= a[0] for a, b in zip(rows, rows[1:])):
        raise ValueError("MUTEX_WAVE_TIME_ORDER")
    # Permit the final decimal-printing rounding, not a missing waveform region.
    if any(b[0] - a[0] > maximum_step_ns * 1e-9 * 1.001 + 1e-15 for a, b in zip(rows, rows[1:])):
        raise ValueError("MUTEX_WAVE_SAMPLE_GAP")


def check_held(rows, voltage):
    errors = []
    low, high = .3 * voltage, .7 * voltage
    for bit in range(2):
        valid_high = False
        excursion = False
        low_seen = True
        for row in rows:
            request, reset, grant = row[bit + 1], row[3], row[bit + 4]
            if reset > low:
                valid_high = False
                excursion = False
                low_seen = grant <= low
                continue
            if request < high:
                # Existing high grant may return after finite propagation. Only
                # a NEW rise after observed low is forbidden without a request.
                valid_high = False
                excursion = False
            if grant > low and low_seen and request <= low:
                errors.append(f"MUTEX_GRANT{bit}_WITHOUT_REQUEST")
                break
            if request >= high:
                if valid_high and grant < high:
                    errors.append(f"MUTEX_GRANT{bit}_LOST_VALID_HIGH")
                    break
                if excursion and grant <= low:
                    errors.append(f"MUTEX_GRANT{bit}_RUNT_OR_REVOKED")
                    break
                if grant >= high:
                    valid_high = True
                if grant > low:
                    excursion = True
            low_seen = grant <= low
    return errors
