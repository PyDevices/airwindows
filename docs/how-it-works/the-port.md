# The port

Every plug-in is generated from Airwindows' own source. `tools/awgen` reads
each one's `<Name>.cpp` (its parameters, defaults and constructor) and
`<Name>Proc.cpp` (its processing loop) at the pinned upstream commit and
writes `src/airwindows/plugins/<Name>.c`, a C translation you can read
against upstream side by side. The same description gives the MicroPython
types, the CPython classes and the stub, so every plug-in has one shape: a
node of the plug-in's name whose keyword arguments are its knobs.

The generated files are committed. They change only when the generator,
its policy or the upstream pin does; [CONTRIBUTING.md](../../CONTRIBUTING.md#the-generated-code)
has the command.

## What changed from upstream

- **int16 in and out, with no dither on the way out.** Upstream dithers
  its float output to 32 bits; here it is rounded once to int16.
- **Fixed random seeds** in place of `rand()`, for the noise and dither
  generators, so a node renders the same take twice.
- **Multiply-adds never fused, and a polynomial sine** on the fast path, so
  every interpreter and target renders the same bytes.
- **Parameters by name.** Each knob takes upstream's label as a Python
  name (`dry_wet`, `bigness`), from 0 to 1, clamped.
- **C++'s overloads kept.** Where upstream's C++ picks the float or long
  double version of a maths function, the C calls the same one.

One plug-in isn't carried: [the list](../reference/plugins.md#not-carried)
says which and why.

## Two variants of every loop

Each `<Name>.c` holds the loop twice. The reference variant keeps
upstream's arithmetic: double where upstream has double. Desktops and the
unix port run it.

The fast variant runs the loop in single precision, with no divide and no
libm call where it can do without, for parts whose FPU has neither a double
nor a divide (every ESP32). The S3's own cycle counts are why:

| Operation | Cycles on an ESP32-S3 |
|---|---|
| float multiply-add | about 5 |
| float divide (`__divsf3`) | 65 |
| `floorf` | 61 |
| double multiply-add | 165 |
| double compare, double to float | 50 each |

So the fast variant multiplies by reciprocals, worked out once a block
where the divisor is a setting and by Newton steps where it moves every
sample; turns small integer powers into multiplies; uses a polynomial
sine; and rounds to int16 without `floorf`. On the S3 the int16 samples go
in and out in one instruction each (`float.s` and `floor.s` with their
power-of-two scale), which gives the same values as the C a desktop runs. Code that runs once a block,
such as working out filter coefficients from the knobs, keeps upstream's
double.

Three more changes save time without changing a sample. A vibrato phase
that only grows by a step and wraps to zero, as Galactic's does, is kept
in fixed point with 60 fractional bits, so adding the step is two integer
adds. The air residue some older plug-ins add to their input is worked out
only when the input is zero, the one case where it changes the sum. And a
value upstream works out for both arms of a branch is worked out inside the
arm that uses it.

Single precision isn't close enough for every plug-in. A long recursive
filter, or a phase that grows for seconds, drifts from upstream by more
than the accuracy bar allows. Those plug-ins run the reference arithmetic
in the fast slot too, so they sound the same on a board at a higher cost in
time. [The list](../reference/plugins.md#full-precision-on-boards) names
them, with how far their single-precision loop strayed.

ESP32 firmware builds only the fast variant and other targets only the
reference; `AIRWINDOWS_VARIANT` (`fast` or `ref`) overrides it, and
`audioairwindows.FAST` says which one a build runs.

## How close it stays

`tests/reference/check.py` compiles each plug-in's upstream C++ beside its
generated kernel and holds both variants to 2 int16 steps of upstream's
output at every sample: at 44.1, 48, 96 and 192 kHz, over seven settings of
the knobs. Upstream gets the same seeds, so dithered and noisy plug-ins
compare sample for sample. It also plants faults the comparison has to
catch. [Accuracy](../reference/accuracy.md) has every plug-in's figures.
MicroPython and CPython render identical bytes
(`tests/test_audioairwindows.py`, run under both by
`tests/test_cross_runtime.py`).

## What it costs

Flash, for ESP32-S3 firmware with MicroPython and audiodsp: the default
140 plug-ins add about 985 kB to the image, which comes to 3,098,400 bytes.
That fits an 8 MB board's app partition with 9 % to spare and leaves about
4.6 MB for files. A plug-in averages about 6 kB of code; the largest,
kRockstar2, is 37 kB. Choose fewer with `AIRWINDOWS_PLUGINS`
([Install](../get-started/install.md#choose-the-plug-ins)) when flash is
tight.

Time, on a desktop (an Intel Core Ultra 7 155H, 48 kHz stereo, from
`tools/bench.py`, which pulls 256-frame blocks through the node the way an
audio output does):

| Effect | MicroPython unix | CPython |
|---|---|---|
| Galactic | 0.27 to 0.37 % | 0.37 to 0.49 % |
| PurestDrive | 0.16 to 0.20 % | 0.23 to 0.25 % |
| ButterComp2 | 0.36 to 0.38 % | 0.38 to 0.40 % |
| All three | 0.88 to 0.90 % | 0.92 % |

On an ESP32-S3 at 240 MHz with octal PSRAM (a Waveshare ESP32-S3-Touch-LCD-7,
MicroPython, same script), as a share of one core. The bench pulls each
block twice over: from Python, as it always has, and from C with
`audiopump.pull`, as an audio output does. Pulling from Python allocates,
so the collector runs every few blocks and scans the noise and Galactic's
delay lines, which costs up to a fifth of a core and moves with the heap.
The second column is the effect alone:

| Effect | Pulled from Python | Pulled from C |
|---|---|---|
| Galactic | 36.1 % | 25.7 % |
| PurestDrive | 11.1 % | 3.5 % |
| ButterComp2 | 19.8 % | 12.1 % |
| All three | 50.5 % | 39.7 % |

Before the one-instruction int16 in and out, the same firmware measured
37.3, 12.0, 20.9 and 53.6 % pulled from Python (26.8, 4.4, 13.3 and 42.9 %
from C). The hand-written ports these three replaced measured 41.0, 13.2,
20.5 and 58.3 % from Python on the same board.

A plug-in's cost on a board depends on whether it runs the fast path;
[the list](../reference/plugins.md#full-precision-on-boards) names the ones
that don't.
