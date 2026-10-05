# SPDX-License-Identifier: Apache-2.0
"""Install the exact Temurin release without a three-component SemVer adapter."""
import hashlib
import os
from pathlib import Path
import platform
import subprocess
import tarfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "21.0.12.1+1"
ASSETS = {
    ("Windows", "amd64"): ("OpenJDK21U-jdk_x64_windows_hotspot_21.0.12.1_1.zip",
                            "f9d6e191ab098c0d416e7d588a24420a8621cd2f4720dab2459b8b7b2d2d8b4e"),
    ("Linux", "x86_64"): ("OpenJDK21U-jdk_x64_linux_hotspot_21.0.12.1_1.tar.gz",
                          "ce79869e1307ed8ee1e2baa86a412b1eb5b75d10a01006d788a6f968bcfaee94"),
}


def main():
    key = (platform.system(), platform.machine().lower())
    if key not in ASSETS:
        raise RuntimeError(f"No qualified JDK bootstrap for {key}; macOS qualification is deferred")
    name, checksum = ASSETS[key]
    destination = ROOT / ".tools/jdk21"
    java_home = destination / f"jdk-{VERSION}"
    java = java_home / "bin" / ("java.exe" if os.name == "nt" else "java")
    if not java.is_file():
        destination.mkdir(parents=True, exist_ok=True)
        archive = destination / name
        if not archive.is_file():
            url = f"https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.12.1%2B1/{name}"
            with urllib.request.urlopen(url, timeout=60) as response:
                archive.write_bytes(response.read())
        if hashlib.sha256(archive.read_bytes()).hexdigest() != checksum:
            raise RuntimeError("JDK archive checksum mismatch")
        if name.endswith("zip"):
            with zipfile.ZipFile(archive) as bundle:
                for entry in bundle.namelist():
                    if not (destination / entry).resolve().is_relative_to(destination.resolve()):
                        raise RuntimeError("Unsafe JDK archive entry")
                bundle.extractall(destination)
        else:
            with tarfile.open(archive) as bundle:
                bundle.extractall(destination, filter="data")
    result = subprocess.run([str(java), "--version"], text=True, capture_output=True, check=True)
    if VERSION not in result.stdout or "Temurin" not in result.stdout:
        raise RuntimeError(f"Unexpected JDK: {result.stdout}")
    if "GITHUB_ENV" in os.environ:
        with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as stream:
            stream.write(f"JAVA_HOME={java_home}\n")
        with open(os.environ["GITHUB_PATH"], "a", encoding="utf-8") as stream:
            stream.write(str(java_home / "bin") + "\n")
    print(f"JAVA_HOME={java_home}")
    print(result.stdout.strip())


if __name__ == "__main__":
    main()
