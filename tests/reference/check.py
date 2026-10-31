# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Copyright (c) 2026 Brad Barnett
"""Every generated kernel against upstream's own C++.

    python tests/reference/check.py [Name ...] [--jobs N] [--faults]
                                    [--shard I/N]

Builds tests/reference/compare.cpp once per plug-in, with upstream's
sources (from AIRWINDOWS_UPSTREAM, or .cache/airwindows-upstream: a checkout
of github.com/airwindows/airwindows at the commit third_party/airwindows/
ORIGIN.txt names) and the generated kernel, and runs it at 44.1, 48, 96 and
192 kHz over seven parameter settings: upstream's defaults, all 0, all 1,
all 0.25, all 0.75 and two seeded random draws.

A kernel passes when, at every sample of every case, each variant is at
most 2 int16 steps from upstream's output rounded to int16: 1 LSB of error,
plus the rounding on each side. The hand ports this generator replaced
measured the same way (Galactic's worst was 2.48 LSB before rounding). The results go to
tests/reference/results.json, and --report turns a full set of them into
docs/reference/accuracy.md.

A plug-in with a hand-written fixed-point fast variant (policy.json,
"fixed") is built a second time with AW_FIXED=1 and that variant is held to
the same bar, as `fixed`.

--faults plants two faults in each plug-in and fails if the comparison
misses the first: a gain error of 1 part in 4096 on one side (1 in 256 for a
plug-in too quiet for that to show), and a parameter read from the wrong
place.
"""

import argparse
import json
import os
import random
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BIN = HERE / "bin"
UPSTREAM = Path(os.environ.get(
    "AIRWINDOWS_UPSTREAM", ROOT / ".cache" / "airwindows-upstream")) \
    / "plugins" / "LinuxVST" / "src"
INDEX = json.loads((ROOT / "tools" / "awgen" / "plugins.json").read_text())
CXX = os.environ.get("CXX") or shutil.which("c++") or "g++"
CC = os.environ.get("CC") or shutil.which("cc") or "gcc"
RATES = [44100, 48000, 96000, 192000]
BAR_LSB = 2


def param_sets(name):
    params = INDEX[name]["params"]
    n = len(params)
    rng = random.Random(name)
    sets = [("defaults", [p["default"] for p in params]),
            ("zeros", [0.0] * n), ("ones", [1.0] * n),
            ("quarter", [0.25] * n), ("three_quarters", [0.75] * n),
            ("random1", [round(rng.random(), 4) for _ in range(n)]),
            ("random2", [round(rng.random(), 4) for _ in range(n)])]
    if n == 0:
        sets = sets[:1]
    return sets


def build(name, kernel=None, tag="", defines=()):
    """The harness binary for one plug-in. `kernel` swaps in another kernel
    source, for a planted fault; `defines` are -D options for the kernel."""
    BIN.mkdir(exist_ok=True)
    exe = BIN / (name + tag)
    src = UPSTREAM / name
    kernel = kernel or ROOT / "src" / "airwindows" / "plugins" / (name + ".c")
    sources = [HERE / "compare.cpp", src / (name + ".cpp"),
               src / (name + "Proc.cpp"), kernel,
               ROOT / "src" / "airwindows" / "kernel_common.h"]
    if exe.exists() and all(s.stat().st_mtime <= exe.stat().st_mtime
                            for s in sources):
        return exe
    seeds = "".join("(p)->%s = aw_seed(%d); " % (s, i)
                    for i, s in enumerate(INDEX[name]["seeds"]))
    obj = BIN / (name + tag + ".o")
    subprocess.run([CC, "-std=c11", "-O2", "-w", "-c", "-I",
                    str(ROOT / "src"), *["-D" + d for d in defines],
                    "-o", str(obj), str(kernel)],
                   check=True, timeout=600)
    subprocess.run(
        [CXX, "-O1", "-w", "-std=c++14", "-fwrapv", "-include",
         str(HERE / "harness_rand.h"), "-I", str(HERE), "-I", str(src),
         "-I", str(ROOT / "src"), '-DPLUGIN_H="%s.h"' % name,
         "-DPLUGIN=" + name, "-DAW_DESC=aw_plugin_" + name,
         "-DAW_SET_SEEDS(p)=%s" % (seeds or "(void)(p);"), "-o", str(exe)] +
        ([] if INDEX[name]["params"] else ["-DAW_NO_PARAMS"]) + [
         str(HERE / "compare.cpp"), str(src / (name + ".cpp")),
         str(src / (name + "Proc.cpp")), str(obj)],
        check=True, timeout=600)
    obj.unlink()
    return exe


