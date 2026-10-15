# SPDX-License-Identifier: Apache-2.0
import unittest
from contention import check_contention
from characterize import analyze_transient


class ContentionChecks(unittest.TestCase):
    def test_documented_main_campaign_requires_contention_helper(self):
        partial = [[t*1e-9, 3.3, 3.3, 0, 1.65, 0] for t in range(61)]
        missing = [[t*1e-9, 0, 0, 0, 0, 0] for t in range(61)]
        self.assertIn("MUTEX_GRANT0_PARTIAL_HIGH", analyze_transient(partial, 3.3, "contention")["errors"])
        self.assertIn("MUTEX_CONTENTION_STIMULUS_MISSING", analyze_transient(missing, 3.3, "contention")["errors"])

    def test_unresolved_with_persistent_requests_remains_legal(self):
        self.assertEqual(check_contention([[t*1e-9, 3.3, 3.3, 0, 0, 0] for t in range(61)], 3.3), [])

    def test_partial_high_is_not_unresolved_zero(self):
        rows = [[t*1e-9, 3.3, 3.3, 0, 1.65, 0] for t in range(61)]
        self.assertEqual(check_contention(rows, 3.3), ["MUTEX_GRANT0_PARTIAL_HIGH"])

    def test_missing_contenders_cannot_pass_empty_activity(self):
        rows = [[t*1e-9, 0, 0, 0, 0, 0] for t in range(61)]
        self.assertEqual(check_contention(rows, 3.3), ["MUTEX_CONTENTION_STIMULUS_MISSING"])

    def test_held_reset_cannot_count_as_unresolved_arbitration(self):
        rows = [[t*1e-9, 3.3, 3.3, 3.3, 0, 0] for t in range(61)]
        self.assertEqual(check_contention(rows, 3.3), ["MUTEX_CONTENTION_STIMULUS_MISSING"])


if __name__ == "__main__":
    unittest.main()
