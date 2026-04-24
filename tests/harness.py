#!/usr/bin/env python3
"""
PT3 Player harness — py65 validation.

M1: hello-tone constant AY output
M2: note table generator vs Python reference (8 combinations)
M3: volume table generator vs Python reference (2 variants)
"""

import os
import sys
import subprocess
from pathlib import Path

from py65.devices.mpu6502 import MPU
from py65.memory import ObservableMemory

PROJECT_ROOT = Path(__file__).parent.parent
SRC_DIR = PROJECT_ROOT / "src"
BUILD_DIR = PROJECT_ROOT / "build"
TESTS_DIR = PROJECT_ROOT / "tests"

DIGIMUZ_DATA_W = 0xFD22
DIGIMUZ_REG_SEL = 0xFD23

PLAYER_BASE = 0x3000
PLAYER_INIT = PLAYER_BASE + 0x00
PLAYER_PLAY = PLAYER_BASE + 0x06
PLAYER_BUILD_NOTE_TABLE = PLAYER_BASE + 0x18


def assemble_player():
    BUILD_DIR.mkdir(exist_ok=True)
    r = subprocess.run(
        ["ca65", "-I", str(SRC_DIR), "-o",
         str(BUILD_DIR / "player.o"), str(SRC_DIR / "player.s")],
        capture_output=True, text=True)
    if r.returncode != 0:
        print("ca65 FAILED:"); print(r.stderr); sys.exit(1)
    r = subprocess.run(
        ["ld65", "-Ln", str(BUILD_DIR / "player.sym"),
         "-C", str(SRC_DIR / "player.cfg"),
         "-o", str(BUILD_DIR / "player.bin"), str(BUILD_DIR / "player.o")],
        capture_output=True, text=True)
    if r.returncode != 0:
        print("ld65 FAILED:"); print(r.stderr); sys.exit(1)


def find_symbol(name):
    """Parse ld65 -Ln label file. Format: 'al ADDR .NAME'"""
    sym_file = BUILD_DIR / "player.sym"
    for line in sym_file.read_text().splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[2] == f".{name}":
            return int(parts[1], 16)
    raise RuntimeError(f"Symbol {name} not found in .sym file")


class AYBusObserver:
    def __init__(self):
        self.selected_reg = 0
        self.ay_state = [0] * 16
        self.frame_end_states = []

    def on_reg_sel(self, addr, value):
        self.selected_reg = value & 0x0F

    def on_data_write(self, addr, value):
        self.ay_state[self.selected_reg] = value

    def snapshot(self):
        self.frame_end_states.append(tuple(self.ay_state[:14]))


def load_bin(mpu, path, addr):
    data = Path(path).read_bytes()
    for i, b in enumerate(data):
        mpu.memory[addr + i] = b


def call_sub(mpu, addr, max_cycles=1000000):
    SENTINEL = 0xFF00
    mpu.stPush(((SENTINEL - 1) >> 8) & 0xFF)
    mpu.stPush((SENTINEL - 1) & 0xFF)
    mpu.pc = addr
    cycles = 0
    while mpu.pc != SENTINEL and cycles < max_cycles:
        mpu.step()
        cycles += 1
    if cycles >= max_cycles:
        raise RuntimeError(f"call_sub hit {max_cycles} cycles (stuck at PC=${mpu.pc:04X})")
    return cycles


def build_sim():
    obs = AYBusObserver()
    mem = ObservableMemory()
    mem.subscribe_to_write([DIGIMUZ_REG_SEL], obs.on_reg_sel)
    mem.subscribe_to_write([DIGIMUZ_DATA_W], obs.on_data_write)
    mpu = MPU(memory=mem)
    mpu.reset()
    return mpu, obs


# -----------------------------------------------------------------------------
# M1 test — unchanged
# -----------------------------------------------------------------------------
M1_EXPECTED = (0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00,
               0x3E, 0x0F, 0x00, 0x00, 0x00, 0x00, 0x00)


def test_m1():
    print("=" * 70)
    print("M1 — Hello Tone")
    print("=" * 70)
    assemble_player()
    mpu, obs = build_sim()
    load_bin(mpu, BUILD_DIR / "player.bin", 0x3000)
    c = call_sub(mpu, PLAYER_INIT)
    print(f"  player_init: {c} steps")
    obs.snapshot()
    tot = 0
    for _ in range(60):
        tot += call_sub(mpu, PLAYER_PLAY)
        obs.snapshot()
    print(f"  player_play avg: {tot // 60} steps/frame")

    frames = obs.frame_end_states[1:]
    ok_id = all(f == frames[0] for f in frames)
    ok_exp = frames[0] == M1_EXPECTED
    print(f"  all 60 frames identical: {'PASS' if ok_id else 'FAIL'}")
    print(f"  matches M1 spec:         {'PASS' if ok_exp else 'FAIL'}")
    return 0 if (ok_id and ok_exp) else 1


