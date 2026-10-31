# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Copyright (c) 2026 Brad Barnett
"""Reads one upstream plug-in into a description.

An Airwindows plug-in is three files under plugins/LinuxVST/src/<Name>/:
<Name>.h declares the class (its parameters and its state as members),
<Name>.cpp has the constructor (defaults and initial state) and the
parameter names, and <Name>Proc.cpp has processReplacing, the float loop.
Every one of the 529 follows that shape, so this reads them with a tokenizer
and a few patterns rather than a C++ parser.
"""

import re
from pathlib import Path

from .ir import Member, Param, Plugin
from .lex import code, find, join, lex, match, next_code

# Members every plug-in has that are the VST host's business, not the DSP's.
_HOST_MEMBERS = {"_programName", "_canDo"}

_TYPES = {"double", "float", "int", "bool", "uint32_t", "int32_t", "long",
          "unsigned", "signed", "short", "char", "VstInt32", "uint64_t",
          "int64_t", "uint16_t", "int16_t", "uint8_t", "int8_t", "size_t",
          "const", "static"}


def _strip_comments(tokens):
    return [t for t in tokens if t.kind != "comment"]


def _statements(tokens):
    """Splits code tokens at top-level semicolons. Braces nest."""
    out, cur, depth = [], [], 0
    for t in tokens:
        if t.kind == "op" and t.text in "({[":
            depth += 1
        elif t.kind == "op" and t.text in ")}]":
            depth -= 1
        if t.kind == "op" and t.text == ";" and depth == 0:
            out.append(cur)
            cur = []
        else:
            cur.append(t)
    if any(t.kind not in ("ws", "comment") for t in cur):
        out.append(cur)
    return out


def _class_body(tokens, name):
    i = 0
    while True:
        i = find(tokens, "class", i)
        if i < 0:
            raise SyntaxError("no class %s" % name)
        j = next_code(tokens, i + 1)
        if tokens[j].text == name:
            break
        i += 1
    brace = find(tokens, "{", j)
    end = match(tokens, brace)
    return brace, end


def _enum_constants(tokens):
    """Names and values of an `enum { a, b = 3, ... }` token run."""
    brace = find(tokens, "{")
    end = match(tokens, brace)
    items = []
    cur = []
    for t in code(tokens[brace + 1:end]):
        if t.text == ",":
            items.append(cur)
            cur = []
        else:
            cur.append(t)
    if cur:
        items.append(cur)
    out = []
    value = -1
    for item in items:
        if not item:
            continue
        name = item[0].text
        if len(item) > 2 and item[1].text == "=":
            expr = join(item[2:]).strip()
            try:
                value = int(eval(expr, {}, {}))
            except Exception:
                value = None
        else:
            value = None if value is None else value + 1
        out.append((name, value))
    return out


def _declarations(stmt, consts):
    """Members declared by one statement: `double a, b[3][4], c = 1.0`."""
    toks = code(stmt)
    if not toks:
        return []
    k = 0
    type_words = []
    while k < len(toks) and (toks[k].text in _TYPES or (
            toks[k].kind == "ident" and k == 0)):
        type_words.append(toks[k].text)
        k += 1
        if type_words[-1] not in ("unsigned", "signed", "long", "short",
                                  "const", "static"):
            break
    if not type_words:
        return []
    ctype = " ".join(type_words)
    members = []
    while k < len(toks):
        if toks[k].text == "*":
            raise SyntaxError("pointer member in %s" % join(stmt))
        name = toks[k].text
        k += 1
        dims = []
        while k < len(toks) and toks[k].text == "[":
            j = k
            depth = 0
            while True:
                if toks[j].text == "[":
                    depth += 1
                elif toks[j].text == "]":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            dims.append(join_spaced(toks[k + 1:j]))
            k = j + 1
        init = None
        if k < len(toks) and toks[k].text == "=":
            j = k + 1
            depth = 0
            while j < len(toks) and not (toks[j].text == "," and depth == 0):
                if toks[j].text in "({[":
                    depth += 1
                elif toks[j].text in ")}]":
                    depth -= 1
                j += 1
            init = join_spaced(toks[k + 1:j])
            k = j
        members.append(Member(name=name, ctype=ctype, dims=dims, init=init))
        if k < len(toks) and toks[k].text == ",":
            k += 1
    return members


