# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Copyright (c) 2026 Brad Barnett
"""Turns a plug-in's constructor and float loop into C.

The loop is upstream's own text with a few tokens swapped, so the generated
kernel reads line for line against <Name>Proc.cpp. What changes, in every
plug-in alike:

  * Members become locals. Each member the body uses is loaded into a local
    of the same name when the call starts and stored back when it ends, so
    the body compiles unchanged and the compiler keeps the state in
    registers. Arrays become pointers into the state.
  * The host plumbing goes: the in/out pointer setup, the pointer
    increments, getSampleRate(). Samples come in and go out as int16.
  * Upstream's 32-bit float output dither goes. The output here is int16;
    the xorshift steps that drive it stay, because many plug-ins read the
    same generators for their own noise.
  * C++ that C spells differently: functional casts, abs() on doubles,
    function-local statics (which become per-node state), rand().

The fast variant, for parts whose FPU has no double and no divide (every
ESP32), also: single precision throughout, float literals, a polynomial sine
and a floor without a call, small integer powers as multiplies, and no
divide in the loop where it can be helped (a reciprocal worked out before
the loop when the divisor doesn't change in it, Newton's otherwise).
"""

import re

from .lex import Tok, code, join, lex, match, next_code, prev_code

TYPE_WORDS = {"double", "float", "int", "bool", "uint32_t", "int32_t",
              "long", "unsigned", "signed", "short", "char", "VstInt32",
              "uint64_t", "int64_t", "uint16_t", "int16_t", "uint8_t",
              "int8_t", "size_t", "const", "static"}
CAST_TYPES = {"double", "float", "int", "bool", "uint32_t", "int32_t",
              "long", "unsigned", "VstInt32", "uint64_t", "int64_t",
              "uint16_t", "int16_t", "uint8_t", "int8_t", "short", "char"}
FLOAT_TYPES = {"double", "float", "long double"}

HOST_CALLS = {"_canDo", "setNumInputs", "setNumOutputs", "setUniqueID",
              "canProcessReplacing", "canDoubleReplacing",
              "programsAreChunks", "vst_strncpy", "_programName"}

# libm in the fast variant. sin/cos/floor get our own; the rest use the
# float versions. Anything not listed is refused by the classifier.
FAST_MATH = {
    "sin": "aw_sinf", "cos": "aw_cosf", "floor": "aw_floorf",
    "fabs": "fabsf", "sqrt": "sqrtf", "pow": "powf", "exp": "expf",
    "log": "logf", "log10": "log10f", "tan": "tanf", "asin": "asinf",
    "acos": "acosf", "atan": "atanf", "atan2": "atan2f", "sinh": "sinhf",
    "cosh": "coshf", "tanh": "tanhf", "cbrt": "cbrtf", "fmin": "fminf",
    "fmax": "fmaxf", "fmod": "fmodf", "ceil": "aw_ceilf", "exp2": "exp2f",
    "log2": "log2f", "round": "roundf", "copysign": "copysignf",
    "asinh": "asinhf", "acosh": "acoshf", "atanh": "atanhf",
    "hypot": "hypotf", "trunc": "truncf", "fabsf": "fabsf",
    "sinf": "aw_sinf", "cosf": "aw_cosf", "sqrtf": "sqrtf",
    "floorf": "aw_floorf", "powf": "powf", "expf": "expf", "logf": "logf",
}
REF_MATH = {"sin", "cos", "floor", "fabs", "sqrt", "pow", "exp", "log",
            "log10", "tan", "asin", "acos", "atan", "atan2", "sinh", "cosh",
            "tanh", "cbrt", "fmin", "fmax", "fmod", "ceil", "exp2", "log2",
            "round", "copysign", "asinh", "acosh", "atanh", "hypot",
            "trunc", "fabsf", "sinf", "cosf", "sqrtf", "floorf", "powf",
            "expf", "logf"}
FLOAT_FUNCS = set(FAST_MATH) | set(FAST_MATH.values()) | {"aw_abs",
                                                           "aw_recipf"}

_FLOAT_LIT = re.compile(r"^(?:\d+\.\d*|\.\d+|\d+[eE][+-]?\d+|\d+\.\d*[eE][+-]?"
                        r"\d+|\.\d+[eE][+-]?\d+)[fFlL]?$")


class TranslateError(Exception):
    pass


def T(kind, text):
    return Tok(kind, text)


def _toks(text):
    return lex(text)


def is_float_literal(tok):
    return tok.kind == "number" and bool(_FLOAT_LIT.match(tok.text)) \
        and not tok.text.lower().startswith("0x")


# --- statements -------------------------------------------------------------

def stmt_extent(tokens, i):
    """(start, end) of the simple statement holding token i; end is its ';'.

    A leading `case X:` or `default:` label is left out of it."""
    depth = 0
    s = i
    while s > 0:
        t = tokens[s - 1]
        if t.kind == "op":
            # Starting inside brackets, the statement runs out past them.
            if t.text in ")]":
                depth += 1
            elif t.text in "([":
                depth -= 1
            elif depth <= 0 and t.text in (";", "{", "}"):
                break
        s -= 1
    depth = 0
    e = i
    while e < len(tokens):
        t = tokens[e]
        if t.kind == "op":
            if t.text in "([":
                depth += 1
            elif t.text in ")]":
                depth -= 1
            elif t.text == ";" and depth <= 0:
                break
        e += 1
    # Skip a case/default label at the front.
    c = next_code(tokens, s)
    if c < len(tokens) and tokens[c].text in ("case", "default"):
        k = c
        while k < e and not (tokens[k].text == ":"):
            k += 1
        s = k + 1
    # Skip `if (...)`/`else` heads? No: a statement under an if is removed
    # with its if, which only happens for the dither, whose ifs hold nothing
    # else.
    return s, e


