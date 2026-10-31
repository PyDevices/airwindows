# The node

Every plug-in in [the list](plugins.md) is a node of the same shape. Every parameter is the plug-in's own 0 to 1 knob, under its own name and with
its own default. Values outside 0 to 1 are clamped. Every node also takes
`sample_rate` (default 48000) and `channel_count` (1 or 2, default 2), fixed
at construction. A mono node runs the stereo effect with its one channel on
both sides.

Methods on every one: `play(source)`, `stop()`, `set(**parameters)`,
`get(name)`, `parameters()`, `clear()`, `deinit()`, and the `playing`
property.

`parameters()` describes the knobs, so a program can draw a panel for any
plug-in without knowing it in advance: one `(keyword, name, default)` per
knob, in upstream's order, the name being upstream's display name.
`get(name)` says where a knob is now, after clamping.

```python
>>> audioairwindows.Galactic().parameters()[:2]
(('replace', 'Replace', 0.5), ('brightness', 'Brightness', 0.5))
```

The three below were the first the module carried, described here in more
detail than upstream's one line.

## Galactic

A big, dense, true-stereo reverb.

| Parameter | Default | What it does |
|---|---|---|
| `replace` | 0.5 | How much new sound replaces the tail. Lower rings longer; 0 holds what's there and takes nothing new in. |
| `brightness` | 0.5 | Darkens the tail when lowered. |
| `detune` | 0.5 | Speed of the vibrato that keeps the tail from ringing on one pitch. |
| `bigness` | 1.0 | Size of the space. |
| `dry_wet` | 1.0 | 0 is the input alone, 1 the reverb alone. |

Memory: about 530 kB of delay lines on a board and 1 MB on a desktop, sized
for `bigness` 1.

## PurestDrive

A gentle saturation that eases off on quiet passages and on the highs.

| Parameter | Default | What it does |
|---|---|---|
| `drive` | 0.0 | Amount of saturation; 0 passes the input through untouched. |

## ButterComp2

A smooth compressor with no threshold, attack or release to set.

| Parameter | Default | What it does |
|---|---|---|
| `compress` | 0.0 | The whole amount, from none to a lot. It also raises the input by up to 14 dB. |
| `output` | 0.5 | Output level: 0.5 is unity, 1.0 is +6 dB. |
| `dry_wet` | 1.0 | 0 is the input alone. |
