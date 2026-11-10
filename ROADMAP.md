# Roadmap

- **CircuitPython.** A binding for CircuitPython-compatible firmware, so the
  plug-ins build there as they do into MicroPython.
- **Single precision for more plug-ins on boards.** About half still run
  full-precision arithmetic on boards with no double FPU, because their
  single-precision loop misses the accuracy bar; one family at a time.
- **The fast path on more boards.** The ESP32-P4 and the original ESP32 have
  no double in their FPUs either. Measure each with the fast path on, and
  turn it on where it helps.
- **A release on PyPI**, so `pip install omnipython-airwindows` works with no
  extra index. The prebuilt wheels exist for each release; what's left is the
  final release that puts them on PyPI.
