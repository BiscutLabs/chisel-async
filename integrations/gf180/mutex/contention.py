# SPDX-License-Identifier: Apache-2.0
"""Contention checks that permit indefinite zero-grant stuttering, not bad levels."""


def check_contention(rows, voltage):
    low, high = .3 * voltage, .7 * voltage
    errors = []
    settled = [row for row in rows if row[0] >= 30e-9]
    if len(settled) < 2 or any(row[1] < high or row[2] < high or row[3] > low for row in settled):
        errors.append("MUTEX_CONTENTION_STIMULUS_MISSING")
    active = [row for row in rows if row[0] >= 18e-9]
    for bit in range(2):
        if any(row[bit + 4] > low for row in active) and not any(row[bit + 4] >= high for row in active):
            errors.append(f"MUTEX_GRANT{bit}_PARTIAL_HIGH")
    return errors
