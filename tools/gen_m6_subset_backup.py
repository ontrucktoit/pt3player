#!/usr/bin/env python3
"""
Generate M6 subset golden reference from Python simulator.

M6 subset semantics:
- Pattern engine, notes, samples, envelope, speed change: ENABLED
- Ornaments: DISABLED (ch.ornament_num forced to 0)
- Effects 1-5, 8 (gliss, portamento, smpos, orpos, vibrato, env-slide): DISABLED
- Effect 9 (speed change): ENABLED

Strategy: monkey-patch apply_row_to_channel and replace the spec_cmd dispatch
block to drop effects we don't support in M6. Produces golden ref binaries
tests/m6_ref_<fname>.bin with format:

  magic        'M6\x00\x01'          (4 bytes)
  num_frames   u16 LE                (2 bytes)
  frames       14 bytes × N          (14 raw AY register values R0..R13 per frame)
"""

import sys, struct, os, hashlib
sys.path.insert(0, '/home/linumax/commodore/jukebox/pt3_python_sim/pt3_python_sim')

import pt3_simulator as sim_mod
from pt3_simulator import PT3Module

# ---- Monkey-patch apply_row_to_channel: never set ornament ----
_orig_apply = sim_mod.apply_row_to_channel

def patched_apply(ch, row, mod):
    # Call original but with ornament fields stripped from the row first
    # Save and temporarily clear ornament attrs on the row object
    orig_orn = row.ornament
    orig_exp0 = getattr(row, 'ornament_explicit_zero', False)
    row.ornament = None
    # Monkey-patch ornament_explicit_zero getter by setting attribute to False
    row.ornament_explicit_zero = False
    _orig_apply(ch, row, mod)
    row.ornament = orig_orn
    row.ornament_explicit_zero = orig_exp0
    # Defensive: after apply, force ornament state to 0
    ch.ornament_num = 0
    ch.pos_in_ornament = 0

sim_mod.apply_row_to_channel = patched_apply

# ---- For effects: we need to intercept the spec_cmd dispatch inside simulate() ----
# Strategy: modify row.spec_cmd right before apply, keep only cmd 0x09.
# We wrap decode_next_row to strip non-0x09 spec_cmd from rows before simulator sees them.
from pt3_pattern_decoder import decode_next_row as _orig_decode

def patched_decode(data, state):
    row = _orig_decode(data, state)
    if row is not None and row.spec_cmd is not None:
        # Keep only cmd 0x09 (speed change). Drop everything else.
        if row.spec_cmd.cmd != 0x09:
            row.spec_cmd = None
    return row

# Patch in sim_mod namespace where simulate() looks for it
sim_mod.decode_next_row = patched_decode

# ---- Generate ----
OUT_DIR = 'tests'
FILES = ['luchibobra.pt3', 'blobbzgame.pt3', 'yerzmyey.pt3']
NUM_FRAMES = 2000  # ~40 seconds at 50 Hz

for fname in FILES:
    path = f'tests/pt3/{fname}'
    mod = PT3Module(path)
    psg = sim_mod.simulate(mod, max_frames=NUM_FRAMES, verbose=False)
    
    # Accumulate diff-frames into full per-frame state
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
