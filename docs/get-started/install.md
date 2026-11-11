# Install

The effects are audiodsp audio nodes, so audiodsp comes first: version
0.6.10 or later, on either Python.

## CPython

```sh
pip install omnipython-airwindows
```

That installs a prebuilt wheel with every plug-in in it, so nothing
compiles, and [omnipython-audiodsp](https://pypi.org/project/omnipython-audiodsp/)
beside it. Python 3.11 or later.

A wheel is published for:

- Linux, x86_64 and aarch64 (64-bit Raspberry Pi OS), glibc 2.28 or later
- Windows, 64-bit
- macOS on Apple Silicon
- Android, arm64 and x86_64, and Pyodide, on Python 3.13 and 3.14

Python 3.15 and its free-threaded build have wheels on Linux, Windows and
macOS. A pre-release (`.devN`, `rcN`) is published to TestPyPI first, and
`pip` skips pre-releases unless you ask for one:

```sh
pip install --pre -i https://test.pypi.org/simple/ \
    --extra-index-url https://pypi.org/simple/ omnipython-airwindows
```

With `uv`, add `--index-strategy unsafe-best-match`, or it resolves the
name on PyPI before TestPyPI and installs the wrong version:

```sh
uv pip install --prerelease allow --index-strategy unsafe-best-match \
    -i https://test.pypi.org/simple/ \
    --extra-index-url https://pypi.org/simple/ omnipython-airwindows
```

### Build from source

Anywhere else (Alpine Linux, Intel Macs, 32-bit Python), `pip` has no
wheel for you, so build the extension yourself. It needs a C compiler and a
few minutes, because it compiles about 530 plug-ins:

```sh
pip install git+https://github.com/PyDevices/airwindows
```

## MicroPython

Build this repository into the firmware beside audiodsp, as user C modules.
The module uses audiodsp's `audiocore` sample protocol and its pump lock, and
finds their headers through audiodsp, so the two always build together.

Put both checkouts in one folder:

```sh
mkdir modules && cd modules
git clone https://github.com/PyDevices/audiodsp
git clone https://github.com/PyDevices/airwindows
./audiodsp/scripts/fetch_deps.sh
```

On a Make port (unix, windows), point `USER_C_MODULES` at that folder:

```sh
make -C micropython/ports/unix USER_C_MODULES=/path/to/modules
```

On a CMake port (esp32, rp2), add a `micropython.cmake` to the folder that
includes both, and point `USER_C_MODULES` at it:

```cmake
include(${CMAKE_CURRENT_LIST_DIR}/audiodsp/micropython.cmake)
include(${CMAKE_CURRENT_LIST_DIR}/airwindows/micropython.cmake)
```

Or, on MicroPython 1.29 or later, include both manifests from the manifest
your build already uses:

```python
include("/path/to/modules/audiodsp/manifest.py")
include("/path/to/modules/airwindows/manifest.py")
```

### Choose the plug-ins

A Make build carries every plug-in. A CMake build, which is what an ESP32
or RP2 firmware is, carries the 140 marked **board** in
[the list](../reference/plugins.md): upstream's Basic and Recommended
collections, plus Galactic, PurestDrive and ButterComp2. To carry others,
set `AIRWINDOWS_PLUGINS` to names, collections (`Basic`, `Recommended`,
`Latest`), `default` or `all`, separated by spaces or commas, either in the
environment or on the command line:

```sh
make -C micropython/ports/unix USER_C_MODULES=/path/to/modules \
    AIRWINDOWS_PLUGINS="Galactic Pressure4 kCosmos"
idf.py -D USER_C_MODULES=/path/to/modules/micropython.cmake \
    -D AIRWINDOWS_PLUGINS="default Pressure4" build
```

A name the build doesn't know stops it with that name. The choice is a
build setting rather than a manifest line, because a MicroPython manifest's
`c_module()` takes only a path.

Check it with `import audioairwindows; print(audioairwindows.__version__)`.
`audioairwindows.__revision__` names the commit the build came from.

Galactic keeps about 530 kB of delay lines per node on a board, which needs
PSRAM, and about 1 MB on a desktop, where they're double precision. Give
the unix port the room: `micropython -X heapsize=8M`.

There's no CircuitPython build yet; see the [roadmap](../../ROADMAP.md).
