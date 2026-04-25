"""Inspect player state right after player_init_song, then after first tick.
Compare to what the OLD master (before precompute fix) does."""
import sys, os
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pt3_python_sim'))
sys.path.insert(0, 'tests')

from harness import (build_sim, load_bin, call_sub, find_symbol, BUILD_DIR,
                     PLAYER_BASE, PLAYER_INIT, assemble_player, TESTS_DIR)

PLAYER_INIT_SONG = PLAYER_BASE + 0x2A
PLAYER_TICK = PLAYER_BASE + 0x2D

assemble_player()

FNAME = sys.argv[1] if len(sys.argv) > 1 else 'luchibobra_pt3_player_bug_fix_2000.pt3'

# Load symbols
all_syms = {}
for line in (BUILD_DIR / "player.sym").read_text().splitlines():
    parts = line.split()
    if len(parts) == 3 and parts[0] == "al":
        all_syms[parts[2].lstrip(".")] = int(parts[1], 16)

mpu, _ = build_sim()
load_bin(mpu, BUILD_DIR / "player.bin", 0x3000)
BASE = 0x8000
pt3 = (TESTS_DIR / "pt3" / FNAME).read_bytes()
for i, b in enumerate(pt3):
    mpu.memory[BASE + i] = b
call_sub(mpu, PLAYER_INIT)
mpu.a = BASE >> 8; mpu.x = BASE & 0xFF
call_sub(mpu, PLAYER_INIT_SONG)

print(f"=== After player_init_song({FNAME}) ===")
syms_to_print = ['pb_speed', 'pb_tick_in_row', 'pb_position_idx',
                 'pb_current_line', 'pb_current_pat_len',
                 'pat_len_walk_pos', 'pat_len_tmp_pat_num']
for s in syms_to_print:
    if s in all_syms:
        v = mpu.memory[all_syms[s]]
        print(f"  {s} = ${v:02X} ({v})")

# Print pat_len_table (first 16 entries)
if 'pat_len_table' in all_syms:
    addr = all_syms['pat_len_table']
    vals = [mpu.memory[addr+i] for i in range(16)]
    print(f"  pat_len_table[0..15] = {[hex(v) for v in vals]}")

# ZP stream pointers
zp_stream = {}
for s in ['ZP_STREAM_A_LO', 'ZP_STREAM_A_HI', 'ZP_STREAM_B_LO', 'ZP_STREAM_B_HI', 'ZP_STREAM_C_LO', 'ZP_STREAM_C_HI']:
    if s in all_syms:
        zp_stream[s] = mpu.memory[all_syms[s]]
        print(f"  {s} @ ${all_syms[s]:04X} = ${zp_stream[s]:02X}")

# ch_skip_counter and ch_nn_skip
for s in ['ch_skip_counter_a', 'ch_skip_counter_b', 'ch_skip_counter_c',
          'ch_nn_skip_a', 'ch_nn_skip_b', 'ch_nn_skip_c',
          'ch_end_flag_a', 'ch_end_flag_b', 'ch_end_flag_c']:
    if s in all_syms:
        print(f"  {s} = ${mpu.memory[all_syms[s]]:02X}")

# Run first tick and inspect shadow_ay
shadow = all_syms['shadow_ay']
c = call_sub(mpu, PLAYER_TICK)
print(f"\n=== After first player_tick ({c} steps) ===")
print(f"  shadow_ay R0..R13 = " + " ".join(f"{mpu.memory[shadow+r]:02X}" for r in range(14)))

# Compare to expected from golden ref
ref = (TESTS_DIR / f"m6_ref_{FNAME.replace('.pt3','')}.bin").read_bytes()
expected = ref[6+0*14 : 6+1*14]
print(f"  expected R0..R13   = " + " ".join(f"{b:02X}" for b in expected))