# -----------------------------------------------------------------------------
# M2 test — note table generator for all 8 (table, version) combinations
# -----------------------------------------------------------------------------
def test_m2():
    print("=" * 70)
    print("M2 — Note Table Generator")
    print("=" * 70)
    assemble_player()

    # Find note_table address in binary layout
    note_table_addr = find_symbol("note_table")
    print(f"  note_table located at ${note_table_addr:04X}")

    total_passed = 0
    total_failed = 0

    for table_idx in range(4):
        for version in range(2):
            mpu, obs = build_sim()
            load_bin(mpu, BUILD_DIR / "player.bin", 0x3000)

            # Call player_init to zero BSS
            call_sub(mpu, PLAYER_INIT)

            # Call player_build_note_table(A=table_idx, X=version)
            mpu.a = table_idx
            mpu.x = version
            c = call_sub(mpu, PLAYER_BUILD_NOTE_TABLE)

            # Read 192 bytes from note_table
            our = bytes([mpu.memory[note_table_addr + i] for i in range(192)])

            # Compare with Python reference
            ref_path = TESTS_DIR / f"nt_ref_t{table_idx}_v{version}.bin"
            ref = ref_path.read_bytes()

            if our == ref:
                print(f"  table={table_idx} version={'OLD' if version else 'NEW'}: "
                      f"PASS ({c} steps)")
                total_passed += 1
            else:
                # Find first diff
                for i in range(192):
                    if our[i] != ref[i]:
                        word_idx = i // 2
                        octave = word_idx // 12
                        note = word_idx % 12
                        print(f"  table={table_idx} version={'OLD' if version else 'NEW'}: "
                              f"FAIL at byte {i} (note {note}, octave {octave+1})")
                        # Dump 8 bytes around
                        lo = max(0, i - 3)
                        hi = min(192, i + 5)
                        print(f"    our: {' '.join(f'{b:02X}' for b in our[lo:hi])}")
                        print(f"    ref: {' '.join(f'{b:02X}' for b in ref[lo:hi])}")
                        break
                total_failed += 1

    print()
    print(f"  Result: {total_passed}/{total_passed + total_failed} combinations passed")
    return 0 if total_failed == 0 else 1


# -----------------------------------------------------------------------------
# M3 test — volume table generator for both variants (OLD pt<5, NEW pt>=5)
# -----------------------------------------------------------------------------
PLAYER_BUILD_VOLUME_TABLE = PLAYER_BASE + 0x1B


def test_m3():
    print("=" * 70)
    print("M3 - Volume Table Generator")
    print("=" * 70)
    assemble_player()

    volume_table_addr = find_symbol("volume_table")
    print(f"  volume_table located at ${volume_table_addr:04X}")

    total_passed = 0
    total_failed = 0

    # (pt_version, variant_name)
    cases = [(4, "old"), (7, "new")]

    for pt_version, variant in cases:
        mpu, obs = build_sim()
        load_bin(mpu, BUILD_DIR / "player.bin", 0x3000)

        call_sub(mpu, PLAYER_INIT)

        # player_build_volume_table(A = pt_version)
        mpu.a = pt_version
        c = call_sub(mpu, PLAYER_BUILD_VOLUME_TABLE)

        our = bytes([mpu.memory[volume_table_addr + i] for i in range(256)])

        ref_path = TESTS_DIR / f"vt_ref_{variant}.bin"
        ref = ref_path.read_bytes()

        if our == ref:
            print(f"  pt_version={pt_version} ({variant}): PASS ({c} steps)")
            total_passed += 1
        else:
            # Find first diff
            for i in range(256):
                if our[i] != ref[i]:
                    cv = i >> 4
                    sv = i & 0x0F
                    print(f"  pt_version={pt_version} ({variant}): FAIL at idx {i} "
                          f"(ch_vol={cv:X} sample_vol={sv:X})")
                    lo = max(0, i - 3)
                    hi = min(256, i + 5)
                    print(f"    our: {' '.join(f'{b:02X}' for b in our[lo:hi])}")
                    print(f"    ref: {' '.join(f'{b:02X}' for b in ref[lo:hi])}")
                    break
            total_failed += 1

    print()
    print(f"  Result: {total_passed}/{total_passed + total_failed} variants passed")
    return 0 if total_failed == 0 else 1


# -----------------------------------------------------------------------------
# M4 test — PT3 header parser
# -----------------------------------------------------------------------------
PLAYER_LOAD_PT3 = PLAYER_BASE + 0x03

