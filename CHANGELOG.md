# Changelog

## Unreleased

- Every node describes its knobs: `parameters()` gives each one's keyword,
  upstream's display name and its default, and `get(name)` reads where a
  knob is ([the node](docs/reference/effects.md)).
- The desktop wheel builds with MSVC on Windows.

- Every Airwindows plug-in but one, 528 in all, each a class of its own
  name: [the list](docs/reference/plugins.md), by category. They are
  generated from upstream's source by `tools/awgen`, Galactic, PurestDrive
  and ButterComp2 included, and each is checked against upstream's own C++
  at four sample rates ([accuracy](docs/reference/accuracy.md)).
- A board build carries upstream's Basic and Recommended collections, 140
  plug-ins; `AIRWINDOWS_PLUGINS` chooses others
  ([Install](docs/get-started/install.md#choose-the-plug-ins)).
- Galactic's and ButterComp2's renders changed by a step here and there:
  the generated code follows upstream's arithmetic more closely than the
  hand ports did.

- ESP32-S3 firmware runs a fast path that spends no time in software
  doubles, divides or libm calls, so all three effects chained fit on one
  core with room to spare. It meets the same accuracy bar against upstream
  as the reference port; `audioairwindows.FAST` says which one a build runs.
  [The port](docs/how-it-works/the-port.md#the-fast-path-on-the-esp32-s3)
  has the figures.
- `tools/bench.py` also times all three chained.

- `audioairwindows.__revision__` names the commit a build came from, on
  MicroPython and CPython.
- A `manifest.py`, so a MicroPython 1.29 firmware manifest can include the
  module, and `audioairwindows.pyi`, a type stub for editors.
- `examples/audioairwindows_simpletest.py`, the smallest program that shows
  the module working.
- Pins live in `DEPENDENCIES.lock`. The tests are renamed: the hash check is
  `tests/test_audioairwindows.py` and runs on MicroPython in CI, and the
  check against Airwindows' own code is `tests/check_reference.py`.

## 0.1.0

The first release: Airwindows Galactic, PurestDrive and ButterComp2 as
audiodsp audio nodes, for CPython and for MicroPython firmware built with
audiodsp 0.6.10 or later.