def remove_statements(tokens, predicate):
    """Drops every simple statement whose code tokens satisfy predicate."""
    spans = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t.kind not in ("ws", "comment", "pp") and predicate(tokens, i):
            s, e = stmt_extent(tokens, i)
            spans.append((s, e))
            i = e + 1
        else:
            i += 1
    if not spans:
        return tokens, []
    out = []
    last = 0
    removed = []
    for s, e in spans:
        if s < last:
            continue
        out.extend(tokens[last:s])
        removed.append(tokens[s:e + 1])
        last = e + 1
    out.extend(tokens[last:])
    return out, removed


# --- declarations -------------------------------------------------------------

def declared_locals(tokens):
    """{name: type} for the variables a body declares, at any depth."""
    out = {}
    starts = {";", "{", "}", "(", ")"}
    i = 0
    n = len(tokens)
    while i < n:
        t = tokens[i]
        if t.kind == "ident" and t.text in TYPE_WORDS:
            p = prev_code(tokens, i - 1)
            if p >= 0 and tokens[p].text not in starts and \
                    tokens[p].text not in TYPE_WORDS and \
                    tokens[p].text != ":":
                i += 1
                continue
            if p >= 0 and tokens[p].text == ")":
                # A cast, not a declaration: `(int) x`. Declarations follow
                # `)` only after `for (...)` / `if (...)` heads, rare enough.
                i += 1
                continue
            words = []
            j = i
            while j < n and (tokens[j].kind in ("ws", "comment") or
                             tokens[j].text in TYPE_WORDS):
                if tokens[j].text in TYPE_WORDS:
                    words.append(tokens[j].text)
                j += 1
            ctype = " ".join(w for w in words if w not in ("const", "static"))
            depth = 0
            expect_name = True
            while j < n:
                tj = tokens[j]
                if tj.kind in ("ws", "comment"):
                    j += 1
                    continue
                if tj.text in "([{":
                    depth += 1
                elif tj.text in ")]}":
                    if depth == 0:
                        break
                    depth -= 1
                elif depth == 0 and tj.text == ";":
                    break
                elif depth == 0 and tj.text == ",":
                    expect_name = True
                elif expect_name and tj.kind == "ident" and depth == 0:
                    out.setdefault(tj.text, ctype)
                    expect_name = False
                elif expect_name and tj.text == "*":
                    pass
                else:
                    expect_name = False if tj.text != "*" else expect_name
                j += 1
            i = j
            continue
        i += 1
    return out


def identifiers(tokens):
    return {t.text for t in tokens if t.kind == "ident"}


# --- token rewrites -----------------------------------------------------------

def _unary_position(tokens, i):
    """Whether the operator at i is unary (no operand before it)."""
    p = prev_code(tokens, i - 1)
    if p < 0:
        return True
    t = tokens[p]
    if t.kind in ("ident", "number") and t.text not in ("return", "case"):
        return False
    if t.text in (")", "]"):
        return False
    return True


def io_names(tokens):
    """The host's pointer names, from `float* in1 = inputs[0];`."""
    names = {}
    cs = code(tokens)
    for k, t in enumerate(cs):
        if t.text in ("inputs", "outputs") and k + 3 < len(cs) and \
                cs[k + 1].text == "[" and cs[k - 1].text == "=":
            side = "L" if cs[k + 2].text == "0" else "R"
            kind = "in" if t.text == "inputs" else "out"
            names[cs[k - 2].text] = "aw_%s%s" % (kind, side)
    return names or {"in1": "aw_inL", "in2": "aw_inR",
                     "out1": "aw_outL", "out2": "aw_outR"}


def rewrite_io(tokens, issues, names):
    """`*in1` -> aw_inL, `*out1 = x` -> aw_outL = x."""
    out = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t.kind == "op" and t.text == "*" and _unary_position(tokens, i):
            j = next_code(tokens, i + 1)
            if j < len(tokens) and tokens[j].text in names:
                out.append(T("ident", names[tokens[j].text]))
                i = j + 1
                continue
        if t.kind == "ident" and t.text in names:
            issues.append("uses %s other than as *%s" % (t.text, t.text))
        out.append(t)
        i += 1
    return out


def rewrite_casts(tokens):
    """C++ functional casts, `double(x)`, become C casts."""
    out = []
    i = 0
    n = len(tokens)
    while i < n:
        t = tokens[i]
        if t.kind == "ident" and t.text in CAST_TYPES:
            j = next_code(tokens, i + 1)
            p = prev_code(tokens, i - 1)
            prev = tokens[p].text if p >= 0 else ""
            if j < n and tokens[j].text == "(" and prev not in TYPE_WORDS \
                    and not (p >= 0 and tokens[p].kind == "ident"
                             and prev not in ("return", "case")):
                close = match(tokens, j)
                inner = rewrite_casts(tokens[j + 1:close])
                out.extend([T("op", "("), T("op", "("), t, T("op", ")"),
                            T("op", "(")] + inner + [T("op", ")"),
                                                     T("op", ")")])
                i = close + 1
                continue
        out.append(t)
        i += 1
    return out


def rewrite_idents(tokens, mapping):
    out = []
    for t in tokens:
        if t.kind == "ident" and t.text in mapping:
            out.extend(mapping[t.text])
        else:
            out.append(t)
    return out


