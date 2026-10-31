# Put an effect in a chain

Each effect is an audio sample: it plays a source, and anything that plays a
sample plays it. So it goes wherever an audiodsp effect would.

```python
import audioairwindows

drive = audioairwindows.PurestDrive(sample_rate=48000, drive=0.6)
comp = audioairwindows.ButterComp2(sample_rate=48000, compress=0.4)
verb = audioairwindows.Galactic(sample_rate=48000, replace=0.5, dry_wet=0.3)

drive.play(synth)      # any audiocore source: a synth, a WAV, a mixer voice
comp.play(drive)
verb.play(comp)
audio_out.play(verb)   # your board's audio output, or a mixer voice
```

Every node in the chain must have the source's `sample_rate` and
`channel_count`. Both are fixed when you build the node.

Change a parameter while it plays with `set()`; it takes effect from the next
block of 256 frames:

```python
verb.set(replace=0.2, bigness=0.8)
```

`clear()` empties the reverb's lines and the compressor's followers, as if
the node were new. A node keeps rendering after its source ends, so
Galactic's tail rings out. Once the tail has died, the reverb stops working
until new sound arrives.

`deinit()` frees the node's memory, which matters for Galactic on a board.
