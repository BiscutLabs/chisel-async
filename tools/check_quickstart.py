"""Compile, export and simulate the documented standalone JAR consumer."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

from release import ROOT, artifact_paths, git, sha, verify, write_json
from svsim_windows import configure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distribution", type=Path, help="Use an existing release distribution; never rebuild it")
    parser.add_argument("--qualification-report", type=Path)
    parser.add_argument("--evidence", type=Path, help="Directory for the portable release-consumer report")
    args = parser.parse_args()
    if args.evidence:
        args.evidence.mkdir(parents=True, exist_ok=True)
        write_json(args.evidence / f"consumer-{platform.system()}.json", {"status": "RUNNING"})
    environment = dict(os.environ)
    simulator_paths = [ROOT / ".tools/iverilog/bin", ROOT / ".tools/verilator/bin"]
    if os.name == "nt":
        simulator_paths.append(Path("C:/msys64/ucrt64/bin"))
    environment["PATH"] = os.pathsep.join(str(p) for p in simulator_paths if p.is_dir()) + os.pathsep + environment.get("PATH", "")
    environment.setdefault("JAVA_HOME", str(ROOT / ".tools/jdk21/jdk-21.0.12.1+1"))
    if "CHISEL_FIRTOOL_PATH" not in environment:
        executable = "firtool.exe" if os.name == "nt" else "firtool"
        matches = list((ROOT / ".tools/firtool-1.160.0").rglob(executable))
        if len(matches) != 1:
            raise RuntimeError("Install firtool 1.160.0 or set CHISEL_FIRTOOL_PATH")
        environment["CHISEL_FIRTOOL_PATH"] = str(matches[0].parent)
    distribution = args.distribution.resolve() if args.distribution else None
    manifest = verify(distribution) if distribution else None
    if manifest and manifest["commit"] != git("rev-parse", "HEAD"):
        raise RuntimeError("Consumer checkout does not match the release commit")
    if not distribution:
        subprocess.run([sys.executable, str(ROOT / "tools/sbt.py"), "--bootstrap", "publishLocal"],
                       env=environment, check=True, cwd=ROOT, timeout=600)
    parent = ROOT / "target/consumers"
    parent.mkdir(parents=True, exist_ok=True)
    consumer = Path(tempfile.mkdtemp(prefix="quickstart ", dir=parent))
    shutil.copytree(ROOT / "examples/quickstart", consumer, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("target", "generated", "build", ".bsp", ".metals"))
    version = manifest["version"] if manifest else "0.1.0-SNAPSHOT"
    build = consumer / "build.sbt"
    build.write_text(build.read_text(encoding="utf-8").replace('"0.1.0-SNAPSHOT"', f'"{version}"') + """
lazy val recordDependencies = taskKey[Unit]("Record the actual resolved consumer classpath")
recordDependencies := IO.write(baseDirectory.value / "resolved-classpath.txt",
  (Compile / dependencyClasspath).value.files.map(_.getAbsolutePath).mkString("\\n"))