def rewrite_calls(tokens, mapping):
    """`name(` -> `mapping[name](` for function calls only."""
    out = []
    for i, t in enumerate(tokens):
        if t.kind == "ident" and t.text in mapping:
            j = next_code(tokens, i + 1)
            if j < len(tokens) and tokens[j].text == "(":
                p = prev_code(tokens, i - 1)
                if p < 0 or tokens[p].text not in (".", "->"):
                    out.append(T("ident", mapping[t.text]))
                    continue
        out.append(t)
    return out


def rewrite_get_sample_rate(tokens):
    out = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t.kind == "ident" and t.text == "getSampleRate":
            j = next_code(tokens, i + 1)
            if j < len(tokens) and tokens[j].text == "(":
                close = match(tokens, j)
                out.append(T("ident", "aw_sample_rate"))
                i = close + 1
                continue
        out.append(t)
        i += 1
    return out


def rewrite_rand(tokens):
    out = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t.kind == "ident" and t.text == "rand":
            j = next_code(tokens, i + 1)
            if j < len(tokens) and tokens[j].text == "(":
                close = match(tokens, j)
                out.extend(_toks("aw_rand_next(&aw_rand)"))
                i = close + 1
                continue
        if t.kind == "ident" and t.text == "RAND_MAX":
            out.append(T("ident", "AW_RAND_MAX"))
            i += 1
            continue
        out.append(t)
        i += 1
    return out


def hoist_statics(tokens):
    """Function-local statics become state. Returns tokens and (type, name,
    init) for each."""
    statics = []

    def pred(toks, i):
        return toks[i].text == "static"

    kept, removed = remove_statements(tokens, pred)
    consts = []
    for stmt in removed:
        cs = code(stmt)
        words = [t.text for t in cs]
        if "const" in words:
            consts.append(" ".join(words))
            continue
        eq = words.index("=") if "=" in words else len(words)
        ctype = " ".join(w for w in words[1:eq - 1] if w != "const")
        name = words[eq - 1]
        init = " ".join(words[eq + 1:-1]) if eq < len(words) else "0"
        statics.append((ctype, name, init))
    return kept, statics, consts


# --- the fast variant -----------------------------------------------------------

_ASSIGN = {"=", "+=", "-=", "*=", "/=", "++", "--"}
_COMPARE = {"<", ">", "<=", ">=", "==", "!="}


def wide_spans(tokens, wide):
    """Token indexes of the statements that write or compare a wide name.
    Statements that only read one take it in single precision."""
    keep = set()
    if not wide:
        return keep
    for k, t in enumerate(tokens):
        if t.kind == "ident" and t.text in wide:
            nxt = next_code(tokens, k + 1)
            prv = prev_code(tokens, k - 1)
            after = tokens[nxt].text if nxt < len(tokens) else ""
            before = tokens[prv].text if prv >= 0 else ""
            if after in _ASSIGN or after in _COMPARE or before in _COMPARE \
                    or before in ("++", "--"):
                s, e = stmt_extent(tokens, k)
                keep.update(range(s, e + 1))
    return keep


def to_single(tokens, wide=()):
    """double and long double become float; floating literals get an f.

    Statements that touch a `wide` member (one the policy keeps double, as
    a long phase sum) are left as upstream wrote them."""
    keep = wide_spans(tokens, wide)
    out = []
    i = 0
    n = len(tokens)
    while i < n:
        t = tokens[i]
        if i in keep:
            out.append(t)
            i += 1
            continue
        if t.kind == "ident" and t.text == "long":
            j = next_code(tokens, i + 1)
            if j < n and tokens[j].text == "double":
                out.append(T("ident", "float"))
                i = j + 1
                continue
        if t.kind == "ident" and t.text == "double":
            out.append(T("ident", "float"))
            i += 1
            continue
        if is_float_literal(t):
            text = t.text.rstrip("fFlL")
            value = float(text)
            if value != 0.0 and (abs(value) < 1.17549435e-38
                                 or abs(value) > 3.4028234e38):
                # Outside float's normal range: kept double, which the
                # classifier reports. None of the plug-ins needs it.
                out.append(T("number", text))
            else:
                out.append(T("number", text + "f"))
            i += 1
            continue
        out.append(t)
        i += 1
    return out


def _call_args(tokens, open_index):
    close = match(tokens, open_index)
    args = []
    cur = []
    depth = 0
    for t in tokens[open_index + 1:close]:
        if t.kind == "op" and t.text in "([{":
            depth += 1
        elif t.kind == "op" and t.text in ")]}":
            depth -= 1
        if depth == 0 and t.text == ",":
            args.append(cur)
            cur = []
        else:
            cur.append(t)
    args.append(cur)
    return args, close


def _small_power(arg):
    cs = code(arg)
    if len(cs) != 1 or cs[0].kind != "number":
        return None
    try:
        v = float(cs[0].text.rstrip("fFlLuU"))
    except ValueError:
        return None
    if v in (2.0, 3.0, 4.0):
        return int(v)
    return None


def rewrite_fast_math(tokens, issues, wide=()):
    keep = wide_spans(tokens, wide)
    out = []
    i = 0
    n = len(tokens)
    while i < n:
        t = tokens[i]
        if i in keep:
            out.append(t)
            i += 1
            continue
        if t.kind == "ident":
            j = next_code(tokens, i + 1)
            p = prev_code(tokens, i - 1)
            is_call = j < n and tokens[j].text == "(" and not (
                p >= 0 and tokens[p].text in (".", "->"))
            if is_call and t.text in ("pow", "powf"):
                args, close = _call_args(tokens, j)
                if len(args) == 2:
                    power = _small_power(args[1])
                    if power is not None:
                        inner = rewrite_fast_math(args[0], issues)
                        out.extend(_toks("aw_pow%di(" % power) + inner +
                                   _toks(")"))
                        i = close + 1
                        continue
            if is_call and t.text in FAST_MATH:
                out.append(T("ident", FAST_MATH[t.text]))
                i += 1
                continue
        out.append(t)
        i += 1
    return out


