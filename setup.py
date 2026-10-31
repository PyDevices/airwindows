# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Copyright (c) 2026 Brad Barnett
import os
import subprocess
import sys
from pathlib import Path

from setuptools import Extension, setup

VERSION = Path(__file__).parent.joinpath("VERSION").read_text().strip()

# The commit this build comes from, for __revision__; the board builds work
# it out the same way in micropython.mk and micropython.cmake.
try:
    REVISION = subprocess.run(
        ["git", "-C", str(Path(__file__).parent), "describe", "--tags",
         "--match", "v[0-9]*", "--always", "--dirty", "--abbrev=7"],
        capture_output=True, text=True, check=True).stdout.strip() or "unknown"
except (OSError, subprocess.CalledProcessError):
    REVISION = "unknown"

# The kernel turns off multiply-add contraction with a pragma; clang on macOS
# gets the flag as well, so every build renders the same bytes.
EXTRA = ["-ffp-contract=off"] if sys.platform == "darwin" else []
# MSVC takes _Generic (kernel_common.h's aw_abs) only in its C11 mode, and
# keeps multiply-add contraction off unless asked.
if sys.platform == "win32":
    EXTRA = ["/std:c11", "/fp:contract-"]

# AW_FAST_DEFAULT=1 builds the extension with the fast path on by default, as
# ESP32-S3 firmware is, so a desktop can render what the S3 renders.
FAST = os.environ.get("AW_FAST_DEFAULT", "0").strip() or "0"

# AW_TUNED=1 runs that fast path with the kernels written by hand for the
# S3, as its firmware does, so a desktop renders the S3's bytes
# (airwindows/plugin.h).
TUNED = [("AW_TUNED", os.environ["AW_TUNED"].strip())] \
    if os.environ.get("AW_TUNED", "").strip() else []

# Every plug-in the generator carries (src/airwindows/selection.txt).
PLUGINS = ["src/airwindows/plugins/%s.c" % line.split()[0] for line in
           Path(__file__).parent.joinpath(
               "src", "airwindows", "selection.txt").read_text().splitlines()
           if line.strip() and not line.startswith("#")]

setup(
    # Five hundred kernels compile in a fraction of the time in parallel.
    options={"build_ext": {"parallel": os.cpu_count() or 1}},
    ext_modules=[
        Extension(
            "_audioairwindows",
            # Every plug-in, both variants: the wheel carries them all.
            sources=["src/cpython/_audioairwindows.c",
                     "src/airwindows/registry.c"] + PLUGINS,
            include_dirs=["src"],
            define_macros=[("AW_WITH_ALL", "1"),
                           ("AW_VERSION", '"%s"' % VERSION),
                           ("AW_REVISION", '"%s"' % REVISION),
                           ("AW_FAST_DEFAULT", FAST)] + TUNED,
            extra_compile_args=EXTRA,
        ),
    ],
)
