#!/usr/bin/env python3
"""
Run M6 against all PT3 files in tests/pt3_corpus/, generating Python golden refs
on-the-fly and reporting bit-exact match percentage per file.

Output: build/corpus_results.txt with summary
"""
import sys, os, struct, hashlib
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pt3_python_sim'))
sys.path.insert(0, 'tests')

from pt3_simulator import PT3Module, simulate
from harness import build_sim, load_bin, call_sub, find_symbol, BUILD_DIR, PLAYER_BASE, PLAYER_INIT

PLAYER_INIT_SONG = PLAYER_BASE + 0x2A
PLAYER_TICK = PLAYER_BASE + 0x2D

NUM_FRAMES = int(sys.argv[1]) if len(sys.argv) > 1 else 2000

# Corpus = wider regression set: tests/pt3 (M6 core) + tests/pt3_corpus (extras).
# Approach 2 from the rename PR: duplicates were removed from tests/pt3_corpus,
# so iterating both directories gives the complete unique 17-file set.
CORPUS = []
for d in ['tests/pt3', 'tests/pt3_corpus']:
    for f in sorted(os.listdir(d)):
        if f.endswith('.pt3'):
            CORPUS.append(f'{d}/{f}')
results = []

print(f"Testing {len(CORPUS)} files for {NUM_FRAMES} frames each...")
print()

for path in CORPUS:
    fname = os.path.basename(path)
    
    # Generate Python golden ref
    try:
        mod = PT3Module(path)
        psg = simulate(mod, max_frames=NUM_FRAMES, verbose=False)
    except Exception as e:
        print(f"  {fname:50} SIM ERROR: {e}")
        results.append((fname, 0, NUM_FRAMES, str(e)))
        continue
    
    # Use raw_frames (full per-frame R0..R13 snapshot, with 0xFF sentinel
    # preserved on R13) — same convention as gen_m6_golden.py and
    # tests/m6_ref_*.bin. The 0xFF in ay_regs[13] means "do not write R13"
    # this frame; the 6502 player honors this in m6_write_ay_regs.
    ref_frames = [bytes(raw) for raw in psg.raw_frames]
    
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
