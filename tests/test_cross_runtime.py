# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Copyright (c) 2026 Brad Barnett
"""MicroPython and CPython render the same bytes.

Set MICROPYTHON to a unix MicroPython built with audiodsp and this module
(the README says how); without it the comparison skips. The CPython side is
also held to the hashes in test_audioairwindows.py, so a change to what the effects render shows
up here even where no MicroPython is built.
"""

import os
import pathlib
import subprocess
import sys
import unittest

PROBE = pathlib.Path(__file__).resolve().parent / "test_audioairwindows.py"

sys.path.insert(0, str(PROBE.parent))
from test_audioairwindows import (  # noqa: E402
    EXPECTED, EXPECTED_FAST, EXPECTED_FIXED)
import audioairwindows  # noqa: E402


def run(interpreter):
    # Galactic's stereo delay lines take about 1 MB in double precision,
    # more than the unix port's default heap.
    flags = [] if interpreter == sys.executable else ["-X", "heapsize=8M"]
    result = subprocess.run([interpreter] + flags + [str(PROBE)],
                            capture_output=True, text=True, timeout=600)
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return result.stdout


class CPythonRendersTheRecordedBytes(unittest.TestCase):
    def test_hashes(self):
        self.assertEqual(run(sys.executable), EXPECTED_FIXED
                         if audioairwindows.FIXED else EXPECTED_FAST
                         if audioairwindows.FAST else EXPECTED)


@unittest.skipUnless(os.environ.get("MICROPYTHON"),
                     "MICROPYTHON is not set to a built interpreter")
class MicroPythonRendersTheSameBytes(unittest.TestCase):
    def test_same_output(self):
        self.assertEqual(run(os.environ["MICROPYTHON"]), run(sys.executable))


if __name__ == "__main__":
    unittest.main()