def run_cases(name, exe, fault=0, rates=RATES, sets=None):
    rows = []
    for rate in rates:
        for label, values in sets or param_sets(name):
            r = subprocess.run([str(exe), str(rate), str(fault)] +
                               ["%.6g" % v for v in values],
                               capture_output=True, text=True, timeout=600)
            if r.returncode:
                rows.append({"rate": rate, "set": label,
                             "error": r.stderr.strip()[-300:]})
                continue
            row = json.loads(r.stdout)
            row["set"] = label
            rows.append(row)
    return rows


def has_fixed(name):
    return "AW_FIXED" in (ROOT / "src" / "airwindows" / "plugins" /
                          (name + ".c")).read_text()


def with_fixed(rows, fixed_rows):
    """rows, each with the fixed build's fast variant as `fixed`."""
    for row, other in zip(rows, fixed_rows):
        if "fast" in other:
            row["fixed"] = other["fast"]
        elif "error" in other:
            row["error"] = other["error"]
    return rows


def variants(rows):
    return [v for v in ("ref", "fast", "fixed") if any(v in r for r in rows)]


def summarize(rows):
    """The worst case of each variant. A case where upstream's own output
    goes infinite or NaN has nothing to compare against: it is counted and
    named, and left out of the bar."""
    out = {"cases": len(rows)}
    held = [r for r in rows if r.get("finite") is not False]
    for v in variants(rows):
        worst = max((r[v]["max_lsb"] for r in held if v in r), default=None)
        err = max((r[v]["err_db"] for r in held if v in r), default=None)
        out[v] = {"max_lsb": worst, "worst_err_db": err}
    out["errors"] = sum(1 for r in rows if "error" in r)
    out["nonfinite"] = ["%g %s" % (r["rate"], r["set"]) for r in rows
                        if r.get("finite") is False]
    out["pass"] = out["errors"] == 0 and all(
        out[v]["max_lsb"] is not None and out[v]["max_lsb"] <= BAR_LSB
        for v in variants(rows))
    return out


def plant_wrong_param(name, tmp):
    """The kernel with its first parameter's offset pointing at the second
    (or, for a one-parameter plug-in, at the state's first member)."""
    text = (ROOT / "src" / "airwindows" / "plugins" / (name + ".c")
            ).read_text()
    out = []
    for line in text.splitlines():
        if line.startswith("static const uint32_t aw_%s_offsets_" % name):
            head, body = line.split("{", 1)
            items = re.findall(r"offsetof\([^)]*\)", body)
            if len(items) > 1:
                items[0] = items[1]
            else:
                items[0] = "12"
            line = head + "{" + ", ".join(items) + "};"
        out.append(line)
    path = tmp / (name + "_fault.c")
    path.write_text("\n".join(out) + "\n")
    return path


def check(name, faults):
    fixed = has_fixed(name)
    try:
        exe = build(name)
        fixed_exe = build(name, tag="_fixed", defines=["AW_FIXED=1"]) \
            if fixed else None
    except subprocess.CalledProcessError as e:
        return name, {"pass": False, "build_error": str(e)[-300:]}, []

    def run(exe, fixed_exe, **kw):
        rows = run_cases(name, exe, **kw)
        if fixed_exe:
            rows = with_fixed(rows, run_cases(name, fixed_exe, **kw))
        return rows

    def caught_by_any(rows):
        return any(r.get(v, {}).get("max_lsb", 0) > BAR_LSB
                   for r in rows for v in ("ref", "fast", "fixed"))

    rows = run(exe, fixed_exe)
    summary = summarize(rows)
    if faults and INDEX[name]["params"]:
        # Planted faults, each at one rate over the settings that move it.
        caught = {}
        gain = run(exe, fixed_exe, fault=1, rates=[48000])
        caught["gain"] = caught_by_any(gain)
        if not caught["gain"]:
            # 1 part in 4096 moves no sample past the bar when the output
            # stays under about 12000; a plug-in that quiet gets 1 in 256.
            gain = run(exe, fixed_exe, fault=2, rates=[48000])
            caught["gain"] = caught_by_any(gain)
        tmp = BIN / "faults"
        tmp.mkdir(parents=True, exist_ok=True)
        planted = plant_wrong_param(name, tmp)
        fexe = build(name, planted, tag="_fault")
        ffixed = build(name, planted, tag="_fault_fixed",
                       defines=["AW_FIXED=1"]) if fixed else None
        wrong = run(fexe, ffixed, rates=[48000], sets=param_sets(name)[5:])
        caught["wrong_param"] = caught_by_any(wrong)
        summary["faults_caught"] = caught
    return name, summary, rows


