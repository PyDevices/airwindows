# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Copyright (c) 2026 Brad Barnett
"""Completes a parsed plug-in's description: Python names for its
parameters, their defaults, its one-line summary and upstream's
collections, and whether it fits the template (and if not, why)."""

import keyword
import re

from .lex import code

RESERVED = {"sample_rate", "channel_count", "set", "clear", "play", "stop",
            "deinit", "playing"}

KEYWORDS = {"if", "while", "for", "switch", "return", "sizeof", "case",
            "else", "do", "break", "continue", "default"}


def py_name(display, taken):
    s = display.strip()
    s = s.replace("/", "_").replace("&", "and").replace("+", "plus")
    s = s.replace("#", "num").replace("%", "pct")
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower()
    if not s:
        s = "param"
    if s[0].isdigit():
        s = "p" + s
    if keyword.iskeyword(s) or s in RESERVED:
        s += "_"
    base = s
    k = 2
    while s in taken:
        s = "%s_%d" % (base, k)
        k += 1
    taken.add(s)
    return s


def _number(text):
    try:
        return float(eval(text.replace("f", "") if re.fullmatch(
            r"[0-9.eE+\-*/ ()f]+", text) else "None", {}, {}))
    except Exception:
        return None


def defaults(plugin):
    """Each parameter's default: the constructor's top-level `A = 0.5;`."""
    toks = code(plugin.ctor)
    depth = 0
    found = {}
    members = {p.member for p in plugin.params}
    for k, t in enumerate(toks):
        if t.text == "{":
            depth += 1
        elif t.text == "}":
            depth -= 1
        elif depth == 0 and t.kind == "ident" and t.text in members and \
                k + 1 < len(toks) and toks[k + 1].text == "=" and \
                t.text not in found:
            e = k + 2
            while e < len(toks) and toks[e].text != ";":
                e += 1
            found[t.text] = _number(" ".join(x.text for x in toks[k + 2:e]))
    return found


def complete(plugin, what_line=None):
    taken = set()
    found = defaults(plugin)
    for p in plugin.params:
        p.py = py_name(p.name, taken)
        value = found.get(p.member)
        if value is None:
            plugin.flags.append("no default for %s" % p.enum)
            value = 0.0
        p.default = min(1.0, max(0.0, value))
        if value != p.default:
            plugin.flags.append("default for %s outside 0..1" % p.enum)
    if what_line:
        m = re.match(r"^(\S+) (.*?)\s*\[coll=([^\]]*)\]\s*$", what_line)
        if m:
            plugin.summary = m.group(2)
            plugin.collections = [c.strip() for c in m.group(3).split(",")
                                  if c.strip()]


def read_what(path):
    """{name: line} from upstream's what.txt."""
    out = {}
    for line in open(path, encoding="utf-8", errors="replace"):
        name = line.split(" ", 1)[0]
        if "[coll=" in line:
            out[name] = line.rstrip("\n")
    return out


def read_categories(path):
    """{name: category} from Airwindopedia's category list."""
    out = {}
    text = open(path, encoding="utf-8", errors="replace").read()
    start = text.find("# Categories")
    if start < 0:
        return out
    for line in text[start:].splitlines()[1:]:
        if line.startswith("#"):
            break
        if ":" not in line:
            continue
        cat, names = line.split(":", 1)
        for n in names.split(","):
            n = n.strip()
            if n and n not in out:
                out[n] = cat.strip()
    return out
