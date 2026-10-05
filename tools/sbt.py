"""Run the pinned sbt launcher with a JDK already installed on the host."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.12.4"
SHA256 = "45eb459f46b234ccdfe4a16c6863dc5a793ac5f71acc2412a2b2b5b176461104"


def main() -> int:
    args = sys.argv[1:]
    bootstrap = "--bootstrap" in args
    args = [arg for arg in args if arg != "--bootstrap"]
    launcher = ROOT / ".tools" / f"sbt-launch-{VERSION}.jar"
    if not launcher.exists():
        if not bootstrap:
            raise RuntimeError("Missing sbt launcher. Run tools/sbt.py --bootstrap <tasks> to fetch it.")
        launcher.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://repo.maven.apache.org/maven2/org/scala-sbt/sbt-launch/{VERSION}/{launcher.name}"
        with urllib.request.urlopen(url, timeout=60) as response:
            contents = response.read()
        if hashlib.sha256(contents).hexdigest() != SHA256:
            raise RuntimeError("Downloaded sbt launcher checksum mismatch")
        launcher.write_bytes(contents)
    if hashlib.sha256(launcher.read_bytes()).hexdigest() != SHA256:
        raise RuntimeError("Cached sbt launcher checksum mismatch")
    java_home = os.environ.get("JAVA_HOME")
    java = str(Path(java_home) / "bin" / ("java.exe" if os.name == "nt" else "java")) if java_home else shutil.which("java")
    if not java:
        raise RuntimeError("A JDK is required; install JDK 21 or set JAVA_HOME.")
    environment = dict(os.environ)
    # A local, explicitly installed compiler is convenient; never select another version.
    if "CHISEL_FIRTOOL_PATH" not in environment:
        executable = "firtool.exe" if os.name == "nt" else "firtool"
        matches = list((ROOT / ".tools" / "firtool-1.160.0").rglob(executable))
        if len(matches) == 1:
            environment["CHISEL_FIRTOOL_PATH"] = str(matches[0].parent)
    command = [java, "-Xmx2G", "-XX:ActiveProcessorCount=4", "-Dsbt.supershell=false",
               "-Dsbt.color=false", "-Dsbt.override.build.repos=true",
               f"-Dsbt.repository.config={ROOT / 'project' / 'repositories'}",
               "-jar", str(launcher), *args]
    return subprocess.run(command, cwd=ROOT, env=environment, check=False).returncode


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError) as error:
        print(f"sbt: {error}", file=sys.stderr)
        sys.exit(2)
