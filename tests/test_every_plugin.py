# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Copyright (c) 2026 Brad Barnett
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


if __name__ == "__main__":
    unittest.main()
