# SPDX-License-Identifier: Apache-2.0
import xml.etree.ElementTree as ET
import pytest
from run_chiselsim import ACTIVITY, CASES, verify


@pytest.mark.parametrize("fault,diagnostic", [("empty", "CHISELSIM_TEST_INVENTORY"),
    ("missing", "CHISELSIM_TEST_INVENTORY"), ("skipped", "CHISELSIM_TEST_FAILURE"),
    ("failed", "CHISELSIM_TEST_FAILURE"), ("inactive", "CHISELSIM_MISSING_ACTIVITY")])
def test_native_lane_cannot_pass_with_missing_or_failed_activity(tmp_path, fault, diagnostic):
    root = ET.Element("testsuite")
    for name in sorted(CASES):
        ET.SubElement(root, "testcase", name=name)
    if fault == "empty": root.clear()
    if fault == "missing": root.remove(root[0])
    if fault in ("skipped", "failed"): ET.SubElement(root[0], "skipped" if fault == "skipped" else "failure")
    xml = tmp_path / "test.xml"
    ET.ElementTree(root).write(xml)
    with pytest.raises(RuntimeError, match=diagnostic):
        verify(xml, "" if fault == "inactive" else "\n".join(ACTIVITY))