def _operand_end(tokens, j):
    """End index (inclusive) of the unary-expression starting at j."""
    n = len(tokens)
    j = next_code(tokens, j)
    while j < n and tokens[j].text in ("-", "+", "!", "~"):
        j = next_code(tokens, j + 1)
    if tokens[j].text == "(":
        close = match(tokens, j)
        inner = code(tokens[j + 1:close])
        if inner and all(x.text in CAST_TYPES for x in inner):
            return _operand_end(tokens, close + 1)
        end = close
    elif tokens[j].kind in ("ident", "number"):
        end = j
    else:
        return None
    while True:
        k = next_code(tokens, end + 1)
        if k < n and tokens[k].text in ("[", "("):
            end = match(tokens, k)
        elif k < n and tokens[k].text in (".", "->"):
            end = next_code(tokens, k + 1)
        else:
            return end


def _is_float_expr(toks, types):
    """Whether an operand is floating point: it holds a float literal, a
    float variable or a float-valued call, and no cast to an integer."""
    cs = code(toks)
    for k, t in enumerate(cs):
        if t.text == "(" and k + 2 < len(cs) and cs[k + 2].text == ")" and \
                cs[k + 1].text in CAST_TYPES and cs[k + 1].text not in (
                    "double", "float"):
            return False
    for k, t in enumerate(cs):
        if is_float_literal(t):
            return True
        if t.kind == "ident":
            if types.get(t.text) in FLOAT_TYPES:
                return True
            if t.text in FLOAT_FUNCS and k + 1 < len(cs) and \
                    cs[k + 1].text == "(":
                return True
            if t.text in ("float", "double"):
                return True
    return False


def _assigned(tokens):
    """Names assigned anywhere in tokens (=, op=, ++, --, &name)."""
    out = set()
    cs = code(tokens)
    for k, t in enumerate(cs):
        if t.kind != "ident":
            continue
        nxt = cs[k + 1].text if k + 1 < len(cs) else ""
        prv = cs[k - 1].text if k > 0 else ""
        if nxt in ("=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=",
                   "<<=", ">>=", "++", "--") or prv in ("++", "--", "&"):
            out.add(t.text)
        if nxt == "[":
            # x[i] = ... assigns into x; that is not x itself changing.
            pass
    return out


def rewrite_fast_divisions(loop, types, outside, hoisted):
    """Divisions in the loop body. `outside` names declared before the loop
    (members, parameters, pre-loop locals); `hoisted` collects the
    reciprocals to declare before it, as (name, expression tokens)."""
    assigned = _assigned(loop)
    inner_decls = set(declared_locals(loop))
    out = []
    i = 0
    n = len(loop)
    while i < n:
        t = loop[i]
        if t.kind == "op" and t.text in ("/", "/="):
            if t.text == "/=":
                # x /= rhs;  the right side runs to the statement's end.
                e = i + 1
                depth = 0
                while e < n and not (loop[e].text == ";" and depth == 0):
                    if loop[e].text in "([":
                        depth += 1
                    elif loop[e].text in ")]":
                        depth -= 1
                    e += 1
                operand = loop[i + 1:e]
                end = e - 1
            else:
                end = _operand_end(loop, i + 1)
                if end is None:
                    out.append(t)
                    i += 1
                    continue
                operand = loop[i + 1:end + 1]
            p = prev_code(out, len(out) - 1)
            left_float = False
            if p >= 0:
                lt = out[p]
                if is_float_literal(lt) or types.get(lt.text) in FLOAT_TYPES:
                    left_float = True
                elif lt.text == ")":
                    # Find the matching ( in out.
                    depth = 0
                    q = p
                    while q >= 0:
                        if out[q].text == ")":
                            depth += 1
                        elif out[q].text == "(":
                            depth -= 1
                            if depth == 0:
                                break
                        q -= 1
                    left_float = _is_float_expr(out[q:p + 1], types)
                elif lt.text == "]":
                    q = p
                    while q >= 0 and out[q].text != "[":
                        q -= 1
                    b = prev_code(out, q - 1)
                    left_float = b >= 0 and types.get(out[b].text) in \
                        FLOAT_TYPES
            if t.text == "/=":
                lhs = prev_code(out, len(out) - 1)
                left_float = lhs >= 0 and types.get(out[lhs].text) in \
                    FLOAT_TYPES
            if not (left_float or _is_float_expr(operand, types)):
                out.append(t)
                i += 1
                continue
            names = identifiers(operand)
            calls = {x.text for k, x in enumerate(code(operand))
                     if x.kind == "ident" and k + 1 < len(code(operand))
                     and code(operand)[k + 1].text == "("}
            invariant = names and not (names & assigned) and \
                not (names & inner_decls) and names <= outside and \
                not (calls - FLOAT_FUNCS - {"aw_abs"}) and \
                "aw_rand_next" not in names
            invariant = invariant or (not names)
            op = "*=" if t.text == "/=" else "*"
            if invariant:
                key = join(code(operand))
                for name, expr in hoisted:
                    if join(code(expr)) == key:
                        break
                else:
                    name = "aw_inv%d" % len(hoisted)
                    hoisted.append((name, operand))
                out.extend([T("op", op), T("ws", " "), T("ident", name)])
            else:
                out.extend([T("op", op), T("ws", " ")] +
                           _toks("aw_recipf(") + operand + _toks(")"))
            i = end + 1
            continue
        out.append(t)
        i += 1
    return out


