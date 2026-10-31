# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Copyright (c) 2026 Brad Barnett
"""python -m tools.awgen [--upstream DIR] [--only Name,Name] [--check]

Reads upstream's plug-ins and writes the generated kernels, the registry and
the bindings' tables. --check compiles each kernel on its own with the host's
cc and writes the result to tools/awgen/fit.json, which the plug-in list and
the skipped list are made from.
"""

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import describe, emit_bindings, emit_kernel
from .parse import parse_plugin
from .translate import TranslateError

ROOT = Path(__file__).resolve().parents[2]
POLICY = json.loads((Path(__file__).parent / "policy.json").read_text())
DEFAULT_UPSTREAM = Path(os.environ.get(
    "AIRWINDOWS_UPSTREAM", ROOT / ".cache" / "airwindows-upstream"))


def upstream_commit(upstream):
    try:
        return subprocess.check_output(
            ["git", "-C", str(upstream), "rev-parse", "HEAD"],
            text=True).strip()
    except Exception:
        return "unknown"


def load(upstream, only=None):
    src = upstream / "plugins" / "LinuxVST" / "src"
    what = describe.read_what(upstream / "what.txt")
    cats = describe.read_categories(upstream / "Airwindopedia.txt")
    names = sorted(p.name for p in src.iterdir() if p.is_dir())
    if only:
        names = [n for n in names if n in only]
    plugins, failed = [], {}
    for name in names:
        try:
            plugin = parse_plugin(src, name)
        except Exception as e:  # noqa: BLE001
            failed[name] = "parse: %s" % e
            continue
        describe.complete(plugin, what.get(name))
        plugin.category = cats.get(name, "")
        plugin.wide = POLICY.get(name, {}).get("wide", [])
        plugin.phase = POLICY.get(name, {}).get("phase", [])
        plugin.fast_as_ref = POLICY.get(name, {}).get("fast") is False
        plugin.fixed = POLICY.get(name, {}).get("fixed", False)
        plugins.append(plugin)
    return plugins, failed


