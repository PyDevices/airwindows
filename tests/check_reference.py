# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Copyright (c) 2026 Brad Barnett
"""The generated kernels against Airwindows' own code.

Runs tests/reference/check.py, which compiles each plug-in's upstream C++
beside its generated kernel and holds both variants to 2 int16 steps of
upstream at every sample, at four sample rates and seven parameter settings,
with planted faults that it must catch. It needs a C++ compiler and
upstream's source (AIRWINDOWS_UPSTREAM, or .cache/airwindows-upstream at the
commit DEPENDENCIES.lock names); without them it skips.

AW_REFERENCE_PLUGINS chooses what it checks: a list of names, or `all`. By
default it checks a few that cover the generator's corners.
"""

import os
import pathlib
import shutil
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
UPSTREAM = pathlib.Path(os.environ.get(
    "AIRWINDOWS_UPSTREAM", ROOT / ".cache" / "airwindows-upstream"))

# The three this module first shipped by hand, and a few that exercise the
# generator: rand() at run time, #ifdef'd matrices, statics, wide sums.
SAMPLE = ("Galactic", "PurestDrive", "ButterComp2", "Pressure4", "kCosmos",
          "VerbSixes", "TapeHack", "Air3", "Cojones", "ToTape9")


@unittest.skipUnless((UPSTREAM / "plugins").is_dir() and
                     (shutil.which("c++") or shutil.which("g++")),
                     "no upstream checkout or C++ compiler")
class GeneratedKernelsMatchUpstream(unittest.TestCase):
    def test_within_the_bar(self):
        chosen = os.environ.get("AW_REFERENCE_PLUGINS", "").split()
        names = [] if chosen == ["all"] else (chosen or list(SAMPLE))
        result = subprocess.run(
            [sys.executable, str(ROOT / "tests" / "reference" / "check.py"),
             "--faults", "--jobs", str(os.cpu_count() or 2)] + names,
            capture_output=True, text=True, timeout=6 * 3600)
        sys.stdout.write(result.stdout[-4000:])
        self.assertEqual(result.returncode, 0, result.stdout[-2000:] +
                         result.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()
