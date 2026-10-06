# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from svsim_windows import adapt, CLEAN


@pytest.mark.parametrize("fault,diagnostic", [("outside", "SVSIM_ADAPTER_OUTSIDE_WORKSPACE"),
    ("unknown", "SVSIM_ADAPTER_UNKNOWN_MAKEFILE"), ("recipe", "SVSIM_ADAPTER_UNKNOWN_CLEAN_RECIPE"),
    ("existing", "SVSIM_ADAPTER_REQUIRES_FRESH_WORKSPACE")])
def test_adapter_rejects_unrecognized_or_existing_builds_without_mutating_them(tmp_path, fault, diagnostic):
    root = tmp_path / "workspace"
    directory = (tmp_path if fault == "outside" else root) / "workdir-verilator"
    directory.mkdir(parents=True)
    original = "# This Makefile enables lightweight debugging of `svsim` tests.\n" + CLEAN
    if fault == "unknown": original = "unrelated makefile\n" + CLEAN
    if fault == "recipe": original = original.replace("delims=", "changed=")
    if fault == "existing": (directory / "verilated-sources").mkdir()
    makefile = directory / "Makefile"
    makefile.write_text(original)
    with pytest.raises(RuntimeError, match=diagnostic):
        adapt(directory, root)
    assert makefile.read_text() == original
