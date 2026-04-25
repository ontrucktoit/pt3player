"""Deep diagnose of frame 279 in mmcm_xiaomi.pt3 — heaviest frame in profile.
Look at ALL channel state, skip counters, sample/orn positions.
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

# Find all symbols matching certain patterns
import subprocess
# Parse ld65 .sym file (al-format)
all_syms = {}
sym_file = BUILD_DIR / "player.sym"
for line in sym_file.read_text().splitlines():
    parts = line.split()
    if len(parts) == 3 and parts[0] == "al":
        addr = int(parts[1], 16)
        name = parts[2].lstrip(".")
        all_syms[name] = addr

# Pull symbols matching patterns
def pull(prefix):
    return sorted([(n, a) for n, a in all_syms.items() if n.startswith(prefix)])

ch_state = pull('ch_')
pb_state = pull('pb_')
print(f"Found {len(all_syms)} symbols total")
print(f"ch_* state symbols: {len(ch_state)}")
print(f"pb_* state symbols: {len(pb_state)}")

mpu, _ = build_sim()
load_bin(mpu, BUILD_DIR / "player.bin", 0x3000)
BASE = 0x8000
pt3 = (TESTS_DIR / "pt3" / FNAME).read_bytes()
for i, b in enumerate(pt3):
    mpu.memory[BASE + i] = b
call_sub(mpu, PLAYER_INIT)
mpu.a = BASE >> 8; mpu.x = BASE & 0xFF
call_sub(mpu, PLAYER_INIT_SONG)

shadow = find_symbol("shadow_ay")

def dump_full(label):
    print(f"  --- {label} ---")
    print(f"    AY = " + " ".join(f"{mpu.memory[shadow+r]:02X}" for r in range(14)))
    for n, a in pb_state:
        v = mpu.memory[a]
        # if the symbol probably is 16-bit (pb_xxx_lo/hi pattern), show pair
        print(f"    {n} @ ${a:04X} = ${v:02X} ({v})")
    print(f"    --- per-channel state ---")
    for n, a in ch_state:
        v = mpu.memory[a]
        print(f"    {n} @ ${a:04X} = ${v:02X} ({v})")

# Run up to TARGET-1
for f in range(1, TARGET):
    call_sub(mpu, PLAYER_TICK)

print(f"\n=== STATE before frame {TARGET} ===")
dump_full("PRE")
print(f"\n=== running frame {TARGET} ===")
c = call_sub(mpu, PLAYER_TICK)
print(f"  player_tick: {c} steps")
print(f"\n=== STATE after frame {TARGET} ===")
dump_full("POST")