def join_spaced(toks):
    return " ".join(t.text for t in toks)


def _function_body(tokens, qualified):
    """Tokens inside the braces of `Class::method(...) {`, or None."""
    owner, method = qualified.split("::")
    i = 0
    while True:
        i = find(tokens, owner, i)
        if i < 0:
            return None
        j = next_code(tokens, i + 1)
        if j < len(tokens) and tokens[j].text == "::":
            k = next_code(tokens, j + 1)
            if k < len(tokens) and tokens[k].text == method:
                p = next_code(tokens, k + 1)
                if p < len(tokens) and tokens[p].text == "(":
                    close = match(tokens, p)
                    brace = find(tokens, "{", close)
                    return tokens[brace + 1:match(tokens, brace)]
        i += 1


def _after_index_switch(body):
    """setParameter's statements after its `switch (index) {...}`."""
    i = 0
    while True:
        i = find(body, "switch", i)
        if i < 0:
            return []
        p = next_code(body, i + 1)
        if p < len(body) and body[p].text == "(":
            close = match(body, p)
            if [t.text for t in code(body[p + 1:close])] == ["index"]:
                brace = find(body, "{", close)
                return body[match(body, brace) + 1:]
        i += 1


def _cases(body):
    """`case kParamX: <stmts> break;` runs of a switch, as {label: tokens}."""
    out = {}
    toks = body
    i = 0
    while True:
        i = find(toks, "case", i)
        if i < 0:
            break
        colon = find(toks, ":", i)
        label = join(code(toks[i + 1:colon])).strip()
        j = colon + 1
        depth = 0
        while j < len(toks):
            t = toks[j]
            if t.text in ("{", "("):
                depth += 1
            elif t.text in ("}", ")"):
                depth -= 1
            if depth == 0 and t.text in ("case", "default"):
                break
            if depth < 0:
                break
            j += 1
        out[label] = toks[colon + 1:j]
        i = j
    return out


def preprocess(tokens, defines):
    """Drops what an #ifdef/#ifndef leaves out. Upstream's headers use them
    only for include guards and the matrix sizes of the k-reverbs
    (`#define SIXBYSIX true` ... `#ifdef SIXBYSIX`). Adds to `defines`."""
    out = []
    stack = []
    for t in tokens:
        if t.kind == "pp":
            words = t.text.lstrip("#").split()
            head = t.text.split()[0] if t.text.split() else ""
            directive = words[0] if words else ""
            if head != "#" + directive:
                directive = head.lstrip("#")
            name = words[1] if len(words) > 1 else ""
            active = all(stack)
            if directive == "ifdef":
                stack.append(name in defines)
                continue
            if directive == "ifndef":
                stack.append(name not in defines)
                continue
            if directive == "else":
                stack[-1] = not stack[-1]
                continue
            if directive == "endif":
                stack.pop()
                continue
            if directive in ("if", "elif"):
                raise SyntaxError("#%s is not handled" % directive)
            if active and directive == "define" and name:
                defines.add(name)
        if all(stack):
            out.append(t)
    return out


_STRING = re.compile(r'"((?:\\.|[^"\\])*)"')


