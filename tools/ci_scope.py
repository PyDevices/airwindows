# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Copyright (c) 2026 Brad Barnett
"""Say which CI jobs a change needs, so a change pays only for what it touches.

    python tools/ci_scope.py --base origin/main         # a branch against main
    python tools/ci_scope.py --files src/airwindows/plugins/Galactic.c
    python tools/ci_scope.py --all                      # everything
    python tools/ci_scope.py --base BASE --event push --github   # in Actions

It prints a JSON object and, with --github, writes the same answer as step
outputs and a step summary. It needs nothing installed.

- A change to documentation alone runs nothing. Documentation is a .md file,
  anything under docs/, LICENSE or NOTICE. docs/reference/plugins.md is not:
  the generator writes it, and the cpython job checks it.
- Anything else runs the cpython job. On a pull request it runs on 3.12
  alone, unless the C sources, the packaging or the pins changed; then, and
  on every push to main, it runs on 3.11, 3.12 and 3.13.
- The micropython job runs when the C sources, the generator, the build
  files, the pins, or the tests and example it runs changed.
- The reference job (every plug-in against upstream's C++) runs on a push to
  main and by hand, as before. It checks every plug-in when the generator,
  the shared kernel headers, the reference harness or the pins changed, and
  otherwise only the plug-ins whose kernels changed.
- Everything runs, every plug-in included, for a manual run, when there is
  no earlier commit to compare with, when a workflow or this tool changed,
  and for a deleted file outside the documentation.
"""

import argparse
import fnmatch
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Files that are documentation and nothing else.
#: The workflow's ``paths`` filter leaves out the same files.
DOCS = ("*.md", "docs/*", "LICENSE", "NOTICE", "*/LICENSE")
#: Documentation the generator writes: the cpython job checks it.
GENERATED_DOCS = ("docs/reference/plugins.md",)
#: Everything runs.
FULL = (".github/*", "tools/ci_scope.py")
#: The cpython matrix widens to every version on a pull request.
WIDE = ("src/*", "setup.py", "pyproject.toml", "manifest.py", "VERSION",
        "DEPENDENCIES.lock", "audioairwindows.pyi", "tools/awgen/templates/*")
#: The micropython job.
MICROPYTHON = ("src/*", "tools/awgen/*", "micropython.mk", "micropython.cmake",
               "manifest.py", "VERSION", "DEPENDENCIES.lock", "setup.py",
               "pyproject.toml", "third_party/airwindows/ORIGIN.txt",
               "tests/test_cross_runtime.py", "tests/test_audioairwindows.py",
               "examples/audioairwindows_simpletest.py")
#: Every plug-in against upstream. tools/awgen/templates only shapes the
#: Python and stub bindings, which the reference harness doesn't build.
REFERENCE_ALL = ("tools/awgen/*", "src/airwindows/kernel_common.h",
                 "src/airwindows/plugin.h", "tests/reference/*",
                 "DEPENDENCIES.lock", "third_party/airwindows/ORIGIN.txt")
REFERENCE_NOT = ("tools/awgen/templates/*",)
KERNELS = "src/airwindows/plugins/"
#: Plug-ins a reference runner checks; more changed than this takes more runners.
PER_SHARD = 16
SHARDS = 8
VERSIONS_ALL = ["3.11", "3.12", "3.13"]
VERSIONS_PR = ["3.12"]


def _match(path, patterns):
    return any(fnmatch.fnmatchcase(path, p) for p in patterns)


def is_docs(path):
    return _match(path, DOCS) and not _match(path, GENERATED_DOCS)


