# SPDX-FileCopyrightText: Copyright (c) 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""What a board build carries by default, and what it can still name.

A plug-in that policy.json marks `board: false` takes more than a core on a
board, so `default` must leave it out, and naming it must still build it.
It runs select.py as micropython.cmake does, and needs nothing installed.
"""

import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SELECT = os.path.join(ROOT, "src", "airwindows", "select.py")
SELECTION = os.path.join(ROOT, "src", "airwindows", "selection.txt")
POLICY = os.path.join(ROOT, "tools", "awgen", "policy.json")

# More than a whole ESP32-S3 core at 48 kHz stereo, at default knobs.
TOO_SLOW = ("ZBandpass2", "ZHighpass2", "ZLowpass2", "ZNotch2")


def select(spec):
    out = subprocess.run([sys.executable, SELECT, SELECTION, spec],
                         capture_output=True, text=True, check=True)
    return set(out.stdout.split())


class Selection(unittest.TestCase):
    def test_too_slow_left_out_of_default(self):
        default = select("default")
        self.assertGreater(len(default), 100)
        for name in TOO_SLOW:
            self.assertNotIn(name, default)

    def test_policy_board_false_left_out_of_default(self):
        with open(POLICY) as f:
            policy = json.load(f)
        off = {n for n, v in policy.items()
               if isinstance(v, dict) and v.get("board") is False}
        self.assertTrue(set(TOO_SLOW) <= off)
        self.assertEqual(off & select("default"), set())

    def test_too_slow_still_built_by_name(self):
        for name in TOO_SLOW:
            self.assertEqual(select(name), {name})
        self.assertTrue(set(TOO_SLOW) <= select("default " + " ".join(TOO_SLOW)))


if __name__ == "__main__":
    unittest.main()
