#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Check the type stub in stubs/audioairwindows-stubs against itself and against the code.

From the repository root, with the omnipython-airwindows wheel installed (it brings
audiodsp and the compiled module the stub describes):

    python tools/check_stubs.py

It runs three things, each in its own process with a hard timeout:

1. mypy over the stub, so a stub that doesn't parse or contradicts itself fails.
2. mypy's `stubtest`, which imports `audioairwindows` under CPython and fails when the
   stub and the code disagree about a name or a signature. `tools/stubs/allowlist.txt`
   holds the two differences that are CPython-only, each with its reason.
3. mypy over `tools/stubs/sample_ok.py`, which must pass, and `tools/stubs/sample_bad.py`,
   which must fail with its one planted error, so the stub is proved to reach a user
   and to catch a mistake.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STUBS = ROOT / "stubs"
SAMPLES = ROOT / "tools" / "stubs"
TIMEOUT = 300  # seconds, per step


def run(command, env=None):
    try:
        return subprocess.run(command, env=env, timeout=TIMEOUT, capture_output=True, text=True, check=False)
    except subprocess.TimeoutExpired:
        print("timed out: " + " ".join(command))
        return None


def show(result):
    if result is not None:
        print((result.stdout + result.stderr).rstrip())


def main():
    status = 0
    mypy = [sys.executable, "-m", "mypy", "--no-incremental"]
    stub = STUBS / "audioairwindows-stubs" / "__init__.pyi"
    with tempfile.TemporaryDirectory() as scratch:
        # MYPYPATH wants the stub as a module name; the wheel ships it as a `-stubs`
        # package, which a type checker finds in site-packages instead.
        shutil.copy2(stub, Path(scratch) / "audioairwindows.pyi")
        env = dict(os.environ, MYPYPATH=scratch)

        print("== mypy over the stub")
        result = run(mypy + ["--no-site-packages", str(Path(scratch) / "audioairwindows.pyi")])
        show(result)
        status |= result is None or result.returncode != 0

        print("== stubtest audioairwindows")
        result = run([sys.executable, "-m", "mypy.stubtest", "--allowlist", str(SAMPLES / "allowlist.txt"), "audioairwindows"], env)
        show(result)
        status |= result is None or result.returncode != 0

        print("== sample a user writes: must pass")
        result = run(mypy + [str(SAMPLES / "sample_ok.py")], env)
        show(result)
        status |= result is None or result.returncode != 0

        print("== sample with one planted error: must fail")
        result = run(mypy + [str(SAMPLES / "sample_bad.py")], env)
        show(result)
        if result is None or result.returncode == 0 or '"drive" to "PurestDrive"' not in result.stdout:
            print("the planted error was not reported: the stub is not being read")
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
