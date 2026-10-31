# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Copyright (c) 2026 Brad Barnett
"""audioairwindows on CPython: the surface, the errors, and what each effect
does that a listener would notice."""

import unittest
from array import array

import audioairwindows
import audiocore

RATE = 48000
EFFECTS = (audioairwindows.Galactic, audioairwindows.PurestDrive,
           audioairwindows.ButterComp2)


def source(frames=4096, burst=1024, channels=2, level=12000):
    values = array("h")
    x = 1
    for frame in range(frames):
        for _ in range(channels):
            x = (x * 1103515245 + 12345) & 0x7fffffff
            noise = ((x >> 16) % 2001) - 1000
            values.append(noise * level // 1000 if frame < burst else 0)
    return audiocore.RawSample(values, sample_rate=RATE,
                               channel_count=channels)


def render(node, blocks):
    return b"".join(bytes(audiocore.get_buffer(node)[1])
                    for _ in range(blocks))


def peak(data):
    values = array("h")
    values.frombytes(data)
    return max((abs(v) for v in values), default=0)


class Surface(unittest.TestCase):
    def test_audio_sample_fields(self):
        for kind in EFFECTS:
            for channels in (1, 2):
                with self.subTest(kind=kind.__name__, channels=channels):
                    node = kind(sample_rate=22050, channel_count=channels)
                    self.assertEqual(node.sample_rate, 22050)
                    self.assertEqual(node.channel_count, channels)
                    self.assertEqual(node.bits_per_sample, 16)
                    self.assertTrue(node.samples_signed)
                    node.play(source(channels=channels))
                    result, data = audiocore.get_buffer(node)
                    self.assertEqual(len(bytes(data)), 256 * 2 * channels)

    def test_unknown_option_is_refused(self):
        for kind in EFFECTS:
            with self.subTest(kind=kind.__name__):
                with self.assertRaises(TypeError):
                    kind(volume=1.0)
                node = kind()
                with self.assertRaises(TypeError):
                    node.set(volume=1.0)

    def test_fixed_settings_cannot_be_set(self):
        node = audioairwindows.Galactic()
        for name in ("sample_rate", "channel_count"):
            with self.assertRaises(TypeError):
                node.set(**{name: 1})

    def test_channel_count_is_one_or_two(self):
        for count in (0, 3):
            with self.assertRaises(ValueError):
                audioairwindows.PurestDrive(channel_count=count)

    def test_options_are_clamped(self):
        """Every knob is 0..1, as upstream's are; past the end is the end."""
        a = audioairwindows.ButterComp2(compress=7.0, output=-3.0)
        b = audioairwindows.ButterComp2(compress=1.0, output=0.0)
        a.play(source())
        b.play(source())
        self.assertEqual(render(a, 8), render(b, 8))

    def test_parameters_describe_the_knobs(self):
        """Keyword, upstream's display name and default, in upstream's order."""
        node = audioairwindows.Galactic()
        self.assertEqual(node.parameters(), (
            ("replace", "Replace", 0.5), ("brightness", "Brightness", 0.5),
            ("detune", "Detune", 0.5), ("bigness", "Bigness", 1.0),
            ("dry_wet", "Dry/Wet", 1.0)))
        for name in audioairwindows.__all__:
            kind = getattr(audioairwindows, name)
            described = kind(channel_count=1).parameters()
            self.assertEqual(tuple(p[0] for p in described), kind._PARAMS)

    def test_get_reads_where_a_knob_is(self):
        node = audioairwindows.Galactic(bigness=0.25)
        self.assertEqual(node.get("replace"), 0.5)
        self.assertEqual(node.get("bigness"), 0.25)
        node.set(replace=3.0)
        self.assertEqual(node.get("replace"), 1.0)
        with self.assertRaises(KeyError):
            node.get("nonsense")

    def test_deinit(self):
        node = audioairwindows.Galactic()
        node.deinit()
        with self.assertRaises(ValueError):
            node.set(replace=0.1)


class Behaviour(unittest.TestCase):
    def test_bypass_settings_are_a_wire(self):
        """Galactic and ButterComp2 at dry_wet 0, and PurestDrive at drive 0,
        hand back the input sample for sample."""
        for node in (audioairwindows.Galactic(dry_wet=0.0),
                     audioairwindows.ButterComp2(compress=1.0, dry_wet=0.0),
                     audioairwindows.PurestDrive(drive=0.0)):
            with self.subTest(kind=type(node).__name__):
                node.play(source(frames=2048, burst=2048))
                self.assertEqual(
                    render(node, 8),
                    bytes(audiocore.get_buffer(source(frames=2048,
                                                      burst=2048))[1]))

    def test_galactic_rings_on_and_comes_to_rest(self):
        """The tail outlasts its source, then reaches exact zero. A quiet
        block can come while the long lines still hold sound, so the node
        stops only after a whole line's length of silence, and then stays
        silent."""
        node = audioairwindows.Galactic(replace=0.9, bigness=0.3)
        node.play(source(frames=1024, burst=1024))
        render(node, 4)
        self.assertGreater(peak(render(node, 8)), 0)
        quiet = 0
        for _ in range(6000):
            quiet = 0 if any(render(node, 1)) else quiet + 1
            if quiet == 300:
                break
        else:
            self.fail("the tail never came to rest")
        self.assertFalse(any(render(node, 64)))

    def test_purestdrive_saturates(self):
        clean = audioairwindows.PurestDrive(drive=0.0)
        driven = audioairwindows.PurestDrive(drive=1.0)
        clean.play(source(level=30000))
        driven.play(source(level=30000))
        self.assertNotEqual(render(clean, 4), render(driven, 4))
        # A sine curve only ever pulls a full-scale sample inward.
        self.assertLessEqual(peak(render(driven, 4)), peak(render(clean, 4)))

    def test_buttercomp2_output_is_unity_at_half(self):
        """At compress 0, `output` 0.5 hands the input back within an LSB
        and 1.0 doubles it; compress then changes the sound."""
        def run(**options):
            node = audioairwindows.ButterComp2(**options)
            node.play(source(frames=2048, burst=2048, level=8000))
            out = array("h")
            out.frombytes(render(node, 8))
            return out
        dry = array("h")
        dry.frombytes(bytes(audiocore.get_buffer(
            source(frames=2048, burst=2048, level=8000))[1]))
        unity = run(compress=0.0, output=0.5)
        double = run(compress=0.0, output=1.0)
        squeezed = run(compress=1.0, output=0.5)
        self.assertLessEqual(max(abs(a - b) for a, b in zip(unity, dry)), 1)
        self.assertLessEqual(
            max(abs(a - 2 * b) for a, b in zip(double, dry)), 2)
        self.assertGreater(
            max(abs(a - b) for a, b in zip(squeezed, dry)), 100)

    def test_set_changes_the_next_block(self):
        a = audioairwindows.PurestDrive(drive=0.0)
        b = audioairwindows.PurestDrive(drive=0.0)
        a.play(source(level=30000))
        b.play(source(level=30000))
        self.assertEqual(render(a, 1), render(b, 1))
        b.set(drive=1.0)
        self.assertNotEqual(render(a, 1), render(b, 1))

    def test_clear_renders_as_a_new_node(self):
        for kind in EFFECTS:
            with self.subTest(kind=kind.__name__):
                fresh = kind()
                fresh.play(source())
                expected = render(fresh, 6)
                used = kind()
                used.play(source(level=30000))
                render(used, 6)
                used.clear()
                used.play(source())
                self.assertEqual(render(used, 6), expected)

    def test_mono_is_the_stereo_algorithm_on_both_sides(self):
        """A mono node feeds its one channel to both sides; with identical
        sides upstream's output is identical, so mono equals either side."""
        values = array("h")
        values.frombytes(bytes(audiocore.get_buffer(
            source(channels=1, frames=4096, burst=1024))[1]))
        stereo_values = array("h")
        for v in values:
            stereo_values.extend((v, v))
        for kind in (audioairwindows.PurestDrive,
                     audioairwindows.ButterComp2):
            with self.subTest(kind=kind.__name__):
                mono = kind(channel_count=1, **({"drive": 0.7}
                            if kind is audioairwindows.PurestDrive
                            else {"compress": 0.7}))
                stereo = kind(channel_count=2, **({"drive": 0.7}
                              if kind is audioairwindows.PurestDrive
                              else {"compress": 0.7}))
                mono.play(audiocore.RawSample(values, sample_rate=RATE,
                                              channel_count=1))
                stereo.play(audiocore.RawSample(stereo_values,
                                                sample_rate=RATE,
                                                channel_count=2))
                m = array("h")
                m.frombytes(render(mono, 1))
                s = array("h")
                s.frombytes(render(stereo, 2))
                self.assertEqual(list(m), list(s[0::2])[:len(m)])


if __name__ == "__main__":
    unittest.main()
