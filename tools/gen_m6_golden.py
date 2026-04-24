#!/usr/bin/env python3
"""
Generate M6 golden reference from Python PT3 simulator (full fidelity).

Uses pt3_simulator.simulate() unmodified — the same function that achieves
19/19 bit-exact match vs VTII PSG reference on real songs. This is the
authoritative test oracle for the 6502 player.

Format tests/m6_ref_<fname>.bin:
  magic        'M6\x00\x01'          (4 bytes)
  num_frames   u16 LE                (2 bytes)
  frames       14 bytes x N          (14 raw AY register values R0..R13 per frame)
"""

import sys, struct, os, hashlib
sys.path.insert(0, '/home/linumax/commodore/jukebox/pt3_python_sim/pt3_python_sim')

from pt3_simulator import PT3Module, simulate

OUT_DIR = 'tests'
FILES = ['luchibobra.pt3', 'blobbzgame.pt3', 'yerzmyey.pt3']
NUM_FRAMES = 2000  # ~40 seconds at 50 Hz

for fname in FILES:
    path = f'tests/pt3/{fname}'
    mod = PT3Module(path)
    psg = simulate(mod, max_frames=NUM_FRAMES, verbose=False)

    state = [0] * 14
    bout = bytearray(b'M6\x00\x01')
    bout += struct.pack('<H', len(psg.frames))
    for f in psg.frames:
        for r, v in f.items():
            state[r] = v
        bout += bytes(state)

    out_path = f'{OUT_DIR}/m6_ref_{fname.replace(".pt3","")}.bin'
    with open(out_path, 'wb') as fp:
        fp.write(bytes(bout))

    md5 = hashlib.md5(bytes(bout)).hexdigest()
    print(f"{out_path}: {len(bout)} bytes, {len(psg.frames)} frames, md5={md5}")
