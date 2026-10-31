# Your first program

[examples/galactic_tail.py](../../examples/galactic_tail.py) is the README's
example with its steps spelled out. It plays 20 ms of noise into Galactic and
prints how loud the tail is every quarter second or so:

```sh
python examples/galactic_tail.py
```

```
0.00 s    247
0.26 s    343
0.51 s    307
0.77 s    243
1.02 s    325
1.28 s    203
1.54 s    194
1.79 s    194
2.05 s    155
2.30 s    144
2.56 s     86
2.82 s     92
```

A MicroPython built with the module prints the same lines. Lower `replace`
and the numbers fall more slowly; raise it and the tail dies sooner.
