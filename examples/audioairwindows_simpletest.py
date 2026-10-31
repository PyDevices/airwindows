# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Saturate a tone with PurestDrive and print what it did.

Plays a loud 440 Hz sine through PurestDrive, the gentlest of the three
effects, and prints the loudest sample going in and coming out. The output
peak is lower than the input's: the drive rounds the tops of the wave off.

Needs: audiodsp and this package, on CPython or a MicroPython built with both.

Run it:

    python examples/audioairwindows_simpletest.py

Tested on: CPython 3.12 (Linux), MicroPython 1.29 unix port.
"""

import math
from array import array

import audioairwindows
import audiocore

# Change these to match your setup.
RATE = 48000
DRIVE = 0.8  # 0 passes the tone through untouched, 1 is the most drive

# Build one second of a 440 Hz sine at about 90% of full scale.
tone = array("h", [int(30000 * math.sin(2 * math.pi * 440 * i / RATE))
                   for i in range(RATE)])

# Play it through PurestDrive.
drive = audioairwindows.PurestDrive(sample_rate=RATE, channel_count=1,
                                    drive=DRIVE)
drive.play(audiocore.RawSample(tone, sample_rate=RATE, channel_count=1))

# Pull ten blocks and keep the loudest output sample.
loudest = 0
for _ in range(10):
    block = array("h", bytes(audiocore.get_buffer(drive)[1]))
    loudest = max(loudest, max(abs(v) for v in block))

print("audioairwindows", audioairwindows.__version__,
      audioairwindows.__revision__)
print("peak in: ", max(abs(v) for v in tone))
print("peak out:", loudest)