def report(results, path):
    """docs/reference/accuracy.md from a full sweep's results."""
    policy = json.loads((ROOT / "tools" / "awgen" / "policy.json")
                        .read_text())
    lines = [
        "<!-- GENERATED by tests/reference/check.py --report. "
        "Do not edit. -->", "",
        "# Accuracy", "",
        "Each plug-in is compiled beside upstream's own C++ at the pinned "
        "commit and both are fed the same int16 signal at 44.1, 48, 96 and "
        "192 kHz, over seven settings of the parameters: upstream's "
        "defaults, all 0, all 1, all 0.25, all 0.75 and two random draws. "
        "Upstream's noise and `rand()` get the seeds the port uses, so "
        "dithered output compares sample for sample. The figures are the "
        "worst distance from upstream's output rounded to int16, in int16 "
        "steps, over every sample of every case. The bar is %d: 1 step of "
        "error plus the rounding on each side." % BAR_LSB, "",
        "`full` is the full-precision variant every desktop runs. `single` "
        "is the variant a board without a double FPU runs; where it reads "
        "`= full`, the plug-in's single-precision loop strayed outside the "
        "bar and boards run the full one ([why](plugins.md#full-precision-"
        "on-boards)).", "",
        "Two faults are planted in each plug-in with parameters, to show "
        "the comparison would notice: a gain error of 1 part in 4096, which "
        "it must catch, and the first parameter read from the wrong place. "
        "A wrong parameter can be one the settings tried barely move, so a "
        "miss there is shown, not failed. Cases where upstream's own output "
        "goes infinite or NaN have nothing to compare against and are named "
        "instead.", "",
        "| Plug-in | full | single | Faults caught | Not compared |",
        "|---|---|---|---|---|"]
    for name in sorted(results):
        s = results[name]["summary"]
        single = s.get("fast", {}).get("max_lsb")
        if policy.get(name, {}).get("fast") is False:
            single = "= full"
        f = s.get("faults_caught")
        faults = "no parameters" if f is None else ", ".join(
            k.replace("_", " ") for k, v in sorted(f.items()) if v) or "none"
        if f and not f.get("wrong_param"):
            faults += " (wrong parameter missed)"
        lines.append("| %s | %s | %s | %s | %s |" % (
            name, s.get("ref", {}).get("max_lsb"), single, faults,
            ", ".join(s.get("nonfinite", []))))
    path.write_text("\n".join(lines) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*")
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--faults", action="store_true")
    ap.add_argument("--out", type=Path, default=HERE / "results.json")
    ap.add_argument("--report", action="store_true",
                    help="write docs/reference/accuracy.md from the "
                    "results and stop")
    ap.add_argument("--shard", default="",
                    help="I/N: check every Nth plug-in from the Ith, so N "
                    "machines can share a full sweep")
    args = ap.parse_args(argv)
    if args.report:
        report(json.loads(args.out.read_text()),
               ROOT / "docs" / "reference" / "accuracy.md")
        return 0
    names = args.names or sorted(
        n for n in INDEX
        if (ROOT / "src" / "airwindows" / "plugins" / (n + ".c")).exists())
    if args.shard:
        i, n = (int(x) for x in args.shard.split("/"))
        names = names[i::n]
    results = json.loads(args.out.read_text()) if args.out.exists() else {}
    with ThreadPoolExecutor(args.jobs) as pool:
        for name, summary, rows in pool.map(
                lambda n: check(n, args.faults), names):
            results[name] = {"summary": summary, "cases": rows}
            s = summary
            print("%-24s %s ref %s fast %s%s%s" % (
                name, "PASS" if s.get("pass") else "FAIL",
                s.get("ref", {}).get("max_lsb"),
                s.get("fast", {}).get("max_lsb"),
                " fixed %s" % s["fixed"]["max_lsb"] if "fixed" in s else "",
                " faults %s" % s["faults_caught"] if "faults_caught" in s
                else ""), flush=True)
            args.out.write_text(json.dumps(results, indent=1,
                                           sort_keys=True) + "\n")
    # The gain fault changes every plug-in that makes a sound; a comparison
    # that misses it proves nothing. A wrong parameter can be one the
    # settings tried barely move, so a miss there is reported, not failed.
    failed = [n for n in names if not results[n]["summary"].get("pass") or
              results[n]["summary"].get("faults_caught", {}).get("gain")
              is False]
    print("%d of %d within %d LSB" % (len(names) - len(failed), len(names),
                                     BAR_LSB))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