def scope(changed, deleted=(), event="pull_request", force_full=False):
    """What to run for ``changed`` (existing files) and ``deleted`` ones."""
    changed, deleted = sorted(set(changed)), sorted(set(deleted))
    paths = changed + deleted
    reasons = []
    if force_full:
        reasons.append("everything was asked for")
    reasons += ["%s changed" % p for p in paths if _match(p, FULL)]
    reasons += ["%s was deleted" % p for p in deleted if not is_docs(p)]

    if reasons:
        return {"full": True, "reasons": reasons, "cpython": True,
                "versions": VERSIONS_ALL, "micropython": True,
                "reference": "all", "plugins": [], "shards": SHARDS}

    code = [p for p in paths if not is_docs(p)]
    cpython = bool(code)
    wide = event != "pull_request" or any(_match(p, WIDE) for p in code)
    micropython = any(_match(p, MICROPYTHON) for p in code)

    reference, plugins, shards = "", [], 0
    if any(_match(p, REFERENCE_ALL) and not _match(p, REFERENCE_NOT)
           for p in code):
        reference, shards = "all", SHARDS
    else:
        plugins = sorted(os.path.basename(p)[:-2] for p in changed
                         if p.startswith(KERNELS) and p.endswith(".c"))
        if plugins:
            reference = "some"
            shards = min(SHARDS, -(-len(plugins) // PER_SHARD))
    return {"full": False, "reasons": [], "cpython": cpython,
            "versions": (VERSIONS_ALL if wide else VERSIONS_PR) if cpython
            else [], "micropython": micropython, "reference": reference,
            "plugins": plugins, "shards": shards}


def changed_between(base, head="HEAD"):
    """(existing, deleted) paths that differ between ``base`` and ``head``."""
    out = subprocess.run(
        ["git", "diff", "--name-status", "--no-renames",
         "%s...%s" % (base, head)],
        cwd=ROOT, check=True, capture_output=True, text=True).stdout
    changed, deleted = [], []
    for line in out.splitlines():
        status, _, path = line.partition("\t")
        (deleted if status.startswith("D") else changed).append(path)
    return changed, deleted


def known(commit):
    return subprocess.run(["git", "cat-file", "-e", commit + "^{commit}"],
                          cwd=ROOT, capture_output=True).returncode == 0


def summary(result):
    lines = ["### What CI runs", ""]
    if result["full"]:
        lines.append("Everything, because %s." % "; ".join(result["reasons"]))
    elif not result["cpython"]:
        lines.append("Nothing: only documentation changed.")
    else:
        lines.append("- cpython on %s" % ", ".join(result["versions"]))
        lines.append("- micropython: %s" % (
            "yes" if result["micropython"] else "no"))
        ref = {"all": "every plug-in", "": "no"}.get(
            result["reference"], ", ".join(result["plugins"]))
        lines.append("- reference (push to main and manual runs): %s" % ref)
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", help="compare HEAD with this commit")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--files", nargs="*", help="treat these as the changes")
    ap.add_argument("--event", default="pull_request",
                    help="the GitHub event: pull_request, push, ...")
    ap.add_argument("--all", action="store_true", help="run everything")
    ap.add_argument("--github", action="store_true",
                    help="write step outputs and the step summary")
    args = ap.parse_args(argv)

    changed, deleted = [], []
    full = args.all or args.event not in ("pull_request", "push")
    if args.files is not None:
        changed = args.files
    elif not full and args.base and set(args.base) - {"0"} \
            and known(args.base):
        changed, deleted = changed_between(args.base, args.head)
    else:
        full = True  # no earlier commit to compare with
    result = scope(changed, deleted, args.event, force_full=full)
    print(json.dumps(result, indent=2))

    if args.github:
        path = os.environ.get("GITHUB_STEP_SUMMARY")
        if path:
            with open(path, "a", encoding="utf-8") as f:
                f.write(summary(result))
        path = os.environ.get("GITHUB_OUTPUT")
        if path:
            with open(path, "a", encoding="utf-8") as f:
                f.write("cpython=%s\n" % str(result["cpython"]).lower())
                f.write("versions=%s\n" % json.dumps(result["versions"]))
                f.write("micropython=%s\n"
                        % str(result["micropython"]).lower())
                f.write("reference=%s\n" % result["reference"])
                f.write("plugins=%s\n" % " ".join(result["plugins"]))
                f.write("shards=%s\n"
                        % json.dumps(list(range(result["shards"]))))
                f.write("shard_count=%d\n" % result["shards"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