""", encoding="utf-8")
    repositories = consumer / "repositories"
    resolver = f"candidate: {(distribution / 'maven').as_uri()}\n" if distribution else "local\n"
    repositories.write_text("[repositories]\n" + resolver +
                            "maven-central: https://repo.maven.apache.org/maven2\n", encoding="utf-8")
    environment["CA_CHISELSIM_DIRECTORY"] = str(ROOT / "build/quickstart" / consumer.name.split()[-1])
    configure(environment)
    java = Path(environment["JAVA_HOME"]) / "bin" / ("java.exe" if os.name == "nt" else "java")
    command = [str(java), "-Xmx2G", "-XX:ActiveProcessorCount=4", "-Dsbt.supershell=false",
               "-Dsbt.color=false", "-Dsbt.override.build.repos=true",
               f"-Dsbt.repository.config={repositories}", "-jar",
               str(ROOT / ".tools/sbt-launch-1.12.4.jar"),
               "recordDependencies", "runMain EmitQuickstart", "test"]
    evidence = consumer / "verification/quickstart"
    evidence.mkdir(parents=True)
    result = {"status": "RUNNING", "system": platform.system(), "commit": git("rev-parse", "HEAD"),
              "manifest_sha256": sha(distribution / "manifest.json") if distribution else None,
              "qualification_status": None, "version": version}
    write_json(evidence / "report.json", result)
    try:
        with (evidence / "build.log").open("w", encoding="utf-8") as log:
            subprocess.run(command, cwd=consumer, env=environment, stdout=log, stderr=subprocess.STDOUT,
                           check=True, timeout=900)
        resolved = [Path(line) for line in (consumer / "resolved-classpath.txt").read_text().splitlines()
                    if Path(line).name.startswith("chisel-async_2.13") and line.endswith(".jar")]
        if len(resolved) != 1:
            raise RuntimeError("Consumer did not resolve exactly one library JAR")
        result["library_sha256"] = sha(resolved[0])
        if manifest and result["library_sha256"] != sha(artifact_paths(distribution, version)[0]):
            raise RuntimeError("Consumer used a different library JAR")
        suite = ET.parse(consumer / "target/test-reports/TEST-BridgeSpec.xml").getroot()
        cases = suite.findall("testcase")
        if (suite.get("tests") != "1" or len(cases) != 1
                or cases[0].get("name") != "holds tokens through return"
                or any(node.tag in {"failure", "error", "skipped"} for node in suite.iter())):
            raise RuntimeError("Quickstart simulation inventory or result mismatch")
        for name, count in (("AsyncDesignSpec", 2), ("RoutingSpec", 5), ("AsicMappingSpec", 2), ("ProtocolTestSpec", 12)):
            async_suite = ET.parse(consumer / f"target/test-reports/TEST-{name}.xml").getroot()
            if (len(async_suite.findall("testcase")) != count or int(async_suite.get("tests", "0")) != count
                    or any(node.tag in {"failure", "error", "skipped"} for node in async_suite.iter())):
                raise RuntimeError(f"Quickstart async inventory or result mismatch: {name}")
        result["async_campaigns"] = {}
        for fixture, count in (("routing-mux",300), ("routing-regfork",300), ("routing-phase",16)):
            cases = sorted((consumer / "build" / fixture).glob("seed-*/result.json"))
            records = [json.loads(p.read_text()) for p in cases]
            if (len(records) != count or {int(r["seed"]) for r in records} != set(range(1,count+1))
                    or any(r["status"] != "PASS" or not r["activity"] for r in records)):
                raise RuntimeError(f"Missing async delay campaign evidence: {fixture}")
            result["async_campaigns"][fixture] = {"cases":count,"result_sha256":{p.parent.name:sha(p) for p in cases}}
        with (evidence / "export.log").open("w", encoding="utf-8") as log:
            for exported in ("generated", "build/async-gcd/export", "build/routing-mux/export", "build/routing-regfork/export", "build/routing-phase/export"):
                subprocess.run([sys.executable, str(ROOT / "tools/check_export.py"), str(consumer / exported)],
                               env=environment, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                               check=True, timeout=180)
        if not (consumer / "generated/resolved.json").is_file():
            raise RuntimeError("Quickstart export produced no resolution evidence")
        if args.qualification_report:
            qualification = json.loads(args.qualification_report.read_text(encoding="utf-8"))
            required = qualification.get("required", [])
            steps = qualification.get("steps", [])
            if (qualification.get("status") != "PASS" or not required
                    or [step.get("name") for step in steps] != required
                    or any(step.get("exit_code") != 0 for step in steps)
                    or not {"build", "export", "consumer", "chiselsim", "quickstart"}.issubset(required)):
                raise RuntimeError("Complete native qualification has not passed")
            result["qualification_status"] = "PASS"
            result["qualification_sha256"] = sha(args.qualification_report)
        result["status"] = "PASS"
    except BaseException as error:
        result.update(status="ERROR", error=str(error))
        raise
    finally:
        write_json(evidence / "report.json", result)
        if args.evidence:
            args.evidence.mkdir(parents=True, exist_ok=True)
            write_json(args.evidence / f"consumer-{platform.system()}.json", result)
        print(f"Quickstart {result['status']}: {evidence}", flush=True)


if __name__ == "__main__":
    main()