def rewrite_int_sums(loop, types):
    """`int w = count + offset;` with offset a float: the sum in single
    precision can round across a whole number that double wouldn't, and
    the index jumps a sample while the fraction stays put. For a sum that
    isn't negative, which an index is, count + floor(offset) is the same
    number and needs no rounding, so the fast variant writes that."""
    out = list(loop)
    k = 0
    while k < len(out):
        t = out[k]
        if t.kind == "ident" and types.get(t.text) in ("int", "int32_t",
                                                       "long", "VstInt32"):
            nxt = next_code(out, k + 1)
            if nxt < len(out) and out[nxt].text == "=":
                s = next_code(out, nxt + 1)
                e = s
                depth = 0
                while e < len(out) and not (out[e].text == ";" and
                                            depth == 0):
                    if out[e].text in "([":
                        depth += 1
                    elif out[e].text in ")]":
                        depth -= 1
                    e += 1
                rhs = out[s:e]
                terms = []
                cur = []
                depth = 0
                for x in rhs:
                    if x.text in "([":
                        depth += 1
                    elif x.text in ")]":
                        depth -= 1
                    if depth == 0 and x.text in ("+", "-") and code(cur):
                        terms.append((cur, x))
                        cur = []
                    else:
                        cur.append(x)
                terms.append((cur, None))
                if len(terms) == 2 and terms[0][1].text == "+":
                    a, b = terms[0][0], terms[1][0]
                    fa, fb = _is_float_expr(a, types), _is_float_expr(b, types)
                    if fa != fb:
                        i_term, f_term = (b, a) if fa else (a, b)
                        new = i_term + [T("op", " + ")] + _toks(
                            "(int)aw_floorf(") + f_term + _toks(")")
                        out[s:e] = new
                        k = s + len(new)
                        continue
        k += 1
    return out


# C++'s <cmath> has float and long double overloads that C's math.h lacks: sqrt(B) with a
# float B is sqrtf in upstream's build and sqrt in C. Calls whose arguments
# are all single precision take the float function, as upstream's do.
_CXX_FLOAT_OVERLOADS = {
    "sqrt": "sqrtf", "sin": "sinf", "cos": "cosf", "tan": "tanf",
    "exp": "expf", "log": "logf", "log10": "log10f", "pow": "powf",
    "atan": "atanf", "asin": "asinf", "acos": "acosf", "atan2": "atan2f",
    "sinh": "sinhf", "cosh": "coshf", "tanh": "tanhf", "cbrt": "cbrtf",
    "floor": "floorf", "ceil": "ceilf", "fmod": "fmodf", "exp2": "exp2f",
    "log2": "log2f", "hypot": "hypotf", "fmin": "fminf", "fmax": "fmaxf",
    "expm1": "expm1f", "log1p": "log1pf", "fabs": "fabsf", "asinh": "asinhf",
    "acosh": "acoshf", "atanh": "atanhf", "trunc": "truncf",
    "round": "roundf"}


def _is_single_expr(toks, types):
    """Whether an expression is float in C++: float variables, integers and
    f-suffixed literals only, with no call and no double anywhere."""
    cs = code(toks)
    seen_float = False
    for k, t in enumerate(cs):
        if t.kind == "number":
            if is_float_literal(t) and not t.text.lower().endswith("f"):
                return False
            if is_float_literal(t):
                seen_float = True
        elif t.kind == "ident":
            if k + 1 < len(cs) and cs[k + 1].text in ("(", "["):
                return False
            ctype = types.get(t.text)
            if ctype == "float":
                seen_float = True
            elif ctype in FLOAT_TYPES or ctype is None:
                return False
    return seen_float


def rewrite_cxx_float_overloads(tokens, types):
    out = list(tokens)
    i = 0
    while i < len(out):
        t = out[i]
        if t.kind == "ident" and t.text in _CXX_FLOAT_OVERLOADS:
            j = next_code(out, i + 1)
            if j < len(out) and out[j].text == "(" and \
                    (i == 0 or out[prev_code(out, i - 1)].text not in
                     (".", "->")):
                args, _ = _call_args(out, j)
                if args and all(_is_single_expr(a, types) for a in args):
                    out[i] = T("ident", _CXX_FLOAT_OVERLOADS[t.text])
                elif any(types.get(x.text) == "long double"
                         for a in args for x in code(a) if x.kind == "ident"):
                    # And the long double ones: sin(x) is sinl(x) in C++.
                    out[i] = T("ident", t.text + "l")
        i += 1
    return out


# --- fixed-point phases -------------------------------------------------------

def _phase_parts(loop, name):
    """The step expression of `name += step;` and that statement's extent."""
    cs = [k for k, t in enumerate(loop) if t.kind == "ident" and
          t.text == name]
    for k in cs:
        nxt = next_code(loop, k + 1)
        prv = prev_code(loop, k - 1)
        if loop[nxt].text == "+=" and (prv < 0 or loop[prv].text in
                                        (";", "{", "}")):
            s, e = stmt_extent(loop, k)
            step = loop[next_code(loop, nxt + 1):e]
            return step, next_code(loop, s), e
    raise TranslateError("phase %s: no `%s += step;`" % (name, name))


