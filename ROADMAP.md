# Roadmap

- **CircuitPython.** A binding for CircuitPython-compatible firmware, so the
  plug-ins build there as they do into MicroPython.
- **Single precision for more plug-ins on boards.** About half run upstream's
  full-precision arithmetic on boards with no double FPU, because their
  single-precision loop strays outside the accuracy bar. Bring them in one
  family at a time, cheapest first.
- **The fast path on more boards.** The ESP32-P4 and the original ESP32 have
  no double in their FPUs either. Measure each with the fast path on, and
  turn it on where it helps.
- **A PyPI release**, so `pip install airwindows-py` works without git, with
  prebuilt wheels so the install doesn't compile every plug-in.
