# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""What a user writes against the stubs: mypy must accept it."""

import audioairwindows
import audiocore

source = audiocore.RawSample(bytearray(960), channel_count=1, sample_rate=48000)
drive = audioairwindows.PurestDrive(sample_rate=48000, channel_count=1, drive=0.8)
drive.play(source)
playing: bool = drive.playing