def compile_check(path):
    """Compiles one kernel both ways. Returns the first error or None, and
    how many places the fast variant still does double arithmetic."""
    errors = []
    doubles = 0
    for flags in (["-DAW_BUILD_REF=1", "-DAW_BUILD_FAST=0"],
                  ["-DAW_BUILD_REF=0", "-DAW_BUILD_FAST=1",
                   "-DAW_COUNT_DOUBLES=1", "-Wdouble-promotion"]):
        r = subprocess.run(
            ["cc", "-std=c11", "-O1", "-c", "-o", os.devnull,
             "-I", str(ROOT / "src"), "-Werror=implicit-function-declaration",
             "-Werror=incompatible-pointer-types", "-Werror=int-conversion",
             "-Wno-unused-variable", "-Wno-unused-but-set-variable"] +
            flags + [str(path)], capture_output=True, text=True)
        if r.returncode:
            lines = [ln for ln in r.stderr.splitlines() if "error" in ln]
            errors.append(lines[0] if lines else r.stderr[:300])
        elif "-Wdouble-promotion" in flags:
            # Only the per-sample loop counts: the rest runs once a block
            # and keeps upstream's double on purpose.
            lines = Path(path).read_text().splitlines()
            fast_at = next(i for i, ln in enumerate(lines)
                           if ln.startswith("#if AW_BUILD_FAST"))
            inside = set()
            on = False
            for i, ln in enumerate(lines[fast_at:], fast_at + 1):
                if "/* aw:loop */" in ln:
                    on = True
                if on:
                    inside.add(i)
                if "/* aw:end */" in ln:
                    on = False
            for ln in r.stderr.splitlines():
                if "[-Wdouble-promotion]" in ln:
                    try:
                        if int(ln.split(":")[1]) in inside:
                            doubles += 1
                    except (IndexError, ValueError):
                        pass
    return (errors[0] if errors else None), doubles


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m tools.awgen")
    ap.add_argument("--upstream", type=Path, default=DEFAULT_UPSTREAM)
    ap.add_argument("--only", default="")
    ap.add_argument("--out", type=Path, default=ROOT / "src" / "airwindows"
                    / "plugins")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--jobs", type=int, default=2)
    args = ap.parse_args(argv)
    only = set(filter(None, args.only.split(",")))
    commit = upstream_commit(args.upstream)
    plugins, failed = load(args.upstream, only)
    args.out.mkdir(parents=True, exist_ok=True)
    written = []
    issues = {}
    for plugin in plugins:
        skip = POLICY.get(plugin.name, {}).get("skip")
        if skip:
            # policy.json says why this one isn't carried.
            failed[plugin.name] = "skipped: %s" % skip
            stale = args.out / (plugin.name + ".c")
            if stale.exists():
                stale.unlink()
            continue
        try:
            text, found = emit_kernel.emit(plugin, commit)
        except (TranslateError, Exception) as e:  # noqa: BLE001
            failed[plugin.name] = "translate: %s" % e
            continue
        path = args.out / (plugin.name + ".c")
        if not path.exists() or path.read_text() != text:
            path.write_text(text)
        written.append((plugin, path))
        if found or plugin.flags:
            issues[plugin.name] = sorted(set(found + plugin.flags))
    index_path = Path(__file__).parent / "plugins.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {}
    for plugin, _ in written:
        index[plugin.name] = {
            "summary": plugin.summary, "collections": plugin.collections,
            "category": plugin.category, "seeds": plugin.seeds,
            "params": [{"py": p.py, "name": p.name, "label": p.label,
                        "default": p.default} for p in plugin.params]}
    index_path.write_text(json.dumps(index, indent=1, sort_keys=True) + "\n")
    if args.check:
        with ThreadPoolExecutor(args.jobs) as pool:
            results = list(pool.map(lambda pp: compile_check(pp[1]), written))
        doubles = {}
        for (plugin, _), (err, nd) in zip(written, results):
            if err:
                failed[plugin.name] = "compile: %s" % err
            elif nd:
                doubles[plugin.name] = nd
        fit_path = Path(__file__).parent / "fit.json"
        fit = {"commit": commit, "failed": {}, "issues": {},
               "fast_doubles": {}, "ok": []}
        if only and fit_path.exists():
            # A partial run updates the plug-ins it checked and keeps the rest.
            fit = json.loads(fit_path.read_text())
            for key in ("failed", "issues", "fast_doubles"):
                for name in only:
                    fit[key].pop(name, None)
            fit["ok"] = [n for n in fit["ok"] if n not in only]
        fit["commit"] = commit
        fit["failed"].update(failed)
        fit["issues"].update(issues)
        fit["fast_doubles"].update(doubles)
        fit["ok"] = sorted(set(fit["ok"]) | {
            p.name for p, _ in written if p.name not in failed})
        fit_path.write_text(
            json.dumps(fit, indent=1, sort_keys=True) + "\n")
    # The bindings carry every plug-in that has a kernel and compiles.
    fit_path = Path(__file__).parent / "fit.json"
    broken = dict(json.loads(fit_path.read_text())["failed"]) \
        if fit_path.exists() else {}
    broken.update(failed)
    carried = {n: v for n, v in index.items() if n not in broken and
               (args.out / (n + ".c")).exists()}
    left_out = {n: why.split(": ", 1)[-1] for n, why in broken.items()}
    default = emit_bindings.emit(ROOT, carried, POLICY, left_out)
    print("bindings: %d plug-ins, %d in the board default" % (
        len(carried), len(default)))
    print("%d written, %d failed, %d with issues" % (
        len(written), len(failed), len(issues)))
    for name, why in sorted(failed.items())[:40]:
        print("  %s: %s" % (name, why))
    return 0


if __name__ == "__main__":
    sys.exit(main())