def lower_phase(loop, name):
    """A phase that only ever grows by a step and wraps to zero, kept in
    Q4.60 fixed point instead of double, the way an oscillator keeps one.

    In the loop, `name += step;` adds a step worked out once in Q4.60 (and
    again after each statement that changes what it is made of), `name >
    limit` compares in Q4.60, `name = x;` stores x in Q4.60, and every other
    read takes it as a float. Returns the loop and the step expression."""
    step, s, e = _phase_parts(loop, name)
    parts = identifiers(step)
    if name in parts:
        raise TranslateError("phase %s: its step reads it" % name)
    stepname = "aw_step_" + name
    loop = loop[:s] + _toks("%s += %s;" % (name, stepname)) + loop[e + 1:]
    refresh = _toks("\n\t\t\t%s = AW_Q60_STEP(" % stepname) + step + \
        _toks(");")
    out = []
    i = 0
    n = len(loop)
    while i < n:
        t = loop[i]
        if t.kind == "ident" and t.text == name:
            nxt = next_code(loop, i + 1)
            prv = prev_code(loop, i - 1)
            after = loop[nxt].text if nxt < n else ""
            if after == "+=" and loop[next_code(loop, nxt + 1)].text == \
                    stepname:
                out.append(t)
                i += 1
                continue
            if after == "=":
                _, e = stmt_extent(loop, i)
                value = loop[next_code(loop, nxt + 1):e]
                out.extend(_toks("%s = AW_Q60(" % name) + value +
                           _toks(");"))
                i = e + 1
                continue
            if after in ("+=", "-=", "*=", "/=", "++", "--") or \
                    (prv >= 0 and loop[prv].text in ("++", "--")):
                raise TranslateError("phase %s: changed by `%s`" %
                                     (name, after))
            if after in (">", ">=") and loop[nxt + 1:nxt + 2] and \
                    next_code(loop, nxt + 1) < n:
                j = next_code(loop, nxt + 1)
                if loop[j].text == "(":
                    close = match(loop, j)
                    out.extend([t] + loop[i + 1:j] + _toks("AW_Q60") +
                               loop[j:close + 1])
                    i = close + 1
                    continue
                if loop[j].kind == "number":
                    out.extend([t] + loop[i + 1:j] + _toks("AW_Q60(") +
                               [loop[j]] + _toks(")"))
                    i = j + 1
                    continue
                raise TranslateError("phase %s: compared with an "
                                     "expression" % name)
            if after in _COMPARE or (prv >= 0 and loop[prv].text in
                                     _COMPARE):
                raise TranslateError("phase %s: compared other than "
                                     "`> limit`" % name)
            out.extend(_toks("aw_q60f(%s)" % name))
            i += 1
            continue
        if t.kind == "ident" and t.text in parts and t.text != stepname:
            nxt = next_code(loop, i + 1)
            prv = prev_code(loop, i - 1)
            if nxt < n and loop[nxt].text in ("=", "+=", "-=", "*=", "/=",
                                              "++", "--") and \
                    (prv < 0 or loop[prv].text in (";", "{", "}")):
                _, e = stmt_extent(loop, i)
                out.extend(loop[i:e + 1] + refresh)
                i = e + 1
                continue
        out.append(t)
        i += 1
    return out, step


def lower_phase_ctor(tokens, name):
    """`name = x;` -> `name = AW_Q60(x);` in a constructor or reset."""
    out = []
    i = 0
    n = len(tokens)
    while i < n:
        t = tokens[i]
        if t.kind == "ident" and t.text == name:
            nxt = next_code(tokens, i + 1)
            if nxt < n and tokens[nxt].text == "=":
                _, e = stmt_extent(tokens, i)
                value = tokens[next_code(tokens, nxt + 1):e]
                out.extend(_toks("%s = AW_Q60(" % name) + value + _toks(");"))
                i = e + 1
                continue
            raise TranslateError("phase %s: used in the constructor other "
                                 "than by `=`" % name)
        out.append(t)
        i += 1
    return out


# --- the air residue ------------------------------------------------------------

def rewrite_quiet_residue(loop):
    """Skip the air residue's arithmetic when the input sample isn't zero.

    Older plug-ins add a residue of at most 1.7e-15 to the input, and take it
    off again if the sum is still below float's smallest normal. An input
    that isn't zero is a multiple of 2^-15 (an int16 over 32768), whose half
    step is 1.8e-12, so the sum rounds back to the input exactly and the test
    fails. Only a zero input changes, so only a zero input works it out. The
    noise source still counts every sample, as upstream's does."""
    out = list(loop)
    k = 0
    while True:
        found = None
        for i in range(k, len(out)):
            t = out[i]
            if t.kind == "ident" and t.text == "residue":
                s, e = stmt_extent(out, i)
                words = [x.text for x in code(out[s:e + 1])]
                if len(words) == 6 and words[:2] == ["residue", "="] and \
                        words[2] == words[4] and words[3] == "*" and \
                        words[2].startswith("noisesource"):
                    found = (next_code(out, s), e)
                    break
        if found is None:
            return out
        start, e = found
        # inputSampleX += applyresidue; if (...) { inputSampleX -= ...; }
        add = None
        for i in range(e, len(out)):
            if out[i].kind == "ident" and out[i].text.startswith(
                    "inputSample"):
                j = next_code(out, i + 1)
                if out[j].text == "+=" and \
                        out[next_code(out, j + 1)].text == "applyresidue":
                    add = i
                    break
        if add is None:
            return out
        sample = out[add].text
        _, add_end = stmt_extent(out, add)
        iff = next_code(out, add_end + 1)
        if out[iff].text != "if":
            return out
        cond_close = match(out, next_code(out, iff + 1))
        brace = next_code(out, cond_close + 1)
        if out[brace].text != "{":
            return out
        end = match(out, brace)
        inner = [x.text for x in code(out[brace + 1:end])]
        if inner != [sample, "-=", "applyresidue", ";"]:
            return out
        # The sample must still be the input as it came in.
        before = [i for i, x in enumerate(out[:start]) if x.kind == "ident"
                  and x.text == sample]
        if len(before) != 1:
            return out
        d = before[0]
        decl = [x.text for x in code(out[stmt_extent(out, d)[0]:
                                         stmt_extent(out, d)[1] + 1])]
        if decl[-3:-1] != ["=", "aw_in" + sample[len("inputSample"):]]:
            return out
        # Nothing after reads the residue before writing it again.
        for name in ("residue", "applyresidue"):
            for i in range(end + 1, len(out)):
                if out[i].kind == "ident" and out[i].text == name:
                    j = next_code(out, i + 1)
                    if out[j].text != "=":
                        return out
                    break
        out = out[:start] + _toks("if (%s == 0.0f) {\n\t\t" % sample) + \
            out[start:end + 1] + _toks("\n\t\t}") + out[end + 1:]
        k = end + 10


