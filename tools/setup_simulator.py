# SPDX-License-Identifier: Apache-2.0
"""Set up Icarus 13 for consumer tests without the full qualification environment.

Uses a checksum-pinned source build on Linux, or a checksum-pinned MSYS2 UCRT64
package on Windows. Requires the platform prerequisites documented in testing.md.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request

from build_iverilog import ROOT

PACKAGE = 'mingw-w64-ucrt-x86_64-iverilog-1~13.0-2-any.pkg.tar.zst'
PACKAGE_SHA = 'fd4d7d7cb60cda1eb437f5476673503d92964cf47ce6c11b460eb3bd05c43582'


def version(executable):
    proc = subprocess.run([str(executable), '-V'], capture_output=True, text=True, timeout=30)
    if proc.returncode:
        raise RuntimeError(f'SIMULATOR_VERSION_FAILED: {executable}')
    return proc.stdout + proc.stderr


def checked_download(url, path, sha):
    if not path.exists():
        with urllib.request.urlopen(url, timeout=60) as response:
            content = response.read()
        if hashlib.sha256(content).hexdigest() != sha:
            raise RuntimeError('SIMULATOR_DOWNLOAD_CHECKSUM')
        path.write_bytes(content)
    if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
        raise RuntimeError('SIMULATOR_DOWNLOAD_CHECKSUM')


def setup(msys2, output, check_only=False):
    output.mkdir(parents=True, exist_ok=True)
    result = dict(status='RUNNING')
    report=output/'setup.json'
    def save():
        report.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    save()
    try:
        directory = msys2/'ucrt64/bin' if os.name=='nt' else ROOT/'.tools/iverilog/bin'
        suffix = '.exe' if os.name=='nt' else ''
        compiler=directory/f'iverilog{suffix}'; runtime=directory/f'vvp{suffix}'
        if not compiler.is_file():
            found=shutil.which('iverilog')
            if found:
                compiler=Path(found); runtime=compiler.with_name(f'vvp{suffix}')
        ready=compiler.is_file() and runtime.is_file() and 'version 13.0 ' in version(compiler) and 'version 13.0 ' in version(runtime)
        if not ready:
            if check_only:
                raise RuntimeError('ICARUS_13_REQUIRED: run setup without --check-only to install')
            if os.name=='nt':
                pacman=msys2/'usr/bin/pacman.exe'; cygpath=msys2/'usr/bin/cygpath.exe'
                if not pacman.is_file() or not cygpath.is_file():
                    raise RuntimeError('Install MSYS2 first or pass --msys2 DIRECTORY')
                cache=ROOT/'.tools'; cache.mkdir(exist_ok=True)
                package=cache/PACKAGE
                checked_download('https://repo.msys2.org/mingw/ucrt64/'+PACKAGE,package,PACKAGE_SHA)
                posix=subprocess.run([str(cygpath),'-u',str(package)],check=True,capture_output=True,text=True).stdout.strip()
                subprocess.run([str(pacman),'-U','--needed','--noconfirm',posix],check=True,timeout=600)
                compiler=directory/'iverilog.exe'; runtime=directory/'vvp.exe'
            else:
                if not sys.platform.startswith('linux'):
                    raise RuntimeError('Automatic setup is tested on Windows/Linux; macOS is deferred')
                missing=[name for name in ('autoconf','gperf','bison','flex','g++','make') if not shutil.which(name)]
                if missing:
                    raise RuntimeError('Install Linux build prerequisites: '+', '.join(missing))
                subprocess.run([sys.executable,str(ROOT/'tools/build_iverilog.py')],check=True,timeout=1800)
                compiler=directory/'iverilog'; runtime=directory/'vvp'
        for tool in (compiler,runtime):
            value=version(tool)
            if 'version 13.0 ' not in value:
                raise RuntimeError(f'ICARUS_13_REQUIRED: {tool}')
            result[tool.stem+'_version']=value
        result.update(status='INSTALLED',CA_IVERILOG=str(compiler.resolve()),CA_VVP=str(runtime.resolve()))
        save()
    except BaseException as error:
        result.update(status='ERROR',error=str(error)); save(); raise
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--msys2',type=Path,default=Path('C:/msys64'))
    parser.add_argument('--output',type=Path,default=ROOT/'build/simulator-setup')
    parser.add_argument('--check-only',action='store_true')
    args=parser.parse_args()
    result=setup(args.msys2,args.output,args.check_only)
    print('Icarus 13 is ready. Configure your consumer with:')
    for key in ('CA_IVERILOG','CA_VVP'):
        print(f"{key}={result[key]}")
    print('Then run: sbt "runMain chiselasync.testing.CheckSimulator"')
