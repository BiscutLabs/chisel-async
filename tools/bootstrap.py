# SPDX-License-Identifier: Apache-2.0
"""Install the pinned native firtool into this checkout's ignored tool cache."""
import hashlib
from pathlib import Path
import platform
import subprocess
import tarfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ASSETS = {
    ("Windows", "amd64"): ("windows-x64.zip", "f29e5d40125b2d1004611615d65c07dd17e97127c9ee5103abf9694f954a0afe"),
    ("Linux", "x86_64"): ("linux-x64.tar.gz", "bc0a09658f7aee5359997468a1aa100d8851ee0c2f0caac3708e0c95451acbed"),
    ("Darwin", "arm64"): ("macos-arm64.tar.gz", "0115ef422f6f9d2ef24195525e49e01a2a10fc9343e85f8231dfff916f683b22"),
}


def main():
    key = (platform.system(), platform.machine().lower())
    if key not in ASSETS:
        raise RuntimeError(f"No qualified firtool asset configured for {key}")
    suffix, checksum = ASSETS[key]
    destination = ROOT / ".tools" / "firtool-1.160.0"
    executable = "firtool.exe" if key[0] == "Windows" else "firtool"
    matches = list(destination.rglob(executable))
    if not matches:
        archive = ROOT / ".tools" / f"firrtl-bin-{suffix}"
        archive.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://github.com/llvm/circt/releases/download/firtool-1.160.0/{archive.name}"
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != checksum:
            raise RuntimeError("firtool archive checksum mismatch")
        archive.write_bytes(data)
        if suffix.endswith("zip"):
            with zipfile.ZipFile(archive) as bundle:
                for name in bundle.namelist():
                    if not (destination / name).resolve().is_relative_to(destination.resolve()):
                        raise RuntimeError("Unsafe compiler archive entry")
                bundle.extractall(destination)
        else:
            with tarfile.open(archive) as bundle:
                bundle.extractall(destination, filter="data")
        matches = list(destination.rglob(executable))
    if len(matches) != 1:
        raise RuntimeError("Missing or ambiguous firtool executable")
    version = subprocess.run([str(matches[0]), "--version"], capture_output=True, text=True, check=True)
    if "CIRCT firtool-1.160.0" not in version.stdout:
        raise RuntimeError("Unexpected firtool version")
    print(matches[0])
    print(version.stdout.strip())


if __name__ == "__main__":
    main()
