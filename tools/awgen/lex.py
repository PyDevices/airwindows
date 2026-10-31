# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Copyright (c) 2026 Brad Barnett
"""A tokenizer for the C++ subset Airwindows plug-ins are written in.

Every character of the source lands in exactly one token, comments and
whitespace included, so joining the tokens gives the source back and a
translation that swaps a few tokens keeps upstream's layout and comments.
"""

import re
from dataclasses import dataclass

_PATTERNS = [
    ("ws", r"[ \t\r\n]+"),
    ("comment", r"//[^\n]*|/\*.*?\*/"),
    ("pp", r"#[^\n]*"),
    ("string", r'"(?:\\.|[^"\\])*"'),
    ("char", r"'(?:\\.|[^'\\])*'"),
    ("number", r"(?:0[xX][0-9a-fA-F]+[uUlL]*"
               r"|(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?[fFlLuU]*)"),
    ("ident", r"[A-Za-z_][A-Za-z_0-9]*"),
    ("op", r"->|\+\+|--|<<=|>>=|<<|>>|<=|>=|==|!=|&&|\|\||\+=|-=|\*=|/=|%="
           r"|&=|\|=|\^=|::|[-+*/%<>=!&|^~?:;,.(){}\[\]]"),
]
_RE = re.compile("|".join("(?P<%s>%s)" % p for p in _PATTERNS), re.S)


@dataclass
class Tok:
    kind: str
    text: str

    def is_(self, text):
        return self.text == text

    def __repr__(self):
        return "%s:%r" % (self.kind, self.text)


def lex(source):
    out = []
    pos = 0
    while pos < len(source):
        m = _RE.match(source, pos)
        if m is None:
            raise SyntaxError("cannot tokenize at %r" % source[pos:pos + 40])
        out.append(Tok(m.lastgroup, m.group()))
        pos = m.end()
    return out


def join(tokens):
    return "".join(t.text for t in tokens)


def code(tokens):
    """The tokens that are code: no whitespace or comments."""
    return [t for t in tokens if t.kind not in ("ws", "comment")]


def next_code(tokens, i):
    """Index of the first code token at or after i, or len(tokens)."""
    while i < len(tokens) and tokens[i].kind in ("ws", "comment"):
        i += 1
    return i


def prev_code(tokens, i):
    """Index of the last code token at or before i, or -1."""
    while i >= 0 and tokens[i].kind in ("ws", "comment"):
        i -= 1
    return i


def match(tokens, i):
    """Index of the bracket that closes the one at i."""
    opening = tokens[i].text
    closing = {"(": ")", "[": "]", "{": "}"}[opening]
    depth = 0
    for j in range(i, len(tokens)):
        t = tokens[j].text
        if tokens[j].kind != "op":
            continue
        if t == opening:
            depth += 1
        elif t == closing:
            depth -= 1
            if depth == 0:
                return j
    raise SyntaxError("unbalanced %s" % opening)


def find(tokens, text, start=0, kind=None):
    for j in range(start, len(tokens)):
        if tokens[j].text == text and (kind is None or tokens[j].kind == kind):
            return j
    return -1
