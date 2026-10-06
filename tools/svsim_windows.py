# SPDX-License-Identifier: Apache-2.0
"""Narrow build adapter for Chisel 7.16.0 svsim on native Windows/MSYS2.

The hardware, simulator protocol and upstream JAR are unchanged. Fresh svsim
workspaces need no second cleanup; normalize generated build paths and supply
the POSIX getline function missing from the native Windows C runtime.
"""
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CLEAN = '''clean:
\tfor /f "delims=" %i in ('dir /b /a-d ^| findstr /v Makefile ^| findstr /v execution-script.txt') do del "%i"
\tfor /d %i in (*) do rmdir /s /q "%i"
'''


def adapt(directory, root):
    directory, root = directory.resolve(), root.resolve()
    if not directory.is_relative_to(root) or directory.name != "workdir-verilator":
        raise RuntimeError("SVSIM_ADAPTER_OUTSIDE_WORKSPACE")
    makefile = directory / "Makefile"
    text = makefile.read_text()
    if not text.startswith("# This Makefile enables lightweight debugging of `svsim` tests."):
        raise RuntimeError("SVSIM_ADAPTER_UNKNOWN_MAKEFILE")
    if text.count(CLEAN) != 1:
        raise RuntimeError("SVSIM_ADAPTER_UNKNOWN_CLEAN_RECIPE")
    # Workspace.reset has already created this directory for this simulation.
    if (directory / "verilated-sources").exists():
        raise RuntimeError("SVSIM_ADAPTER_REQUIRES_FRESH_WORKSPACE")
    text = text.replace(CLEAN, "clean:\n\t@true\n")
    text = re.sub(r"[A-Za-z]:[^'\n]*", lambda m: m[0].replace("\\", "/"), text)
    text = text.replace("-std=c++17", "-std=c++17 -DDPI_DLLISPEC= -DDPI_DLLESPEC= -DVL_TIME_CONTEXT -include " + (ROOT / "tools/svsim_windows_getline.h").as_posix())
    # The C compiler needs a Windows path even when make runs in an MSYS shell.
    text = text.replace("-I$(shell pwd)", "-I" + directory.as_posix())
    makefile.with_suffix(".upstream").write_text(makefile.read_text())
    makefile.write_text(text)
    sources = directory / "sourceFiles.F"
    sources.write_text(sources.read_text().replace("\\", "/"))


def configure(environment):
    if os.name != "nt":
        return
    # Native executables use the matching UCRT64 compiler; MSYS provides make,
    # Perl and the POSIX shell required by upstream Verilator/svsim build files.
    verilator = shutil.which("verilator_bin.exe", path=environment["PATH"])
    if not verilator:
        raise RuntimeError("Install MSYS2 UCRT64 Verilator and GCC for ChiselSim")
    prefix = Path(verilator).parent.parent
    msys = prefix.parent / "usr/bin"
    compiler = prefix / "bin/gcc.exe"
    if not compiler.is_file() or not (msys / "make.exe").is_file():
        raise RuntimeError("Install MSYS2 UCRT64 GCC plus MSYS make for ChiselSim")
    directory = ROOT / ".tools/svsim-windows"
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / "launcher.c"
    source.write_text('''#include <process.h>
#include <stdlib.h>
int main(int argc, char **argv) {
  char **args = calloc(argc + 2, sizeof(char*));
  if (!args) return 2;
  args[0] = getenv("CA_SVSIM_PYTHON"); args[1] = getenv("CA_SVSIM_ADAPTER");
  for (int i=1; i<argc; ++i) args[i+1]=argv[i];
  return (int)_spawnv(_P_WAIT, args[0], (const char * const *)args);
}
''')
    subprocess.run([str(compiler), str(source), "-o", str(directory / "make.exe")], env=environment, check=True)
    environment.update(CA_SVSIM_PYTHON=sys.executable, CA_SVSIM_ADAPTER=str(Path(__file__).resolve()),
                       CA_SVSIM_MAKE=str(msys / "make.exe"), CA_SVSIM_ROOT=str(ROOT))
    environment["PATH"] = os.pathsep.join((str(directory), str(prefix / "bin"), str(msys), environment["PATH"]))


def main():
    args = sys.argv[1:]
    directory = None
    if len(args) == 3 and args[0] == "-C" and args[2] == "simulation":
        directory = Path(args[1]).resolve()
        adapt(directory, Path(os.environ["CA_SVSIM_ROOT"]))
    code = subprocess.run([os.environ["CA_SVSIM_MAKE"], *args]).returncode
    if code == 0 and directory is not None:
        # svsim requests the literal extensionless executable path on all hosts.
        shutil.copyfile(directory / "simulation.exe", directory / "simulation")
    return code


if __name__ == "__main__":
    sys.exit(main())
