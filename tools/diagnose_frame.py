"""Run player_tick frame-by-frame, dump shadow_ay state, ZP state, and a
trace of which subroutine ran at each frame around a target frame.
"""
import sys, os
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pt3_python_sim'))
sys.path.insert(0, 'tests')

from harness import (build_sim, load_bin, call_sub, find_symbol, BUILD_DIR,
                     PLAYER_BASE, PLAYER_INIT, assemble_player, TESTS_DIR)

PLAYER_INIT_SONG = PLAYER_BASE + 0x2A
PLAYER_TICK = PLAYER_BASE + 0x2D

assemble_player()

FNAME = sys.argv[1] if len(sys.argv) > 1 else 'mmcm_xiaomi.pt3'
TARGET = int(sys.argv[2]) if len(sys.argv) > 2 else 279

mpu, _ = build_sim()
load_bin(mpu, BUILD_DIR / "player.bin", 0x3000)
BASE = 0x8000
pt3 = (TESTS_DIR / "pt3" / FNAME).read_bytes()
for i, b in enumerate(pt3):
    mpu.memory[BASE + i] = b
call_sub(mpu, PLAYER_INIT)
mpu.a = BASE >> 8; mpu.x = BASE & 0xFF
call_sub(mpu, PLAYER_INIT_SONG)

# Find some symbol addresses
sym_shadow = find_symbol("shadow_ay")
ch_state_syms = []
for s in ["pb_speed", "pb_tick_in_row", "pb_position_idx",
          "pb_current_pattern", "pb_current_line", "pb_current_pat_len",
          "pb_env_period_lo", "pb_env_period_hi", "pb_env_shape", "pb_r13_dirty"]:
    try:
        ch_state_syms.append((s, find_symbol(s)))
    except Exception:
        pass

# Try to find per-channel state arrays
for s in ["ch_a_sample_ptr", "ch_a_orn_ptr", "ch_a_skip_counter",
          "ch_a_note", "ch_a_volume", "ch_a_sample_idx", "ch_a_orn_idx",
          "ch_a_sample_pos", "ch_a_orn_pos", "ch_a_sample_tick"]:
    try:
        ch_state_syms.append((s, find_symbol(s)))
    except Exception:
        pass

print(f"File: {FNAME}, target frame: {TARGET}")
print(f"Symbols found: {len(ch_state_syms)}")
print()

# Run frames, dumping state around target
def dump_state(label, mpu, syms_list, sym_shadow):
    print(f"  {label}:")
    print(f"    AY R0..R13 = ", end="")
    print(" ".join(f"{mpu.memory[sym_shadow+r]:02X}" for r in range(14)))
    for s, addr in syms_list[:25]:
        print(f"    {s} @ ${addr:04X} = ${mpu.memory[addr]:02X}")

steps_per_frame = []
for f in range(1, TARGET + 5):
    if f == TARGET - 1 or f == TARGET or f == TARGET + 1:
        print(f"=== before frame {f} ===")
        dump_state("STATE", mpu, ch_state_syms, sym_shadow)
        c = call_sub(mpu, PLAYER_TICK)
        steps_per_frame.append(c)
        print(f"    -> player_tick ran {c} steps")
        print(f"=== after frame {f} ===")
        dump_state("STATE", mpu, ch_state_syms, sym_shadow)
        print()
    else:
        c = call_sub(mpu, PLAYER_TICK)
        steps_per_frame.append(c)

# Also list any frame > 5000 steps
heavy = [(f+1, s) for f, s in enumerate(steps_per_frame) if s > 5000]
print(f"\nFrames > 5000 steps:")
for f, s in heavy:
    print(f"  f={f}: {s} steps")
