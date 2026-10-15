# SPDX-License-Identifier: Apache-2.0
import unittest
from unittest.mock import patch

import check_samples
from characterize import CORNERS


class CornerVoltage(unittest.TestCase):
    def test_every_characterized_corner_uses_its_declared_supply(self):
        for name, _, _, voltage in CORNERS:
            with self.subTest(corner=name):
                self.assertEqual(check_samples.corner_voltage(name), voltage)

    def test_new_corner_name_does_not_need_a_voltage_suffix(self):
        with patch.object(check_samples, "CORNERS", (("new-corner", "typical", 50, 3.15),)):
            self.assertEqual(check_samples.corner_voltage("new-corner"), 3.15)

    def test_unknown_or_ambiguous_corner_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "MUTEX_UNKNOWN_OR_DUPLICATE_CORNER"):
            check_samples.corner_voltage("unknown_3v30")
        with patch.object(check_samples, "CORNERS", (CORNERS[0], CORNERS[0])):
            with self.assertRaisesRegex(ValueError, "MUTEX_UNKNOWN_OR_DUPLICATE_CORNER"):
                check_samples.corner_voltage(CORNERS[0][0])


if __name__ == "__main__":
    unittest.main()
