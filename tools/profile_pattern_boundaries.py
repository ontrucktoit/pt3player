#!/usr/bin/env python3
"""
Profile player_tick step count per frame and look for spikes at pattern
boundaries. If pattern-boundary frames take meaningfully more steps than
typical frames, that strongly supports the hypothesis that real-hardware
IRQ overrun on those frames is what Kris hears as 'czkawki'.
"""
import sys, os
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pt3_python_sim'))
sys.path.insert(0, 'tests')

from pt3_simulator import PT3Module
from harness import build_sim, load_bin, call_sub, find_symbol, BUILD_DIR, PLAYER_BASE, PLAYER_INIT, assemble_player, TESTS_DIR

PLAYER_INIT_SONG = PLAYER_BASE + 0x2A
PLAYER_TICK = PLAYER_BASE + 0x2D

NUM_FRAMES = int(os.environ.get('NF', 600))

FILES = ['luchibobra_pt3_player_bug_fix_2000.pt3', 'yerzmyey_fifteen_colours_2014.pt3', 'mmcm_xiaomi.pt3']
assemble_player()

print(f"Profiling {NUM_FRAMES} frames per song; reporting steps per frame")
print(f"and pattern-boundary spikes\n")

for fname in FILES:
    path = f'tests/pt3/{fname}'
    pt3 = open(path, 'rb').read()
    mod = PT3Module(path)
    speed = mod.initial_speed
    pat_lens = [mod.pattern_lengths[p] for p in mod.pattern_numbers]

    boundary_frames = []
    cum = 0
    for L in pat_lens[:-1]:
        cum += L * speed
        boundary_frames.append(cum)
    boundary_set = set(boundary_frames)

    mpu, _obs = build_sim()
    load_bin(mpu, BUILD_DIR / "player.bin", 0x3000)
    BASE = 0x8000
    for i, b in enumerate(pt3):
        mpu.memory[BASE + i] = b
    call_sub(mpu, PLAYER_INIT)
    mpu.a = BASE >> 8
    mpu.x = BASE & 0xFF
    call_sub(mpu, PLAYER_INIT_SONG)

    steps_per_frame = []
    for f_idx in range(1, NUM_FRAMES + 1):
        c = call_sub(mpu, PLAYER_TICK)
        steps_per_frame.append(c)

    avg = sum(steps_per_frame) / len(steps_per_frame)
    mn = min(steps_per_frame)
    mx = max(steps_per_frame)

    print(f"=== {fname} (speed={speed} t/row, pattern boundary every {pat_lens[0]*speed} frames) ===")
    print(f"  steps/frame: min={mn} avg={avg:.0f} max={mx}  spread={mx-mn} ({100*(mx-mn)/avg:.0f}% of avg)")
    print(f"  pattern-boundary frames in first {NUM_FRAMES}: {boundary_frames[:8]}")

    for bf in boundary_frames:
        if bf > NUM_FRAMES:
            break
        ctx_start = max(0, bf - 3)
        ctx_end = min(NUM_FRAMES, bf + 3)
        print(f"  around frame {bf}:")
        for fi in range(ctx_start, ctx_end):
            actual = fi + 1
            s = steps_per_frame[fi]
            mark = "  <-- BOUNDARY" if actual == bf else ""
            print(f"    f={actual:4d}: {s:5d} steps{mark}")
        print()

    indexed = list(enumerate(steps_per_frame, 1))
    heaviest = sorted(indexed, key=lambda t: -t[1])[:10]
    print(f"  top 10 heaviest frames in first {NUM_FRAMES}:")
    for f_idx, s in heaviest:
        is_boundary = f_idx in boundary_set
        is_row_start = (f_idx - 1) % speed == 0
        tag = ("PATTERN_BOUNDARY" if is_boundary
               else ("row_boundary" if is_row_start else "intra-row"))
        print(f"    f={f_idx:4d}: {s:5d} steps  ({tag})")
    print()
