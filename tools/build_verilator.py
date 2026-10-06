# SPDX-License-Identifier: Apache-2.0
"""Build the pinned native Linux ChiselSim backend in the local tool cache."""
import hashlib
import os
from pathlib import Path
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
VERSION = "5.046"
SHA256 = "002bc6d92b203eb8b4612e1d198d8108517d4ec9859e131ef328015352fe6d0c"


def main():
    if os.name == "nt":
        raise RuntimeError("Use native MSYS2 UCRT64 Verilator 5.046; see README")
    cache = ROOT / ".tools"
    cache.mkdir(exist_ok=True)
    archive = cache / f"verilator-{VERSION}.tar.gz"
    if not archive.exists():
        with urllib.request.urlopen(f"https://github.com/verilator/verilator/archive/refs/tags/v{VERSION}.tar.gz", timeout=60) as response:
            archive.write_bytes(response.read())
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise RuntimeError("Verilator source checksum mismatch")
    source = cache / f"verilator-{VERSION}"
    if not source.exists():
        with tarfile.open(archive) as bundle:
            bundle.extractall(cache, filter="data")
    prefix = cache / "verilator"
    for command in (["autoconf"], ["./configure", f"--prefix={prefix}"],
                    ["make", "-j2", "verilator_exe"], ["make", "installbin", "installdata", "installredirect"]):
        subprocess.run(command, cwd=source, check=True, timeout=1200)
    print(f"Verilator installed. Add to PATH: {prefix / 'bin'}")


if __name__ == "__main__":
    main()