def parse_plugin(src_dir, name):
    d = Path(src_dir) / name
    h_src = (d / (name + ".h")).read_text(errors="replace")
    c_src = (d / (name + ".cpp")).read_text(errors="replace")
    p_src = (d / (name + "Proc.cpp")).read_text(errors="replace")
    defines = set()
    h = preprocess(lex(h_src), defines)
    c = preprocess(lex(c_src), set(defines))
    proc = preprocess(lex(p_src), set(defines))

    plugin = Plugin(name=name)

    # File scope of the header, before the class: the parameter enum, consts
    # and macros.
    cls_brace, cls_end = _class_body(h, name)
    pre = h[:cls_brace]
    param_enum = []
    for t in pre:
        if t.kind == "pp" and t.text.startswith("#define"):
            words = t.text.split()
            if len(words) >= 2 and not words[1].startswith("__"):
                plugin.prelude.append(t.text.strip())
    i = 0
    while True:
        i = find(pre, "enum", i)
        if i < 0:
            break
        brace = find(pre, "{", i)
        end = match(pre, brace)
        consts = _enum_constants(pre[i:end + 1])
        if any(n == "kNumParameters" for n, _ in consts):
            param_enum = [n for n, _ in consts if n != "kNumParameters"]
        else:
            plugin.prelude.append(join(pre[i:end + 1]) + ";")
        i = end
    for stmt in _statements(_strip_comments(pre)):
        toks = [t for t in code(stmt) if t.kind != "pp"]
        if toks and toks[0].text == "static" and \
                "=" in [t.text for t in toks]:
            # A table: `static int primeL[] = {...}`.
            plugin.consts.append(join_spaced(toks))
            continue
        if toks and toks[0].text == "const" and "=" in [t.text for t in toks]:
            name_tok = toks[toks.index(next(t for t in toks if t.text == "=")) - 1]
            if name_tok.text in ("kNumPrograms", "kNumInputs", "kNumOutputs",
                                 "kUniqueId"):
                if name_tok.text == "kNumInputs":
                    plugin.inputs = int(toks[-1].text)
                if name_tok.text == "kNumOutputs":
                    plugin.outputs = int(toks[-1].text)
                continue
            plugin.consts.append(join_spaced(toks))

    # The class: members after `private:` (and any public data members).
    body = h[cls_brace + 1:cls_end]
    for stmt in _statements(_strip_comments(body)):
        toks = code(stmt)
        if not toks:
            continue
        # Drop access labels glued to the front of the statement.
        while len(toks) >= 2 and toks[0].text in ("public", "private",
                                                  "protected") \
                and toks[1].text == ":":
            toks = toks[2:]
        if not toks:
            continue
        words = [t.text for t in toks]
        if "virtual" in words or "(" in words:
            continue
        if words[0] == "enum":
            plugin.class_enums.append(join_spaced(toks) + ";")
            continue
        if words[0] == "std" or words[0] == "char" and "_programName" in words:
            continue
        if "static" in words and "=" in words:
            # A class constant: `static const int kA = 0;`.
            plugin.consts.append(join_spaced(toks))
            continue
        for m in _declarations(toks, plugin.consts):
            if m.name in _HOST_MEMBERS:
                continue
            plugin.members.append(m)

    # Parameters: index -> member from setParameter, name from
    # getParameterName, unit from getParameterLabel.
    setp = _function_body(c, name + "::setParameter")
    getn = _function_body(c, name + "::getParameterName")
    getl = _function_body(c, name + "::getParameterLabel")
    getd = _function_body(c, name + "::getParameterDisplay")
    sets = _cases(setp) if setp else {}
    names = _cases(getn) if getn else {}
    labels = _cases(getl) if getl else {}
    displays = _cases(getd) if getd else {}
    for index, enum_name in enumerate(param_enum):
        stmts = code(sets.get(enum_name, []))
        member = None
        extra = []
        texts = [t.text for t in stmts]
        if len(texts) >= 4 and texts[1] == "=" and texts[2] == "value":
            member = texts[0]
            extra = texts[4:]
        if extra and extra != ["break", ";"]:
            plugin.flags.append("setParameter for %s does more than store"
                                % enum_name)
        label_text = join(labels.get(enum_name, []))
        m = _STRING.search(join(names.get(enum_name, [])))
        lm = _STRING.search(label_text)
        plugin.params.append(Param(
            index=index, enum=enum_name, member=member,
            name=m.group(1) if m else enum_name,
            label=lm.group(1) if lm else "",
            display=join(displays.get(enum_name, [])).strip()))

    ctor = _function_body(c, name + "::" + name)
    if ctor is None:
        raise SyntaxError("no constructor")
    plugin.ctor = ctor
    plugin.proc = _function_body(proc, name + "::processReplacing")
    if plugin.proc is None:
        raise SyntaxError("no processReplacing")
    # What setParameter does after storing the value depends only on the
    # knobs, which change only between blocks here, so it runs at the top of
    # every block instead (Channel4 to Channel9 pick a console that way).
    hook = _after_index_switch(setp) if setp else []
    if any(t.kind not in ("ws", "comment") for t in hook):
        plugin.proc = hook + lex("\n") + plugin.proc
    # The Proc file may define helpers besides the two process methods.
    tops = [t.text for t in code(proc)]
    plugin.proc_functions = sum(1 for k in range(len(tops) - 2)
                                if tops[k] == name and tops[k + 1] == "::")
    return plugin
