# SPDX-License-Identifier: Apache-2.0
"""Exercise actual CIRCT import of packaged scalar continuous-delay models."""
from pathlib import Path
import os
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODELS = ("ChiselAsyncControlGate_v1", "ChiselAsyncAsymmetricC_v1", "ChiselAsyncClosingLatch_v1")


def importer():
    executable = "circt-verilog.exe" if os.name == "nt" else "circt-verilog"
    candidates = list((ROOT / ".tools/firtool-1.160.0").rglob(executable))
    if os.environ.get("CHISEL_FIRTOOL_PATH"):
        candidates.insert(0, Path(os.environ["CHISEL_FIRTOOL_PATH"]) / executable)
    command = next((str(path) for path in candidates if path.is_file()), shutil.which(executable))
    assert command, "Required circt-verilog missing; run tools/qualify.py setup"
    version = subprocess.run([command, "--version"], capture_output=True, text=True, check=True)
    assert "CIRCT firtool-1.160.0" in version.stdout, "UNQUALIFIED_CIRCT_IMPORTER"
    return command


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("delay", (0, 1000))
def test_packaged_continuous_delay_reaches_llhd(tmp_path, model, delay):
    source = ROOT / "src/main/resources/chiselasync/sv" / (model + ".sv")
    output = tmp_path / "import.mlir"
    result = subprocess.run([importer(), "--top", model, "-G", f"DELAY_FS={delay}",
                             str(source), "-o", str(output)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    ir = output.read_text()
    assert f"hw.module @{model}" in ir
    assert "llhd.delay" in ir and f"by <{delay}fs, 0d, 0e>" in ir, "LOST_MODEL_DELAY"


@pytest.mark.parametrize("model", MODELS)
def test_parenthesized_continuous_delay_reproduces_importer_diagnostic(tmp_path, model):
    source = ROOT / "src/main/resources/chiselasync/sv" / (model + ".sv")
    text = source.read_text()
    assert text.count("assign #DELAY_FS") == 1
    mutant = tmp_path / source.name
    mutant.write_text(text.replace("assign #DELAY_FS", "assign #(DELAY_FS)"))
    result = subprocess.run([importer(), "--top", model, str(mutant), "-o", str(tmp_path / "bad.mlir")],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert "unsupported delay with rise/fall/turn-off" in result.stderr
