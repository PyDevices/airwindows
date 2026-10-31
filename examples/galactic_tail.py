# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Copyright (c) 2026 Brad Barnett
"""Print how long a burst of noise rings in Galactic.

Plays a 20 ms burst into the reverb and prints the loudest sample of each
quarter second or so, so you can see the tail build, hold and die away.

Needs: audiodsp and this package, on CPython or a MicroPython built with both.
Run it: python examples/galactic_tail.py
Tested on: CPython 3.12 (Linux), MicroPython unix port
"""

from array import array

import audioairwindows
import audiocore

# Change these to match your setup.
RATE = 48000
ROWS = 12
BLOCKS_PER_ROW = 48

# Build 20 ms of noise; the reverb keeps rendering after it ends.
noise, x = array("h"), 1
for _ in range(RATE // 50):
    x = (x * 1103515245 + 12345) & 0x7fffffff
    noise.append((x >> 16) % 20001 - 10000)

# Run it through Galactic with a long tail and nothing of the dry signal.
verb = audioairwindows.Galactic(sample_rate=RATE, channel_count=1,
                                replace=0.3, dry_wet=1.0)
verb.play(audiocore.RawSample(noise, sample_rate=RATE, channel_count=1))

# Print the loudest sample of every 48 blocks of 256 frames.
for row in range(ROWS):
    loudest = 0
    for _ in range(BLOCKS_PER_ROW):
        block = array("h", bytes(audiocore.get_buffer(verb)[1]))
        loudest = max(loudest, max(abs(v) for v in block))
    print("%.2f s  %5d" % (row * BLOCKS_PER_ROW * 256 / RATE, loudest))
