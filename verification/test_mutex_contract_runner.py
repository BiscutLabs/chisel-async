# SPDX-License-Identifier: Apache-2.0
import unittest
from run_mutex_contract import accepts_log


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
