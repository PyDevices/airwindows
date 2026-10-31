# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Copyright (c) 2026 Brad Barnett
"""Measure what each effect costs, as a share of one core.

Plays two seconds of stereo noise at 48 kHz through each effect, and then
through all three chained (PurestDrive into ButterComp2 into Galactic),
pulling 256-frame blocks, and prints the share of one core that real time
takes, twice. The first figure pulls each block from Python, as this bench
always has. Each of those pulls allocates a little, so the collector runs
every few blocks and scans the noise and Galactic's delay lines: on a board
that is up to a fifth of a core, and it moves with the heap. The second
pulls from C with audiopump.pull, as an audio output does, which allocates
nothing, so it is the effect and its binding alone. The source hands over
its whole buffer at once, so its share is negligible.

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

try:
    import audiopump
except ImportError:
    audiopump = None

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


def pull_blocks(node, native):
    """BLOCKS blocks from node, in microseconds."""
    if native:
        status = bytearray(audiopump.STATUS_BYTES)
        start = clock()
        audiopump.pull(node, BLOCKS, status)
        return since(clock(), start)
    start = clock()
    for _ in range(BLOCKS):
        audiocore.get_buffer(node)
    return since(clock(), start)


def pull(make, values, native=False):
    """The best of ROUNDS, in microseconds per block."""
    best = None
    for _ in range(ROUNDS):
        node = make(audiocore.RawSample(values, sample_rate=RATE,
                                        channel_count=2))
        took = pull_blocks(node, native)
        best = took if best is None or took < best else best
        if hasattr(node, "deinit"):
            node.deinit()
        node = None
        gc.collect()
    return best / BLOCKS


def pull_chain(values, native=False):
    """pull() for the chain: the last node's get_buffer pulls the others."""
    best = None
    for _ in range(ROUNDS):
        chain = Chain(audiocore.RawSample(values, sample_rate=RATE,
                                          channel_count=2))
        took = pull_blocks(chain.verb, native)
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
          "fixed point" if getattr(aw, "FIXED", False) else
          "fast path" if getattr(aw, "FAST", False) else "reference")
    modes = (False, True) if audiopump else (False,)
    print("%% of one core at 48 kHz stereo, pulled from Python%s" % (
        " and from C" if audiopump else ""))
    for name, make in (
            ("Galactic", through(aw.Galactic)),
            ("PurestDrive", through(aw.PurestDrive, drive=1.0)),
            ("ButterComp2", through(aw.ButterComp2, compress=1.0)),
            ("All three", None)):
        if make is None:
            costs = [pull_chain(values, native) for native in modes]
        else:
            costs = [pull(make, values, native) for native in modes]
        print("%-12s" % name + "".join(
            " %6.2f %%" % (100 * c / block_us) for c in costs))


main()