# --- sinking a value into the branch that uses it -------------------------------

_PURE_CALLS = re.compile(r"^(aw_[a-z0-9_]+|fabsf?|sqrtf?|sinf?|cosf?|"
                         r"expf?|logf?|powf?|tanhf?)$")
_WRITES = {"=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>=",
           "++", "--"}


def _top_blocks(loop):
    """(open, close) of each braced block at the loop's top level that is
    the body of an `if (...)` or an `else`."""
    out = []
    depth = 0
    for i, t in enumerate(loop):
        if t.kind != "op":
            continue
        if t.text == "{":
            if depth == 0:
                p = prev_code(loop, i - 1)
                body_of_if = False
                if p >= 0 and loop[p].text == "else":
                    body_of_if = True
                elif p >= 0 and loop[p].text == ")":
                    # Walk back to the parenthesis' opening.
                    d = 0
                    q = p
                    while q >= 0:
                        if loop[q].text == ")":
                            d += 1
                        elif loop[q].text == "(":
                            d -= 1
                            if d == 0:
                                break
                        q -= 1
                    kw = prev_code(loop, q - 1)
                    body_of_if = kw >= 0 and loop[kw].text == "if"
                if body_of_if:
                    out.append((i, match(loop, i)))
            depth += 1
        elif t.text == "}":
            depth -= 1
    return out


def sink_into_branches(loop):
    """Move `float x = expr;` into the one if or else block that reads x.

    Upstream often works out a value for both arms of a branch and uses it in
    one; on a board without a divider, a reciprocal it throws away is time.
    Only a side-effect-free expr moves, and only when nothing it reads
    changes between where it was and where it goes."""
    out = list(loop)
    changed = True
    while changed:
        changed = False
        blocks = _top_blocks(out)
        depth = 0
        for i, t in enumerate(out):
            if t.kind == "op" and t.text == "{":
                depth += 1
            elif t.kind == "op" and t.text == "}":
                depth -= 1
            if depth or t.kind != "ident" or t.text != "float":
                continue
            p = prev_code(out, i - 1)
            if p >= 0 and out[p].text not in (";", "{", "}"):
                continue
            name_at = next_code(out, i + 1)
            eq = next_code(out, name_at + 1)
            if out[name_at].kind != "ident" or out[eq].text != "=":
                continue
            name = out[name_at].text
            _, end = stmt_extent(out, name_at)
            expr = out[eq + 1:end]
            cs = code(expr)
            if any(x.text in _WRITES for x in cs):
                continue
            pure = True
            for k, x in enumerate(cs):
                if x.kind == "ident" and k + 1 < len(cs) and \
                        cs[k + 1].text == "(" and not _PURE_CALLS.match(x.text):
                    pure = False
            if not pure:
                continue
            uses = [k for k in range(end + 1, len(out)) if out[k].kind ==
                    "ident" and out[k].text == name]
            if not uses:
                continue
            home = [b for b in blocks if b[0] < uses[0] and uses[-1] < b[1]]
            if len(home) != 1 or home[0][0] < end:
                continue
            open_, close = home[0]
            # What expr reads must not change before x's last use.
            reads = {x.text for x in cs if x.kind == "ident"}
            span = out[end + 1:uses[-1]]
            if reads & _assigned(span):
                continue
            # x itself must not be written in the block.
            if name in _assigned(out[open_:close]):
                continue
            s = next_code(out, p + 1) if p >= 0 else next_code(out, 0)
            decl = out[s:end + 1]
            # After a comment that ends the brace's line.
            at = open_ + 1
            while at < close and (out[at].kind == "comment" or (
                    out[at].kind == "ws" and "\n" not in out[at].text)):
                at += 1
            cut = s - 1 if s > 0 and out[s - 1].kind == "ws" else s
            out = out[:cut] + out[end + 1:at] + \
                _toks("\n\t\t\t") + decl + out[at:]
            changed = True
            break
    return out


# --- sines of a sample ------------------------------------------------------------

_BOUNDED_SOURCES = {"aw_inL", "aw_inR"}
_SINES = {"aw_sinf", "aw_sin_quarter"}


