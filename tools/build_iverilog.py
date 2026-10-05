# SPDX-License-Identifier: Apache-2.0
"""Build the pinned Icarus 13.0 source on Linux/macOS; Windows uses native MSYS2."""
import hashlib
import os
from pathlib import Path
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REVISION = "dfeee909ed9f20b4870dd93423156c0170c0e1ff"
SHA256 = "c3a18398dd25073845550af2f35926193f4d3aa7cd7080122bdc501f59717c00"


def main():
    if os.name == "nt":
        raise RuntimeError("Use native MSYS2 UCRT64 Icarus on Windows; see README")
    cache = ROOT / ".tools"
    cache.mkdir(exist_ok=True)
    archive = cache / "iverilog-source.tar.gz"
    if not archive.exists():
        with urllib.request.urlopen(f"https://github.com/steveicarus/iverilog/archive/{REVISION}.tar.gz", timeout=60) as response:
            archive.write_bytes(response.read())
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise RuntimeError("Icarus source checksum mismatch")
    source = cache / f"iverilog-{REVISION}"
    if not source.exists():
        with tarfile.open(archive) as bundle:
            bundle.extractall(cache, filter="data")
    prefix = cache / "iverilog"
    for command in (["sh", "autoconf.sh"], ["./configure", f"--prefix={prefix}"],
                    ["make", "-j2"], ["make", "install"]):
        subprocess.run(command, cwd=source, check=True, timeout=600)
    if "GITHUB_PATH" in os.environ:
        with open(os.environ["GITHUB_PATH"], "a", encoding="utf-8") as stream:
            stream.write(str(prefix / "bin") + "\n")
    print(f"Icarus installed. Add to PATH: {prefix / 'bin'}")


if __name__ == "__main__":
    main()
