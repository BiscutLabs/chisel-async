# SPDX-License-Identifier: Apache-2.0
"""Set up the pinned local environment and run every required qualification lane."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]


def run_steps(steps, environment, output):
    output.mkdir(parents=True, exist_ok=True)
    report = output / "report.json"
    result = {"status": "RUNNING", "platform": platform.platform(), "python": sys.version,
              "required": [name for name, _ in steps], "steps": []}
    def save():
        report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    save()  # Invalidate stale success even if the first command cannot start.
    try:
        for name, command in steps:
            print(f"[{name}] running", flush=True)
            log = output / f"{name}.log"
            with log.open("w", encoding="utf-8") as stream:
                process = subprocess.run(command, cwd=ROOT, env=environment, stdout=stream,
                                         stderr=subprocess.STDOUT, text=True, timeout=1800)
            result["steps"].append({"name": name, "command": command, "exit_code": process.returncode,
                                    "log": str(log)})
            save()
            if process.returncode:
                raise RuntimeError(f"{name} failed; see {log}\n" + "\n".join(log.read_text(errors="replace").splitlines()[-25:]))
            print(f"[{name}] PASS", flush=True)
        if not steps:
            raise RuntimeError("EMPTY_QUALIFICATION")
        result["status"] = "PASS"
    except BaseException as error:
        result.update(status="ERROR", error=str(error))
        save()
        raise
    save()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-setup", action="store_true", help="Use installed dependencies; still run the full campaign (CI)")
    parser.add_argument("--simulator-dir", type=Path, help="Directory containing native iverilog and vvp")
    args = parser.parse_args()
    output = ROOT / "target/verification/qualification"
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text('{"status":"RUNNING"}\n', encoding="utf-8")
    try:
        if sys.version_info[:2] != (3, 12):
            raise RuntimeError("Qualification requires Python 3.12; see README prerequisites")
        if platform.system() not in ("Windows", "Linux"):
            raise RuntimeError("The active qualification scope is Windows/Linux; macOS is deferred")
        environment = dict(os.environ)
        candidates = [args.simulator_dir] if args.simulator_dir else []
        candidates += [ROOT / ".tools/iverilog/bin", ROOT / ".tools/verilator/bin"]
        if os.name == "nt":
            candidates.append(Path("C:/msys64/ucrt64/bin"))
        environment["PATH"] = os.pathsep.join(str(p) for p in candidates if p and p.is_dir()) + os.pathsep + environment.get("PATH", "")
        python = sys.executable
        setup = []
        if not args.no_setup:
            directory = ROOT / ".venv"
            python_path = directory / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            if not python_path.is_file():
                venv.EnvBuilder(with_pip=True).create(directory)
            python = str(python_path)
            version = subprocess.run([python, "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
                                     capture_output=True, text=True, check=True).stdout.strip()
            if version != "3.12":
                raise RuntimeError("Existing .venv uses another Python version; recreate it with Python 3.12")
            setup += [("pip", [python, "-m", "ensurepip", "--upgrade"])]
            setup += [("dependencies", [python, "-m", "pip", "install", "--require-hashes", "-r", str(ROOT / "verification/requirements.txt")])]
            setup += [("jdk", [python, str(ROOT / "tools/bootstrap_jdk.py")]),
                      ("firtool", [python, str(ROOT / "tools/bootstrap.py")])]
        environment["JAVA_HOME"] = str(ROOT / ".tools/jdk21/jdk-21.0.12.1+1")
        simulator = shutil.which("iverilog", path=environment["PATH"])
        qualified = simulator and "version 13.0 " in subprocess.run([simulator, "-V"], capture_output=True, text=True, check=True).stdout
        if not qualified:
            if args.no_setup or os.name == "nt" or args.simulator_dir:
                raise RuntimeError("Install native Icarus 13 (Windows: MSYS2 UCRT64 mingw-w64-ucrt-x86_64-iverilog), or pass --simulator-dir")
            missing = [name for name in ("autoconf", "gperf", "bison", "flex", "g++", "make") if not shutil.which(name)]
            if missing:
                raise RuntimeError("Install Linux build prerequisites: " + ", ".join(missing))
            setup.append(("iverilog", [python, str(ROOT / "tools/build_iverilog.py")]))
            environment["PATH"] = str(ROOT / ".tools/iverilog/bin") + os.pathsep + environment["PATH"]
        if os.name == "nt":
            verilator = shutil.which("verilator_bin.exe", path=environment["PATH"])
        else:
            verilator = shutil.which("verilator", path=environment["PATH"])
        qualified = verilator and subprocess.run([verilator, "--version"], capture_output=True, text=True).stdout.startswith("Verilator 5.046 ")
        if not qualified:
            if args.no_setup or os.name == "nt":
                raise RuntimeError("ChiselSim requires native Verilator 5.046; see README prerequisites")
            missing = [name for name in ("autoconf", "bison", "flex", "g++", "make", "perl") if not shutil.which(name)]
            if missing:
                raise RuntimeError("Install Verilator build prerequisites: " + ", ".join(missing))
            setup.append(("verilator", [python, str(ROOT / "tools/build_verilator.py")]))
            environment["PATH"] = str(ROOT / ".tools/verilator/bin") + os.pathsep + environment["PATH"]
        # Some sbt runMain failures on background threads can return exit 0.
        # A generator must replace every contract before any consumer can pass.
        for contract in (ROOT / "target/generated").rglob("contract.json"):
            contract.write_text('{"status":"INVALIDATED"}\n', encoding="utf-8")
        build = [python, str(ROOT / "tools/sbt.py")] + ([] if args.no_setup else ["--bootstrap"]) + ["test",
                 "examples/runMain chiselasync.examples.EmitFixtures target/generated",
                 "examples/runMain chiselasync.examples.EmitControllerComparison target/generated/comparison_unsafe",
                 "examples/runMain chiselasync.examples.EmitLongHold target/generated",
                 "examples/runMain chiselasync.examples.EmitArchitecture target/generated",
                 "examples/runMain chiselasync.examples.EmitOptimized target/generated"]
        steps = setup + [("build", build), ("export", [python, str(ROOT / "tools/check_export.py")]),
            ("python", [python, "-m", "pytest", *[str(p) for p in sorted((ROOT / "verification").glob("test_*.py"))], "-q"])]
        steps += [(name, [python, str(ROOT / path)]) for name, path in (
            ("functional", "verification/run.py"), ("counterexample", "verification/controller_race.py"),
            ("comparison", "verification/compare_controllers.py"), ("timing", "verification/run_timing.py"),
            ("longhold", "verification/run_longhold.py"), ("architecture", "verification/run_architecture.py"),
            ("optimized", "verification/run_optimized.py"))]
        steps += [("chiselsim", [python, str(ROOT / "verification/run_chiselsim.py")]),
                  ("consumer", [python, str(ROOT / "tools/consumer_smoke.py")])]
        run_steps(steps, environment, output)
    except BaseException as error:
        # run_steps already preserves per-step evidence; preflight failures need status too.
        record = json.loads((output / "report.json").read_text())
        record.update(status="ERROR", error=str(error))
        (output / "report.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        raise
    print(f"Qualification PASS; evidence: {output / 'report.json'}")


if __name__ == "__main__":
    main()