def _top_statements(loop):
    """(start, end) of each statement at the loop's top level: a simple
    statement through its ';', or an if/else chain through its last '}'."""
    out = []
    i = next_code(loop, 0)
    n = len(loop)
    while i < n:
        t = loop[i]
        if t.text in ("if", "while", "for", "switch", "do") or t.text == "{":
            s = i
            while True:
                if loop[i].text == "{":
                    i = match(loop, i)
                elif loop[i].text in ("if", "while", "for", "switch"):
                    j = next_code(loop, i + 1)
                    j = match(loop, j)
                    k = next_code(loop, j + 1)
                    if k < n and loop[k].text == "{":
                        i = match(loop, k)
                    else:
                        _, i = stmt_extent(loop, k)
                else:
                    _, i = stmt_extent(loop, i)
                k = next_code(loop, i + 1)
                if k < n and loop[k].text == "else":
                    i = next_code(loop, k + 1)
                    continue
                break
            out.append((s, i))
        else:
            _, e = stmt_extent(loop, i)
            out.append((i, e))
            i = e
        i = next_code(loop, i + 1)
    return out


def _is_denormal_guard(cs, name):
    """`if (fabsf(name)<c) name = fpd * k;` with a tiny k: the result stays
    far below 1."""
    words = [x.text for x in cs]
    if len(words) < 14 or words[:5] != ["if", "(", "fabsf", "(", name]:
        return False
    try:
        close = words.index(")", 6)
    except ValueError:
        return False
    rest = words[close + 1:]
    if len(rest) != 6 or rest[0] != name or rest[1] != "=" or \
            rest[3] != "*" or rest[5] != ";" or not rest[2].startswith("fpd"):
        return False
    try:
        return abs(float(rest[4].rstrip("fF"))) < 1e-10
    except ValueError:
        return False


def rewrite_bounded_sines(loop):
    """The sine of a value known to lie in [-1, 1] skips range reduction.

    An input sample is an int16 over 32768, and a sine's result is in
    [-1, 1]; a name holds such a value from its assignment until anything
    else writes it. aw_sinf of anything within pi/2 is aw_sin_quarter of it
    exactly, so the output doesn't change, and with no branch left the
    compiler can share one sine between two calls on the same value."""
    out = list(loop)
    bounded = set()
    k = 0
    while True:
        stmts = [x for x in _top_statements(out) if x[0] >= k]
        if not stmts:
            return out
        s, e = stmts[0]
        cs = code(out[s:e + 1])
        words = [x.text for x in cs]
        simple = words[0] not in ("if", "while", "for", "switch", "do", "{")
        if simple:
            # Rewrite sines of bounded names in this statement.
            piece = out[s:e + 1]
            new = []
            i = 0
            while i < len(piece):
                t = piece[i]
                if t.kind == "ident" and t.text == "aw_sinf":
                    j = next_code(piece, i + 1)
                    if j < len(piece) and piece[j].text == "(":
                        close = match(piece, j)
                        arg = code(piece[j + 1:close])
                        if len(arg) == 1 and arg[0].kind == "ident" and (
                                arg[0].text in bounded or
                                arg[0].text in _BOUNDED_SOURCES):
                            new.extend(_toks("aw_sin_quarter") +
                                       piece[i + 1:close + 1])
                            i = close + 1
                            continue
                new.append(t)
                i += 1
            out = out[:s] + new + out[e + 1:]
            e = s + len(new) - 1
            cs = code(out[s:e + 1])
            words = [x.text for x in cs]
            # Track what this statement leaves bounded.
            if "=" in words and words.index("=") >= 1:
                eq = words.index("=")
                name = words[eq - 1]
                rhs = words[eq + 1:-1]
                ok = (len(rhs) == 1 and (rhs[0] in bounded or
                                         rhs[0] in _BOUNDED_SOURCES)) or (
                    len(rhs) >= 3 and rhs[0] in _SINES and rhs[1] == "(" and
                    rhs[-1] == ")" and match(cs, eq + 2) == len(cs) - 2)
                written = _assigned(out[s:e + 1])
                bounded -= written
                if ok and words[eq - 2:eq - 1] != ["*"] and \
                        all(w not in ("+=", "-=", "*=", "/=") for w in words):
                    bounded.add(name)
            else:
                bounded -= _assigned(out[s:e + 1])
        else:
            keep = {n for n in bounded if _is_denormal_guard(cs, n)}
            bounded -= _assigned(out[s:e + 1])
            bounded |= keep
        k = e + 1


# --- a counter's wrap -----------------------------------------------------------

def rewrite_mod_wrap(loop, types):
    """`x = x % N;` -> `if ((uint32_t)x >= N) x = x % N;` for an int x.

    A counter that steps by one is below N all but once in N samples, and
    for 0 <= x < N, x % N is x, so the divide runs only when it changes
    something. A negative x is a large unsigned one and still takes it."""
    out = []
    i = 0
    n = len(loop)
    while i < n:
        t = loop[i]
        if t.kind == "ident" and types.get(t.text) in ("int", "int32_t",
                                                       "uint32_t", "long"):
            p = prev_code(loop, i - 1)
            if p < 0 or loop[p].text in (";", "{", "}"):
                s, e = stmt_extent(loop, i)
                words = [x.text for x in code(loop[s:e + 1])]
                if len(words) == 6 and words[1] == "=" and \
                        words[2] == t.text and words[3] == "%" and \
                        words[4].isdigit() and int(words[4]) > 0:
                    out.extend(_toks("if ((uint32_t)%s >= %su) %s = %s %% %s;"
                                     % (t.text, words[4], t.text, t.text,
                                        words[4])))
                    i = e + 1
                    continue
        out.append(t)
        i += 1
    return out
