# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Copyright (c) 2026 Brad Barnett
"""Measure what each effect costs, as a share of one core.

Plays two seconds of stereo noise at 48 kHz through each effect, and then
through all three chained (PurestDrive into ButterComp2 into Galactic),
pulling 256-frame blocks the way an audio output does, and prints the time
per block and the share of one core that real time takes. The source hands over its
whole buffer at once, so the figure is the effect and its binding, with the
source's share negligible.

Run it with CPython or MicroPython, on a desktop or a board:

    python tools/bench.py
    mpremote run tools/bench.py

Galactic needs about 1 MB on a desktop besides the 384 kB of noise, so give
the unix port a bigger heap: micropython -X heapsize=8M tools/bench.py
"""

import array
import gc
import time

import audioairwindows as aw
import audiocore

RATE = 48000
SECONDS = 2
BLOCKS = RATE * SECONDS // 256
ROUNDS = 3

try:
    clock, since = time.ticks_us, time.ticks_diff
except AttributeError:
    def clock():
        return time.perf_counter_ns() // 1000

    def since(end, start):
        return end - start


def noise():
    values = array.array("h", bytes(4 * RATE * SECONDS))
    x = 1
    for i in range(len(values)):
        x = (x * 1103515245 + 12345) & 0x7fffffff
        values[i] = ((x >> 16) & 0x3fff) - 0x2000
    return values


def pull(make, values):
    """The best of ROUNDS, in microseconds per block."""
    best = None
    for _ in range(ROUNDS):
        node = make(audiocore.RawSample(values, sample_rate=RATE,
                                        channel_count=2))
        start = clock()
        for _ in range(BLOCKS):
            audiocore.get_buffer(node)
        took = since(clock(), start)
        best = took if best is None or took < best else best
        if hasattr(node, "deinit"):
            node.deinit()
        node = None
        gc.collect()
    return best / BLOCKS


def pull_chain(values):
    """pull() for the chain: the last node's get_buffer pulls the others."""
    best = None
    for _ in range(ROUNDS):
        chain = Chain(audiocore.RawSample(values, sample_rate=RATE,
                                          channel_count=2))
        start = clock()
        for _ in range(BLOCKS):
            audiocore.get_buffer(chain.verb)
        took = since(clock(), start)
        best = took if best is None or took < best else best
        chain.deinit()
        chain = None
        gc.collect()
    return best / BLOCKS


def through(kind, **options):
    def make(source):
        node = kind(sample_rate=RATE, channel_count=2, **options)
        node.play(source)
        return node
    return make


class Chain:
    """PurestDrive into ButterComp2 into Galactic, pulled from the last."""

    def __init__(self, source):
        self.drive = aw.PurestDrive(sample_rate=RATE, channel_count=2,
                                    drive=1.0)
        self.comp = aw.ButterComp2(sample_rate=RATE, channel_count=2,
                                   compress=1.0)
        self.verb = aw.Galactic(sample_rate=RATE, channel_count=2)
        self.drive.play(source)
        self.comp.play(self.drive)
        self.verb.play(self.comp)

    def deinit(self):
        for node in (self.verb, self.comp, self.drive):
            if hasattr(node, "deinit"):
                node.deinit()


def main():
    values = noise()
    block_us = 256 * 1000000 / RATE
    print("audioairwindows", aw.__version__, getattr(aw, "__revision__", "?"),
          "fast path" if getattr(aw, "FAST", False) else "reference")
    for name, make in (
            ("Galactic", through(aw.Galactic)),
            ("PurestDrive", through(aw.PurestDrive, drive=1.0)),
            ("ButterComp2", through(aw.ButterComp2, compress=1.0)),
            ("All three", None)):
        if make is None:
            cost = pull_chain(values)
        else:
            cost = pull(make, values)
        print("%-12s %7.1f us per block, %5.2f %% of one core at 48 kHz stereo"
              % (name, cost, 100 * cost / block_us))


main()