# Expected values extracted from Python PT3Module for each test file.
# (version_char, features_level, tone_table, delay, num_pos, loop_pos, pat_ptr)
M4_EXPECTED = {
    "yerzmyey.pt3":   (0x37, 2, 1, 5, 28, 0, 0x00E6),
    "luchibobra.pt3": (0x35, 0, 2, 4, 9,  0, 0x00D3),
    "blobbzgame.pt3": (0x72, 1, 2, 3, 8,  2, 0x00D2),
}


def test_m4():
    print("=" * 70)
    print("M4 - PT3 Header Parser")
    print("=" * 70)
    assemble_player()

    # Symbol lookups
    syms = {name: find_symbol(name) for name in [
        "pt3_base_lo", "pt3_version_char", "pt3_features_level",
        "pt3_tone_table", "pt3_delay", "pt3_num_positions",
        "pt3_loop_position", "pt3_patterns_ptr_lo",
        "pt3_sample_table_lo", "pt3_ornament_table_lo",
        "pt3_position_list_lo", "pt3_parse_error",
    ]}

    total_passed = 0
    total_failed = 0
    BASE = 0x8000                                # where we load PT3 in RAM

    for fname, exp in M4_EXPECTED.items():
        (ev_char, ev_fl, ev_tt, ev_del, ev_npos, ev_lpos, ev_pptr) = exp

        mpu, obs = build_sim()
        load_bin(mpu, BUILD_DIR / "player.bin", 0x3000)

        # Load PT3 file at $8000
        pt3_data = (TESTS_DIR / "pt3" / fname).read_bytes()
        for i, b in enumerate(pt3_data):
            mpu.memory[BASE + i] = b

        # Initialize player
        call_sub(mpu, PLAYER_INIT)

        # Call player_load_pt3(A=base_hi, X=base_lo)
        mpu.a = BASE >> 8
        mpu.x = BASE & 0xFF
        c = call_sub(mpu, PLAYER_LOAD_PT3)

        def rd(name):
            return mpu.memory[syms[name]]

        def rd16(name):
            return rd(name) | (mpu.memory[syms[name] + 1] << 8)

        # Collect actual
        got_base = rd16("pt3_base_lo")
        got_ver = rd("pt3_version_char")
        got_fl = rd("pt3_features_level")
        got_tt = rd("pt3_tone_table")
        got_del = rd("pt3_delay")
        got_npos = rd("pt3_num_positions")
        got_lpos = rd("pt3_loop_position")
        got_pptr = rd16("pt3_patterns_ptr_lo")
        got_sptr = rd16("pt3_sample_table_lo")
        got_optr = rd16("pt3_ornament_table_lo")
        got_plst = rd16("pt3_position_list_lo")
        got_err = rd("pt3_parse_error")

        # Expected absolute pointers
        ex_pptr_abs = BASE + ev_pptr
        ex_sptr_abs = BASE + 0x69
        ex_optr_abs = BASE + 0xA9
        ex_plst_abs = BASE + 0xC9

        checks = [
            ("parse_error",   got_err,  0),
            ("base",          got_base, BASE),
            ("version_char",  got_ver,  ev_char),
            ("features_lvl",  got_fl,   ev_fl),
            ("tone_table",    got_tt,   ev_tt),
            ("delay",         got_del,  ev_del),
            ("num_positions", got_npos, ev_npos),
            ("loop_position", got_lpos, ev_lpos),
            ("patterns_ptr",  got_pptr, ex_pptr_abs),
            ("sample_table",  got_sptr, ex_sptr_abs),
            ("ornament_tbl",  got_optr, ex_optr_abs),
            ("position_list", got_plst, ex_plst_abs),
        ]

        failures = [(n, g, e) for (n, g, e) in checks if g != e]
        if not failures:
            print(f"  {fname}: PASS ({c} steps)")
            total_passed += 1
        else:
            print(f"  {fname}: FAIL ({c} steps)")
            for name, g, e in failures:
                print(f"    {name:15s}: got=${g:04X} expected=${e:04X}")
            total_failed += 1

    print()
    print(f"  Result: {total_passed}/{total_passed + total_failed} files passed")
    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd == "m1":
        sys.exit(test_m1())
    elif cmd == "m2":
        sys.exit(test_m2())
    elif cmd == "m3":
        sys.exit(test_m3())
    elif cmd == "m4":
        sys.exit(test_m4())
    elif cmd == "all":
        r1 = test_m1()
        r2 = test_m2()
        r3 = test_m3()
        r4 = test_m4()
        sys.exit(r1 | r2 | r3 | r4)
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
