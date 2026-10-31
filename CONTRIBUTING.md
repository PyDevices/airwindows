# Contributing

## Build and test on CPython

```sh
python -m venv .venv
.venv/bin/pip install setuptools numpy "pydevices-audiodsp>=0.6.10"
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
