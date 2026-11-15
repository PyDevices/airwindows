# SPDX-FileCopyrightText: Copyright (c) 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Every plug-in builds, takes its knobs, and renders, in both variants.

The accuracy of each one against upstream is tests/check_reference.py's
job; this is the quick pass that every class the module lists is there and
plays, at every channel count, without a crash or a value that isn't a
sample.
"""

import unittest
from array import array

import _audioairwindows
import audioairwindows


def burst(frames, channels):
    values = array("h")
    x = 1
    for i in range(frames * channels):
        x = (x * 1103515245 + 12345) & 0x7fffffff
        values.append(((x >> 16) % 16001) - 8000 if i < frames else 0)
    return values.tobytes()


class EveryPlugin(unittest.TestCase):
    def test_listed(self):
        self.assertGreater(len(audioairwindows.__all__), 500)
        for name in audioairwindows.__all__:
            cls = getattr(audioairwindows, name)
            self.assertEqual(cls._NAME, name)
            self.assertEqual(len(set(cls._PARAMS)), len(cls._PARAMS))

    def test_renders(self):
        for channels in (1, 2):
            pcm = burst(1024, channels)
            for name in audioairwindows.__all__:
                cls = getattr(audioairwindows, name)
                for fast in (False, True):
                    with self.subTest(name=name, channels=channels, fast=fast):
                        state = _audioairwindows.State(
                            name, sample_rate=48000, channel_count=channels,
                            fast=fast)
                        for index in range(len(cls._PARAMS)):
                            state.configure(index, 0.7)
                        out = state.process(pcm)
                        self.assertEqual(len(out), len(pcm))
                        state.reset()
                        self.assertEqual(len(state.process_silence(300)),
                                         600 * channels)

    def test_node_surface(self):
        node = audioairwindows.Pressure4(sample_rate=44100, channel_count=1)
        node.set(**{p: 0.25 for p in node._PARAMS})
        with self.assertRaises(TypeError):
            node.set(no_such_knob=1)


class SinglePrecision(unittest.TestCase):
    """Plug-ins whose fast variant, the one a board with no double FPU runs,
    is a single-precision loop of their own rather than the full-precision
    one. check_reference.py holds them to upstream; this checks they still
    run their own loop, and stay near the full one."""

    NAMES = ("Density", "Density2")

    def test_fast_is_its_own_loop_and_stays_close(self):
        pcm = burst(4096, 2)
        for name in self.NAMES:
            count = len(getattr(audioairwindows, name)._PARAMS)
            worst = 0
            for rate in (48000, 192000):
                for value in (0.25, 0.75, 1.0):
                    out = {}
                    for fast in (False, True):
                        state = _audioairwindows.State(
                            name, sample_rate=rate, channel_count=2,
                            fast=fast)
                        for index in range(count):
                            state.configure(index, value)
                        out[fast] = array("h", state.process(pcm))
                    steps = max(abs(a - b)
                                for a, b in zip(out[False], out[True]))
                    with self.subTest(name=name, rate=rate, value=value):
                        self.assertLessEqual(steps, 3)
                    worst = max(worst, steps)
            # The same output everywhere means the fast slot runs the full
            # loop: the plug-in has fallen back to full precision on boards.
            self.assertGreater(worst, 0, name)


if __name__ == "__main__":
    unittest.main()
