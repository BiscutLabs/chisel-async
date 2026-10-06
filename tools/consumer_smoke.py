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
        for name in ("META-INF/LICENSE", "chiselasync/contract-v3.schema.json", "chiselasync/trace-v1.schema.json", "chiselasync/sv/ChiselAsyncCElement_v1.sv",
                     "chiselasync/sv/ChiselAsyncFourPhaseStorage_v1.sv",
                     "chiselasync/sv/ChiselAsyncLatch_v1.sv", "chiselasync/sv/ChiselAsyncDelayLine_v1.sv",
                     "chiselasync/sv/ChiselAsyncAsymmetricC_v1.sv", "chiselasync/sv/ChiselAsyncControlGate_v1.sv",
                     "chiselasync/sv/ChiselAsyncClosingLatch_v1.sv", "chiselasync/sv/ChiselAsyncTimingMarker_v1.sv",
                     "chiselasync/sv/ChiselAsyncAnd_v1.sv", "chiselasync/sv/ChiselAsyncProtocolGuard_v1.sv",
                     "chiselasync/sv/ChiselAsyncXor_v1.sv", "chiselasync/sv/ChiselAsyncToggle_v1.sv",
                     "chiselasync/sv/ChiselAsyncMutex_v1.sv", "chiselasync/sv/ChiselAsyncQdiMarker_v1.sv"):
            if not library.read(name):
                raise RuntimeError(f"Empty published resource: {name}")
    # The space in the path is intentional. Keep outputs for diagnosis/replay.
    parent = ROOT / "target" / "consumers"
    parent.mkdir(parents=True, exist_ok=True)
    consumer = Path(tempfile.mkdtemp(prefix="clean consumer ", dir=parent))
    shutil.copytree(ROOT / "verification/consumer", consumer, dirs_exist_ok=True)
    # Recompile example assembly against only the published library dependency.
    shutil.copy(ROOT / "examples/src/main/scala/chiselasync/examples/EmitReference.scala",
                consumer / "src/main/scala/EmitReference.scala")
    shutil.copy(ROOT / "examples/src/main/scala/chiselasync/examples/EmitQdi.scala",
                consumer / "src/main/scala/EmitQdi.scala")
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
               "-jar", str(ROOT / ".tools/sbt-launch-1.12.4.jar"), "runMain Consumer"]
    subprocess.run(command, cwd=consumer, env=environment, check=True, timeout=180)
    test_source = consumer / "src/test/scala/chiselasync/BridgeSimulationSpec.scala"
    test_source.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "verification/chiselsim/src/test/scala/chiselasync/BridgeSimulationSpec.scala", test_source)
    # Keep native tool paths below Windows MAX_PATH, including Verilator's
    # generated layer files; GNU make also requires a path without spaces.
    environment["CA_CHISELSIM_DIRECTORY"] = str(ROOT / "build/consumer" / consumer.name.rsplit(" ", 1)[-1])
    from svsim_windows import configure
    configure(environment)
    sys.path.insert(0, str(ROOT / "verification"))
    from run_chiselsim import run_suite
    run_suite([*command[:-1], "test"], environment, consumer,
              consumer / "target/test-reports/TEST-chiselasync.BridgeSimulationSpec.xml",
              consumer / "verification/chiselsim")
    subprocess.run([sys.executable, str(ROOT / "verification/run.py"), "--fixtures", "buffer", "structural", "transform", "longhold",
                    "--generated", str(consumer / "generated"), "--output", str(consumer / "verification")],
                   cwd=ROOT, check=True, timeout=180)
    subprocess.run([sys.executable, str(ROOT / "verification/run_timing.py"),
                    "--generated", str(consumer / "generated"), "--output", str(consumer / "verification/timing")],
                   cwd=ROOT, check=True, timeout=180)
    subprocess.run([sys.executable, str(ROOT / "verification/run_longhold.py"), "--seeds", "2",
                    "--generated", str(consumer / "generated"), "--output", str(consumer / "verification/longhold")],
                   cwd=ROOT, check=True, timeout=180)
    subprocess.run([sys.executable, str(ROOT / "verification/run_architecture.py"),
                    "--generated", str(consumer / "generated"), "--output", str(consumer / "verification/architecture")],
                   cwd=ROOT, check=True, timeout=180)
    subprocess.run([sys.executable, str(ROOT / "verification/run_composition.py"), "--seeds", "0",
                    "--generated", str(consumer / "generated"), "--output", str(consumer / "verification/composition")],
                   cwd=ROOT, check=True, timeout=180)
    subprocess.run([sys.executable, str(ROOT / "verification/run_phase.py"), "--seeds", "0", "1", "2", "3",
                    "--generated", str(consumer / "generated"), "--output", str(consumer / "verification/phase")],
                   cwd=ROOT, check=True, timeout=180)
    for lane in ("closure", "mutex", "dims", "reference"):
        subprocess.run([sys.executable, str(ROOT / f"verification/run_{lane}.py"),
                        *(["--seeds", "0", "2", "3"] if lane == "reference" else []),
                        "--generated", str(consumer / "generated"), "--output", str(consumer / "verification" / lane)],
                       cwd=ROOT, check=True, timeout=180)
    subprocess.run([sys.executable, str(ROOT / "verification/run_qdi.py"),
                    "--seeds", "0", "2", "3", "--generated", str(consumer / "generated"),
                    "--output", str(consumer / "verification/qdi")], cwd=ROOT, check=True, timeout=180)
    subprocess.run([sys.executable, str(ROOT / "verification/run_qdi_sequences.py"),
                    "--generated", str(consumer / "generated"),
                    "--output", str(consumer / "verification/qdi-sequences")], cwd=ROOT, check=True, timeout=180)
    print(f"Published artifact consumed and simulated successfully: {consumer}")


if __name__ == "__main__":
    main()
