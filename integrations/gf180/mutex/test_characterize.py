# SPDX-License-Identifier: Apache-2.0
"""Checker controls; these tests do not substitute for analog device runs."""
import tempfile
import unittest
import importlib.util
from pathlib import Path

from characterize import analyze_transient, data, edge
from check_samples import check_held
from waveform import validate_transient


class CheckerTests(unittest.TestCase):
    def test_generic_preparer_does_not_silently_enable_experimental_mutex(self):
        path = Path(__file__).resolve().parents[1] / "prepare.py"
        spec = importlib.util.spec_from_file_location("gf180_prepare_for_mutex_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for policy in range(4):
            required = {"cell": {"model": "ChiselAsyncMutex_v1", "parameters":
                {"RESOLVE_FS": 100, "RESOLVE_MAX_FS": 200, "POLICY": policy, "SEED": 19}},
                "ports": [{"direction": "input", "width": 1, "name": "reset"},
                          {"direction": "input", "width": 2, "name": "request"},
                          {"direction": "output", "width": 2, "name": "grant"}],
                "instances": ["owner.choice"]}
            candidate, reason = module.adapter(required, "TrialMutex", None)
            self.assertIsNone(candidate)
            self.assertIn("reviewed technology implementation", reason)

    def test_missing_activity_cannot_pass_sequence(self):
        rows = [[t * 1e-9, 0, 0, 0, 0, 0] for t in range(231)]
        result = analyze_transient(rows, 3.3, "sequence")
        self.assertIn("MUTEX_MISSING_TIMING_ACTIVITY", result["errors"])
        self.assertIn("MUTEX_SEQUENCE_35NS", result["errors"])

    def test_analog_overlap_below_digital_high_is_rejected(self):
        result = analyze_transient([[20e-9, 3.3, 3.3, 0, 1.2, 1.2]], 3.3, "contention")
        self.assertIn("MUTEX_ANALOG_GRANT_OVERLAP", result["errors"])

    def test_unresolved_is_permitted_without_inventing_resolution_bound(self):
        result = analyze_transient([[t * 1e-9, 3.3, 3.3, 0, 0, 0] for t in range(60)], 3.3, "contention")
        self.assertEqual(result["errors"], [])
        self.assertTrue(result["unresolved_at_end"])
        self.assertIsNone(result["maximum_resolution_bound_ns"])

    def test_runt_grant_during_persistent_request_is_rejected(self):
        rows = [[0, 3.3, 0, 0, 0, 0], [1, 3.3, 0, 0, 1.2, 0], [2, 3.3, 0, 0, 0, 0]]
        self.assertEqual(check_held(rows, 3.3), ["MUTEX_GRANT0_RUNT_OR_REVOKED"])

    def test_request_release_allows_grant_return(self):
        rows = [[0, 3.3, 0, 0, 3.3, 0], [1, 0, 0, 0, 1.2, 0], [2, 0, 0, 0, 0, 0]]
        self.assertEqual(check_held(rows, 3.3), [])

    def test_valid_high_cannot_decay_into_receiver_undefined_range(self):
        rows = [[0, 3.3, 0, 0, 3.3, 0], [1, 3.3, 0, 0, 1.65, 0]]
        self.assertEqual(check_held(rows, 3.3), ["MUTEX_GRANT0_LOST_VALID_HIGH"])

    def test_idle_spurious_grant_is_rejected_after_observed_low(self):
        rows = [[0, 0, 0, 0, 0, 0], [1, 0, 0, 0, 3.3, 0]]
        self.assertEqual(check_held(rows, 3.3), ["MUTEX_GRANT0_WITHOUT_REQUEST"])

    def test_main_campaign_includes_hold_and_ownership_checks(self):
        rows = [[20e-9, 3.3, 0, 0, 3.3, 0], [21e-9, 3.3, 0, 0, 1.65, 0]]
        self.assertIn("MUTEX_GRANT0_LOST_VALID_HIGH", analyze_transient(rows, 3.3, "contention")["errors"])

    def test_waveform_identity_order_coverage_and_spacing(self):
        columns = ["time", "v(g0)"]
        valid = [[0, 0], [1e-9, 0], [2e-9, 0]]
        validate_transient(columns, valid, 2, 1, columns)
        for names, rows, diagnostic in ((["time", "v(g1)"], valid, "COLUMNS"),
            (columns, valid[:-1], "TRUNCATED"), (columns, [valid[0], valid[2], valid[1], valid[2]], "TIME_ORDER"),
            (columns, [valid[0], valid[2]], "SAMPLE_GAP")):
            with self.assertRaisesRegex(ValueError, diagnostic):
                validate_transient(names, rows, 2, 1, columns)

    def test_crossing_interpolates_both_directions(self):
        rows = [[0, 0], [1e-9, 2], [2e-9, 0]]
        self.assertAlmostEqual(edge(rows, 1, 1, 0, True), .5)
        self.assertAlmostEqual(edge(rows, 1, 1, 1, False), 1.5)

    def test_nonfinite_and_wrong_width_waveforms_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "wave.tsv"
            for text in ("time v(g0)\n0 nan\n", "time v(g0)\n0 1 2\n", "time v(g0)\n"):
                path.write_text(text)
                with self.assertRaises(ValueError):
                    data(path)
            path.write_text("time v(g0)\n0 0\n2 0\n1 0\n")
            with self.assertRaisesRegex(ValueError, "TIME_ORDER"):
                data(path)


if __name__ == "__main__":
    unittest.main()
