# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""One deliberate type error, which mypy must report: a check that only passes proves nothing."""

import audioairwindows

audioairwindows.PurestDrive(sample_rate=48000, channel_count=1, drive="loud")
