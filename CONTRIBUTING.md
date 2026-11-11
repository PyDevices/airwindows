# Contributing

## Build and test on CPython

```sh
python -m venv .venv
.venv/bin/pip install --pre -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ setuptools numpy "omnipython-audiodsp>=0.6.10"
.venv/bin/pip install --no-build-isolation .
.venv/bin/python -m unittest discover -s tests
.venv/bin/python -m unittest discover -s tests -p 'check_*.py'
```

The wheel compiles every plug-in, about 530 C files, so the first install
takes a few minutes.

The tests are:

- `test_cpython_audioairwindows.py`: the surface, the errors, and what each
  effect does.
- `test_every_plugin.py`: every plug-in renders, in both variants, mono and
  stereo, and takes its parameters by name.
- `test_audioairwindows.py`: renders three effects and checks a hash of each.
  It runs as a script under MicroPython or CPython and exits non-zero on a
  mismatch.
- `test_cross_runtime.py`: runs `test_audioairwindows.py` under CPython and,
  with `MICROPYTHON` set to a unix MicroPython built with this module, checks
  that MicroPython prints exactly the same.
- `check_reference.py`: the generated kernels against Airwindows' own code,
  through `tests/reference/check.py`. It compiles each upstream plug-in from
  a checkout at `.cache/airwindows-upstream`, so it needs that and a C++
  compiler; without them it skips. It checks ten plug-ins by default;
  `AW_REFERENCE_PLUGINS=all` checks every one, which takes hours.

Everything the builds fetch or test against is pinned in
[`DEPENDENCIES.lock`](DEPENDENCIES.lock), and CI reads its pins from there.

## Build and release wheels

`omnipython-airwindows` is a native CPython distribution. `python -m build`
makes a local source archive and wheel.

A GitHub Release `vX.Y.Z`, matching the `VERSION` file (which is also where
`audioairwindows.__version__` comes from), starts the organization's reusable
publishing workflow. The pin is the `@publishing-vN` ref in
`.github/workflows/publish-release-packages.yml`, with
`build-kind: native-and-wasm`. It builds and validates exactly the number of
wheels `expected-wheel-count` in that file names, and the settings that choose
them are in `[tool.cibuildwheel]` in `pyproject.toml`. If the count changes,
change it in the same pull request. A release builds 30 wheels:

- CPython 3.11 to 3.15, plus the free-threaded 3.15t, on manylinux_2_28
  x86_64, manylinux_2_28 aarch64, Windows AMD64 and macosx_arm64: 24.
- CPython 3.13 to 3.14, Android API 21 arm64_v8a and x86_64: 4.
- CPython 3.13 to 3.14, Pyodide wasm32: 2.

Every wheel compiles all 530 plug-ins, so a release build takes much longer
than a test run. Each wheel except the 3.15 ones, Android and Pyodide
installs into a clean environment and runs the simple test.

To release, run the "Prepare release" workflow. It opens a pull request with
`VERSION` and the changelog; merging it makes the tag and the GitHub Release,
and the Release starts "Publish release packages". Every release goes to
TestPyPI and is attached to its GitHub Release. A pre-release
(`X.Y.ZrcN`, `X.Y.Z.devN`) stops there. A final release then goes to
production PyPI after a maintainer approves the `pypi` environment; that
upload is the `pypi` job in `publish-release-packages.yml`, not in the
reusable workflow, because PyPI's Trusted Publishing only matches the
workflow that runs the upload.

If a publish run is interrupted, run it again for the same tag:

```sh
gh workflow run publish-release-packages.yml --repo PyDevices/airwindows \
    -f release-ref=vX.Y.Z
```

## Build the unix MicroPython the tests use

Follow [Install](docs/get-started/install.md#micropython) with the unix
port, then:

```sh
MICROPYTHON=/path/to/micropython/ports/unix/build-standard/micropython \
    .venv/bin/python -m unittest tests/test_cross_runtime.py
/path/to/micropython/ports/unix/build-standard/micropython tests/test_audioairwindows.py
```

## The generated code

Everything under `src/airwindows/plugins/`, the registry, `selection.txt`,
`src/audioairwindows/module.c` and `types.c`, `src/cpython/audioairwindows.py`
and `audioairwindows.pyi` is written by `tools/awgen`. Don't edit them by
hand: change the generator or `tools/awgen/policy.json` and run it again.

```sh
git clone https://github.com/airwindows/airwindows .cache/airwindows-upstream
git -C .cache/airwindows-upstream checkout <the commit in DEPENDENCIES.lock>
python -m tools.awgen --check --jobs 4
python tests/reference/check.py --faults --jobs 4 Name ...
```

`policy.json` is where a plug-in's exceptions live, each with its reason:
members the single-precision variant keeps double (`wide`), plug-ins whose
single-precision loop is outside the bar (`fast: false`), and plug-ins not
carried (`skip`).

## Changing what an effect renders

A change to the generator must keep `tests/reference/check.py` passing for
every plug-in it touches: each variant within 2 int16 steps of upstream.
If it alters the three hashed renders, update `EXPECTED` and
`EXPECTED_FAST` in `test_audioairwindows.py` and say why in the commit.
