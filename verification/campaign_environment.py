# SPDX-License-Identifier: Apache-2.0
"""Recorded identity for the required native event simulator."""
import platform
import subprocess
import sys


def identity():
    version=subprocess.run(['iverilog','-V'],capture_output=True,text=True,check=True,timeout=30).stdout.splitlines()[0]
    assert 'version 13.0 ' in version,'UNQUALIFIED_SIMULATOR'
    return dict(simulator=version,python=sys.version,platform=platform.platform())
