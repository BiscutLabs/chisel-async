# SPDX-License-Identifier: Apache-2.0
"""Consume a locally published JAR without a source-project dependency."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    subprocess.run([sys.executable, str(ROOT / "tools/sbt.py"), "publishLocal"], check=True)
    artifact = ROOT / "target/scala-2.13/chisel-async_2.13-0.1.0-SNAPSHOT.jar"
    with zipfile.ZipFile(artifact) as library:
        for name in ("META-INF/LICENSE", "chiselasync/contract-v1.schema.json", "chiselasync/sv/ChiselAsyncCElement_v1.sv",
                     "chiselasync/sv/ChiselAsyncFourPhaseStorage_v1.sv",
                     "chiselasync/sv/ChiselAsyncLatch_v1.sv", "chiselasync/sv/ChiselAsyncDelayLine_v1.sv"):
            if not library.read(name):
                raise RuntimeError(f"Empty published resource: {name}")
    # The space in the path is intentional. Keep outputs for diagnosis/replay.
    parent = ROOT / "target" / "consumers"
    parent.mkdir(parents=True, exist_ok=True)
    consumer = Path(tempfile.mkdtemp(prefix="clean consumer ", dir=parent))
    shutil.copytree(ROOT / "verification/consumer", consumer, dirs_exist_ok=True)
    (consumer / "project").mkdir()
    shutil.copy(ROOT / "project/build.properties", consumer / "project/build.properties")
    environment = dict(os.environ)
    if "CHISEL_FIRTOOL_PATH" not in environment:
        name = "firtool.exe" if os.name == "nt" else "firtool"
        matches = list((ROOT / ".tools/firtool-1.160.0").rglob(name))
        if len(matches) != 1:
            raise RuntimeError("Run tools/bootstrap.py first or set CHISEL_FIRTOOL_PATH")
        environment["CHISEL_FIRTOOL_PATH"] = str(matches[0].parent)
    java_home = environment.get("JAVA_HOME")
    java = str(Path(java_home) / "bin" / ("java.exe" if os.name == "nt" else "java")) if java_home else shutil.which("java")
    command = [java, "-Xmx2G", "-XX:ActiveProcessorCount=4", "-Dsbt.supershell=false", "-Dsbt.color=false",
               "-Dsbt.override.build.repos=true", f"-Dsbt.repository.config={ROOT / 'project/repositories'}",
               "-jar", str(ROOT / ".tools/sbt-launch-1.12.4.jar"), "run"]
    subprocess.run(command, cwd=consumer, env=environment, check=True, timeout=180)
    subprocess.run([sys.executable, str(ROOT / "verification/run.py"), "--fixtures", "buffer", "structural", "transform",
                    "--generated", str(consumer / "generated"), "--output", str(consumer / "verification")],
                   cwd=ROOT, check=True, timeout=180)
    subprocess.run([sys.executable, str(ROOT / "verification/run_timing.py"),
                    "--generated", str(consumer / "generated"), "--output", str(consumer / "verification/timing")],
                   cwd=ROOT, check=True, timeout=180)
    print(f"Published artifact consumed and simulated successfully: {consumer}")


if __name__ == "__main__":
    main()
