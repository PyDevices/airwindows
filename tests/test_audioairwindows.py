# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Copyright (c) 2026 Brad Barnett
"""Render every effect and check a hash of its output, one line per case.

Run it under a MicroPython built with audiodsp and this module, or under
CPython with both installed:

    micropython tests/test_audioairwindows.py

It prints one line per case and exits non-zero unless every line matches
EXPECTED. tests/test_cross_runtime.py also runs it under both interpreters
and requires the same lines. Each case plays a noise burst and then silence,
changes a parameter part way through, and renders 400 blocks, so the tails
and the resting reverb are in the hash too.
"""

import array
import gc

import audioairwindows as aw
import audiocore

FRAMES = 48000
BLOCKS = 400
CHANGE_AT = 20

# Rendered from the generated kernels on x86-64 Linux, and by MicroPython's
# unix port there, identically.
EXPECTED = """\
surface [False, True, False, 'TypeError', 'ValueError']
1 Galactic 0xc9e8e76e
1 Galactic 0x11770e1a
1 PurestDrive 0x6697d641
1 ButterComp2 0x8482adc2
2 Galactic 0xfdfe37a8
2 Galactic 0xf5b919f0
2 PurestDrive 0x4e488814
2 ButterComp2 0x41588b6c
"""

# The fast path that ESP32-S3 firmware runs (audioairwindows.FAST), rendered
# by CPython built with AW_FAST_DEFAULT=1 on x86-64 Linux, and by an
# ESP32-S3, identically. PurestDrive's fast path renders the reference's bytes.
EXPECTED_FAST = """\
surface [False, True, False, 'TypeError', 'ValueError']
1 Galactic 0x351593b9
1 Galactic 0x97ed8d18
1 PurestDrive 0x6697d641
1 ButterComp2 0x9bea3bd3
2 Galactic 0x72ff9c79
2 Galactic 0x4b0460d8
2 PurestDrive 0x4e488814
2 ButterComp2 0xd2c01757
"""

CASES = (
    ("Galactic", {}, {"dry_wet": 0.5}),
    ("Galactic", {"detune": 1.0, "replace": 0.2, "bigness": 0.6},
     {"brightness": 0.2}),
    ("PurestDrive", {"drive": 0.8}, {"drive": 0.1}),
    ("ButterComp2", {"compress": 0.7, "dry_wet": 0.8}, {"output": 0.8}),
)


def signal(channels):
    values = array.array("h", bytes(2 * FRAMES * channels))
    x = 12345
    for i in range(FRAMES * channels):
        x = (x * 1103515245 + 12345) & 0x7fffffff
        if i // channels < 12000:
            values[i] = ((x >> 16) & 0x3fff) - 0x2000
    return values


def fnv(h, data):
    for byte in data:
        h = ((h ^ byte) * 16777619) & 0xffffffff
    return h


def surface():
    """The parts of the node's surface both bindings must share."""
    node = aw.Galactic(sample_rate=48000, channel_count=1)
    seen = [node.playing]
    node.play(audiocore.RawSample(array.array("h", [0] * 512),
                                  sample_rate=48000, channel_count=1))
    seen.append(node.playing)
    node.stop()
    seen.append(node.playing)
    try:
        node.set(volume=1)
    except TypeError:
        seen.append("TypeError")
    node.deinit()
    try:
        node.set(replace=0.1)
    except ValueError:
        seen.append("ValueError")
    return "surface %s" % (seen,)


def main():
    lines = [surface()]
    print(lines[0])
    for channels in (1, 2):
        values = signal(channels)
        for name, options, change in CASES:
            source = audiocore.RawSample(values, channel_count=channels,
                                         sample_rate=48000)
            node = getattr(aw, name)(sample_rate=48000,
                                     channel_count=channels, **options)
            node.play(source)
            h = 2166136261
            for block in range(BLOCKS):
                if block == CHANGE_AT:
                    node.set(**change)
                h = fnv(h, bytes(audiocore.get_buffer(node)[1]))
            node.deinit()           # a stereo Galactic holds ~470 KB:
            node = source = None    # free it before the next is made
            gc.collect()
            lines.append("%d %s %s" % (channels, name, hex(h)))
            print(lines[-1])
    expected = EXPECTED_FAST if getattr(aw, "FAST", False) else EXPECTED
    if "\n".join(lines) + "\n" != expected:
        print("FAIL: output differs from EXPECTED")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
