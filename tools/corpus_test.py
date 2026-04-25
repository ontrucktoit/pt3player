#!/usr/bin/env python3
"""
Run M6 against all PT3 files in tests/pt3_corpus/, generating Python golden refs
on-the-fly and reporting bit-exact match percentage per file.

Output: build/corpus_results.txt with summary
"""
import sys, os, struct, hashlib
sys.path.insert(0, '/home/linumax/commodore/jukebox/pt3_python_sim/pt3_python_sim')
sys.path.insert(0, 'tests')

from pt3_simulator import PT3Module, simulate
from harness import build_sim, load_bin, call_sub, find_symbol, BUILD_DIR, PLAYER_BASE, PLAYER_INIT

PLAYER_INIT_SONG = PLAYER_BASE + 0x2A
PLAYER_TICK = PLAYER_BASE + 0x2D

NUM_FRAMES = int(sys.argv[1]) if len(sys.argv) > 1 else 2000

CORPUS = sorted(os.listdir('tests/pt3_corpus'))
results = []

print(f"Testing {len(CORPUS)} files for {NUM_FRAMES} frames each...")
print()

for fname in CORPUS:
    if not fname.endswith('.pt3'): continue
    path = f'tests/pt3_corpus/{fname}'
    
    # Generate Python golden ref
    try:
        mod = PT3Module(path)
        psg = simulate(mod, max_frames=NUM_FRAMES, verbose=False)
    except Exception as e:
        print(f"  {fname:50} SIM ERROR: {e}")
        results.append((fname, 0, NUM_FRAMES, str(e)))
        continue
    
    state = [0] * 14
    ref_frames = []
    for f in psg.frames:
        for r, v in f.items():
            state[r] = v
        ref_frames.append(bytes(state))
    
    # Run 6502 port
    mpu, obs = build_sim()
    load_bin(mpu, BUILD_DIR / "player.bin", 0x3000)
    pt3_data = open(path, 'rb').read()
    for i, b in enumerate(pt3_data):
        mpu.memory[0x8000 + i] = b
    call_sub(mpu, PLAYER_INIT)
    mpu.a = 0x80; mpu.x = 0x00
    call_sub(mpu, PLAYER_INIT_SONG)
    
    shadow = find_symbol('shadow_ay')
    
    pass_count = 0
    first_fail = None
    first_fail_diffs = None
    for i in range(min(NUM_FRAMES, len(ref_frames) - 1)):
        call_sub(mpu, PLAYER_TICK)
        actual = bytes(mpu.memory[shadow + r] for r in range(14))
        expected = ref_frames[i + 1]
        if actual == expected:
            pass_count += 1
        elif first_fail is None:
            first_fail = i + 1
            first_fail_diffs = [(r, actual[r], expected[r]) for r in range(14) if actual[r] != expected[r]]
    
    total = min(NUM_FRAMES, len(ref_frames) - 1)
    pct = 100.0 * pass_count / total if total else 0
    results.append((fname, pass_count, total, first_fail, first_fail_diffs))
    
    status = '✓' if pass_count == total else '✗'
    info = ''
    if first_fail:
        info = f" first fail @ f{first_fail}: " + ' '.join(f"R{r}:${g:02X}!=${e:02X}" for r,g,e in first_fail_diffs[:3])
    print(f"  {status} {fname:50} {pass_count:>5}/{total:<5} ({pct:5.1f}%){info}")

print()
n_pass = sum(1 for _, p, t, *_ in results if p == t and t > 0)
print(f"=== SUMMARY: {n_pass}/{len(results)} files bit-exact ===")
