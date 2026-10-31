# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Copyright (c) 2026 Brad Barnett
"""Which plug-ins a MicroPython build carries. micropython.mk and
micropython.cmake run it with the build's AIRWINDOWS_PLUGINS:

    python select.py selection.txt "default Pressure4 kCosmos"

Each word is a plug-in's name, a collection (Basic, Recommended, Latest),
`default` (what a board build carries unless told otherwise) or `all`;
words are separated by spaces, commas or semicolons. It prints the chosen
names, one per line, or names the word it doesn't know and exits 1.
"""

import re
import sys


def main(path, spec):
    rows = {}
    for line in open(path):
        if line.strip() and not line.startswith("#"):
            words = line.split()
            rows[words[0]] = set(words[1:])
    want = [w for w in re.split(r"[\s,;]+", spec) if w] or ["default"]
    chosen = set()
    for word in want:
        if word == "all":
            chosen |= set(rows)
            continue
        hit = {n for n, tags in rows.items() if n == word or word in tags}
        if not hit:
            sys.stderr.write("AIRWINDOWS_PLUGINS: no plug-in or collection "
                             "named %r\n" % word)
            return 1
        chosen |= hit
    print("\n".join(sorted(chosen)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], " ".join(sys.argv[2:])))
