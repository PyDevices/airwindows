# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Copyright (c) 2026 Brad Barnett
"""The description of one plug-in, which every emitter reads.

parse.py fills it from upstream's three files; translate.py turns its
constructor and loop into C; the emitters write the kernel, the bindings,
the stub and the docs from it. Nothing downstream reads upstream again.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Param:
    index: int
    enum: str
    member: Optional[str]
    name: str            # upstream's display name, e.g. "Dry/Wet"
    label: str           # upstream's unit, e.g. "dB"
    display: str         # upstream's getParameterDisplay case, as source
    default: float = 0.0
    py: str = ""         # the Python keyword, e.g. "dry_wet"


@dataclass
class Member:
    name: str
    ctype: str
    dims: List[str]
    init: Optional[str] = None


@dataclass
class Plugin:
    name: str
    params: List[Param] = field(default_factory=list)
    members: List[Member] = field(default_factory=list)
    prelude: List[str] = field(default_factory=list)
    consts: List[str] = field(default_factory=list)
    class_enums: List[str] = field(default_factory=list)
    inputs: int = 2
    outputs: int = 2
    ctor: list = field(default_factory=list)
    proc: list = field(default_factory=list)
    proc_functions: int = 0
    flags: List[str] = field(default_factory=list)
    # Filled by later stages.
    statics: List[Member] = field(default_factory=list)
    seeds: List[str] = field(default_factory=list)
    summary: str = ""
    collections: List[str] = field(default_factory=list)
    category: str = ""
    # From tools/awgen/policy.json: members the fast variant keeps double.
    wide: List[str] = field(default_factory=list)
    phase: List[str] = field(default_factory=list)
    fast_as_ref: bool = False
