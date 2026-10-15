# SPDX-License-Identifier: Apache-2.0
import unittest
from pathlib import Path
from run_mutex_contract import DIAGNOSTICS, accepts_log, fault_kind


class MutexControlInventory(unittest.TestCase):
    def test_every_contract_diagnostic_has_one_exact_control(self):
        expected = {
            1: "MUTEX_REQUEST_WITHDRAWN_BEFORE_SERVICE",
            2: "MUTEX_GRANT_NOT_RELEASED_BEFORE_REUSE",
            3: "MUTEX_STALE_REQUEST_AT_REARM",
            4: "MUTEX_RESET_WITHOUT_QUIESCENCE",
            5: "MUTEX_GRANT_EXCLUSION",
            6: "MUTEX_HELD_GRANT_REVOKED",
            7: "MUTEX_MISSING_ZERO_HANDOVER",
            8: "MUTEX_GRANT_WITHOUT_REQUEST",
            9: "MUTEX_RESET_DID_NOT_CLEAR",
            10: "MUTEX_WINNER_NOT_RETAINED",
            11: "MUTEX_MODEL_RESOLUTION_DELAY_VIOLATED",
        }
        self.assertEqual(DIAGNOSTICS, expected)
        bench = Path(__file__).with_name("mutex_contract.sv").read_text()
        for diagnostic in expected.values():
            self.assertEqual(bench.count(f'$fatal(1,"{diagnostic}")'), 1)

    def test_reference_corruption_is_distinct_from_owner_and_output_faults(self):
        self.assertEqual(fault_kind(0), "none")
        self.assertEqual(fault_kind(10), "sampled_reference_corruption")
        for fault in (1, 2, 3, 4):
            self.assertEqual(fault_kind(fault), "owner_protocol_fault")
        for fault in (5, 6, 7, 8, 9, 11):
            self.assertEqual(fault_kind(fault), "injected_output_fault")
        with self.assertRaisesRegex(ValueError, "MUTEX_UNKNOWN_FAULT"):
            fault_kind(12)


class MutexLogVerdict(unittest.TestCase):
    passed = "MUTEX_CONTRACT_PASS grants=12 returns=12 epochs=4 unresolved=15\n"
    fatal = "FATAL: path/mutex_contract.sv:40: MUTEX_REQUEST_WITHDRAWN_BEFORE_SERVICE\n       Time: 204 Scope: MutexContract\n"
    expected = "MUTEX_REQUEST_WITHDRAWN_BEFORE_SERVICE"

    def test_success_and_only_expected_failure(self):
        self.assertTrue(accepts_log(0, self.passed))
        self.assertTrue(accepts_log(1, self.fatal, self.expected, 40))

    def test_error_cannot_hide_in_positive_or_expected_failure(self):
        self.assertFalse(accepts_log(0, "ERROR: bad assertion\n" + self.passed))
        self.assertFalse(accepts_log(1, "ERROR: bad assertion\n" + self.fatal, self.expected, 40))

    def test_positive_rejects_fatal_even_with_success_returncode(self):
        self.assertFalse(accepts_log(0, self.fatal + self.passed))

    def test_wrong_duplicate_or_unrelated_fatal_cannot_pass(self):
        for text in (self.fatal * 2, self.fatal + "FATAL: other.sv:1: UNRELATED\n",
                     self.fatal.replace(":40:", ":41:"), self.fatal.replace(self.expected, "OTHER")):
            self.assertFalse(accepts_log(1, text, self.expected, 40))

    def test_no_activity_deadline_or_missing_output_is_not_expected_failure(self):
        for text in ("", "FATAL: path/mutex_contract.sv:40: MUTEX_CONTRACT_DEADLINE\n",
                     "FATAL: path/mutex_contract.sv:40: MUTEX_CONTRACT_ACTIVITY\n"):
            self.assertFalse(accepts_log(1, text, self.expected, 40))
            self.assertFalse(accepts_log(0, text))

    def test_expected_failure_may_not_also_report_pass(self):
        self.assertFalse(accepts_log(1, self.fatal + self.passed, self.expected, 40))


if __name__ == "__main__":
    unittest.main()
