# SPDX-License-Identifier: Apache-2.0
"""Require an active ScalaTest/ChiselSim inventory and retain backend evidence."""
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
CASES = {
    "source bridge preserves held tokens and reset accounting",
    "sink bridge commits once under backpressure and reset",
    "source observation corruption activates the payload oracle",
    "sink observation corruption activates the payload oracle",
    "wide payloads survive the simulator command transport",
}
ACTIVITY = ("CHISELSIM_SOURCE_PASS accepted=265 delivered=264 aborted=1",
            "CHISELSIM_SINK_PASS offered=265 delivered=264 aborted=1",
            "CHISELSIM_WIDE_PASS delivered=4 bits=1024")


def verify(xml, log):
    cases = ET.parse(xml).getroot().findall(".//testcase")
    if len(cases) != len(CASES) or {c.attrib["name"] for c in cases} != CASES:
        raise RuntimeError("CHISELSIM_TEST_INVENTORY")
    if any(c.find(tag) is not None for c in cases for tag in ("failure", "error", "skipped")):
        raise RuntimeError("CHISELSIM_TEST_FAILURE")
    if any(log.count(marker) != 1 for marker in ACTIVITY):
        raise RuntimeError("CHISELSIM_MISSING_ACTIVITY")


def run_suite(command, environment, cwd, xml, output):
    output.mkdir(parents=True, exist_ok=True)
    report = output / "report.json"
    record = {"status": "RUNNING", "command": command, "platform": platform.platform(),
              "required": sorted(CASES)}
    def save(): report.write_text(json.dumps(record, indent=2) + "\n")
    save()
    xml.unlink(missing_ok=True)
    try:
        backend = "verilator_bin.exe" if os.name == "nt" else "verilator"
        version = subprocess.run([backend, "--version"], env=environment, capture_output=True,
                                 text=True, check=True, timeout=30).stdout.strip()
        if not version.startswith("Verilator 5.046 "):
            raise RuntimeError("UNQUALIFIED_CHISELSIM_BACKEND")
        record["backend"] = version
        log_path = output / "scalatest.log"
        with log_path.open("w") as log:
            result = subprocess.run(command, cwd=cwd, env=environment, stdout=log,
                                    stderr=subprocess.STDOUT, text=True, timeout=600)
        if result.returncode:
            raise RuntimeError(f"ChiselSim failed: {log_path}")
        verify(xml, log_path.read_text())
        files = [xml, log_path, ROOT / "verification/chiselsim/src/test/scala/chiselasync/BridgeSimulationSpec.scala",
                 ROOT / "tools/svsim_windows.py", ROOT / "tools/svsim_windows_getline.h"]
        record.update(status="PASS", source_and_result_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
                      activity=list(ACTIVITY), scope="clocked digital bridge and simulator transport; no timed primitive or metastability claim")
    except BaseException as error:
        record.update(status="ERROR", error=str(error)); save(); raise
    save()
    print(f"ChiselSim PASS: 3 positive tests and 2 required payload-fault rejections; {report}")


if __name__ == "__main__":
    run_suite([sys.executable, str(ROOT / "tools/sbt.py"), "simulation/test"], dict(os.environ), ROOT,
              ROOT / "verification/chiselsim/target/test-reports/TEST-chiselasync.BridgeSimulationSpec.xml",
              ROOT / "target/verification/chiselsim")
