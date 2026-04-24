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


# -----------------------------------------------------------------------------
# M5a test — single-channel pattern row decoder
# -----------------------------------------------------------------------------
PLAYER_DECODE_ROW = PLAYER_BASE + 0x1E
ZP_STREAM_A_LO = 0xD8
ZP_STREAM_A_HI = 0xD9
ZP_STREAM_B_LO = 0xDA
ZP_STREAM_B_HI = 0xDB
ZP_STREAM_C_LO = 0xDC
ZP_STREAM_C_HI = 0xDD

ROW_FIELD_NAMES = [
    'note', 'sample', 'env_type', 'ornament', 'orn_expl_zero', 'volume',
    'env_period_lo', 'env_period_hi', 'noise_period',
    'spec_cmd', 'spec_param0', 'spec_param1'
]


def test_m5a():
    print("=" * 70)
    print("M5a - Pattern Row Decoder (single channel)")
    print("=" * 70)
    assemble_player()

    syms = {name: find_symbol(name) for name in [
        "pt3_base_lo", "pt3_patterns_ptr_lo",
        "row_out_ch_a", "row_out_ch_b", "row_out_ch_c",
    ]}

    total_rows_pass = 0
    total_rows_fail = 0
    files_pass = 0
    files_fail = 0
    BASE = 0x8000

    for fname in ['luchibobra.pt3', 'blobbzgame.pt3', 'yerzmyey.pt3']:
        ref_path = TESTS_DIR / f"m5a_ref_{fname.replace('.pt3','')}.bin"
        ref_data = ref_path.read_bytes()
        assert ref_data[:4] == b'M5A\x01', f"Bad magic in {ref_path}"
        num_seq = ref_data[4] | (ref_data[5] << 8)

        # Load PT3 into py65 memory (shared across all sequences in this file)
        mpu, obs = build_sim()
        load_bin(mpu, BUILD_DIR / "player.bin", 0x3000)
        pt3 = (TESTS_DIR / "pt3" / fname).read_bytes()
        for i, b in enumerate(pt3):
            mpu.memory[BASE + i] = b
        call_sub(mpu, PLAYER_INIT)
        mpu.a = BASE >> 8
        mpu.x = BASE & 0xFF
        call_sub(mpu, PLAYER_LOAD_PT3)

        file_rows_pass = 0
        file_rows_fail = 0
        first_fail_info = None

        idx = 6  # skip 4-byte magic + 2-byte seq count
        for seq_i in range(num_seq):
            pat_num = ref_data[idx]
            ch_idx = ref_data[idx + 1]
            start_ptr_rel = ref_data[idx + 2] | (ref_data[idx + 3] << 8)
            num_rows = ref_data[idx + 4] | (ref_data[idx + 5] << 8)
            idx += 6

            # Set ZP_STREAM_<ch> to absolute start ptr
            start_abs = BASE + start_ptr_rel
            if ch_idx == 0:
                mpu.memory[ZP_STREAM_A_LO] = start_abs & 0xFF
                mpu.memory[ZP_STREAM_A_HI] = (start_abs >> 8) & 0xFF
                out_addr = syms['row_out_ch_a']
            elif ch_idx == 1:
                mpu.memory[ZP_STREAM_B_LO] = start_abs & 0xFF
                mpu.memory[ZP_STREAM_B_HI] = (start_abs >> 8) & 0xFF
                out_addr = syms['row_out_ch_b']
            else:
                mpu.memory[ZP_STREAM_C_LO] = start_abs & 0xFF
                mpu.memory[ZP_STREAM_C_HI] = (start_abs >> 8) & 0xFF
                out_addr = syms['row_out_ch_c']

            for row_i in range(num_rows):
                expected_row = ref_data[idx:idx + 12]
                expected_end_ptr_rel = ref_data[idx + 12] | (ref_data[idx + 13] << 8)
                idx += 14

                mpu.a = ch_idx
                call_sub(mpu, PLAYER_DECODE_ROW)
                # ret A=0 expected for decoded rows
                actual_row = bytes([mpu.memory[out_addr + i] for i in range(12)])

                # Check stream ptr
                if ch_idx == 0:
                    actual_end_abs = mpu.memory[ZP_STREAM_A_LO] | (mpu.memory[ZP_STREAM_A_HI] << 8)
                elif ch_idx == 1:
                    actual_end_abs = mpu.memory[ZP_STREAM_B_LO] | (mpu.memory[ZP_STREAM_B_HI] << 8)
                else:
                    actual_end_abs = mpu.memory[ZP_STREAM_C_LO] | (mpu.memory[ZP_STREAM_C_HI] << 8)
                actual_end_rel = actual_end_abs - BASE

                row_match = (actual_row == expected_row)
                ptr_match = (actual_end_rel == expected_end_ptr_rel)

                if row_match and ptr_match:
                    file_rows_pass += 1
                else:
                    file_rows_fail += 1
                    if first_fail_info is None:
                        # Capture detailed info for reporting
                        diffs = []
                        for i in range(12):
                            if actual_row[i] != expected_row[i]:
                                diffs.append(
                                    f"{ROW_FIELD_NAMES[i]}: got ${actual_row[i]:02X} "
                                    f"exp ${expected_row[i]:02X}"
                                )
                        if not ptr_match:
                            diffs.append(
                                f"stream_ptr: got ${actual_end_rel:04X} "
                                f"exp ${expected_end_ptr_rel:04X}"
                            )
                        first_fail_info = {
                            'pat': pat_num, 'ch': ch_idx, 'row': row_i,
                            'diffs': diffs
                        }

        if file_rows_fail == 0:
            print(f"  {fname}: PASS ({file_rows_pass} rows)")
            files_pass += 1
        else:
            print(f"  {fname}: FAIL ({file_rows_pass} passed, {file_rows_fail} failed)")
            if first_fail_info:
                info = first_fail_info
                print(f"    first failure: pat {info['pat']} ch {info['ch']} row {info['row']}")
                for d in info['diffs']:
                    print(f"      {d}")
            files_fail += 1
        total_rows_pass += file_rows_pass
        total_rows_fail += file_rows_fail

    print()
    print(f"  Result: {files_pass}/{files_pass + files_fail} files; "
          f"{total_rows_pass}/{total_rows_pass + total_rows_fail} rows bit-exact")
    return 0 if files_fail == 0 else 1


# -----------------------------------------------------------------------------
# M5b test — skip + multi-channel driver
# -----------------------------------------------------------------------------
PLAYER_INIT_PATTERN = PLAYER_BASE + 0x21
PLAYER_DECODE_ALL = PLAYER_BASE + 0x24


def test_m5b():
    print("=" * 70)
    print("M5b - Skip + Multi-channel Driver")
    print("=" * 70)
    assemble_player()

    syms = {name: find_symbol(name) for name in [
        "row_out_ch_a", "row_out_ch_b", "row_out_ch_c",
    ]}

    total_ticks_pass = 0
    total_ticks_fail = 0
    files_pass = 0
    files_fail = 0
    BASE = 0x8000

    for fname in ['luchibobra.pt3', 'blobbzgame.pt3', 'yerzmyey.pt3']:
        ref_path = TESTS_DIR / f"m5b_ref_{fname.replace('.pt3','')}.bin"
        ref_data = ref_path.read_bytes()
        assert ref_data[:4] == b'M5B\x01', f"Bad magic in {ref_path}"
        num_patterns = ref_data[4] | (ref_data[5] << 8)

        mpu, obs = build_sim()
        load_bin(mpu, BUILD_DIR / "player.bin", 0x3000)
        pt3 = (TESTS_DIR / "pt3" / fname).read_bytes()
        for i, b in enumerate(pt3):
            mpu.memory[BASE + i] = b
        call_sub(mpu, PLAYER_INIT)
        mpu.a = BASE >> 8
        mpu.x = BASE & 0xFF
        call_sub(mpu, PLAYER_LOAD_PT3)

        file_ticks_pass = 0
        file_ticks_fail = 0
        first_fail = None

        idx = 6
        for p_i in range(num_patterns):
            pat_num = ref_data[idx]
            num_ticks = ref_data[idx + 1] | (ref_data[idx + 2] << 8)
            idx += 3

            # Init pattern
            mpu.a = pat_num
            call_sub(mpu, PLAYER_INIT_PATTERN)

            for tick_i in range(num_ticks):
                expected_tick = ref_data[idx:idx + 36]
                expected_active = ref_data[idx + 36]
                idx += 37

                call_sub(mpu, PLAYER_DECODE_ALL)
                actual_active = mpu.a
                # Read all 3 row_outs
                actual_bytes = bytearray()
                for ch_name in ('a', 'b', 'c'):
                    addr = syms[f'row_out_ch_{ch_name}']
                    for i in range(12):
                        actual_bytes.append(mpu.memory[addr + i])
                actual_tick = bytes(actual_bytes)

                row_match = actual_tick == expected_tick
                active_match = actual_active == expected_active

                if row_match and active_match:
                    file_ticks_pass += 1
                else:
                    file_ticks_fail += 1
                    if first_fail is None:
                        diffs = []
                        for ch_i in range(3):
                            for field_i in range(12):
                                i = ch_i * 12 + field_i
                                if actual_tick[i] != expected_tick[i]:
                                    diffs.append(
                                        f"ch{ch_i} {ROW_FIELD_NAMES[field_i]}: "
                                        f"got ${actual_tick[i]:02X} exp ${expected_tick[i]:02X}"
                                    )
                        if not active_match:
                            diffs.append(f"active_count: got {actual_active} exp {expected_active}")
                        first_fail = {'pat': pat_num, 'tick': tick_i, 'diffs': diffs}

        if file_ticks_fail == 0:
            print(f"  {fname}: PASS ({file_ticks_pass} ticks)")
            files_pass += 1
        else:
            print(f"  {fname}: FAIL ({file_ticks_pass} passed, {file_ticks_fail} failed)")
            if first_fail:
                info = first_fail
                print(f"    first failure: pat {info['pat']} tick {info['tick']}")
                for d in info['diffs'][:10]:
                    print(f"      {d}")
            files_fail += 1
        total_ticks_pass += file_ticks_pass
        total_ticks_fail += file_ticks_fail

    print()
    print(f"  Result: {files_pass}/{files_pass + files_fail} files; "
          f"{total_ticks_pass}/{total_ticks_pass + total_ticks_fail} ticks bit-exact")
    return 0 if files_fail == 0 else 1


# -----------------------------------------------------------------------------
# M6 test — full per-tick playback engine, bit-exact vs Python PSG sim
# -----------------------------------------------------------------------------
PLAYER_INIT_SONG = PLAYER_BASE + 0x2A
PLAYER_TICK = PLAYER_BASE + 0x2D


def test_m6(max_frames=8000):
    """Run M6 player for N frames per file, diff shadow_ay vs golden ref bit-exact.
    
    For each test file:
      1. Build sim, load player + pt3
      2. Call player_init then player_init_song
      3. Loop: call player_tick; read shadow_ay; compare to golden frame
      4. Report first-mismatch frame and ratio of matching frames
    """
    print("=" * 70)
    print("M6 - Full playback engine (bit-exact vs Python PSG sim)")
    print("=" * 70)
    assemble_player()

    syms = {name: find_symbol(name) for name in [
        "shadow_ay",
    ]}

    BASE = 0x8000
    files_pass = 0
    files_fail = 0

    for fname in ['luchibobra.pt3', 'blobbzgame.pt3', 'yerzmyey.pt3']:
        ref_path = TESTS_DIR / f"m6_ref_{fname.replace('.pt3','')}.bin"
        ref = ref_path.read_bytes()
        assert ref[:4] == b'M6\x00\x01', f"bad magic in {ref_path}"
        n_ref_frames = ref[4] | (ref[5] << 8)
        # frames stored at offset 6, 14 bytes each
        def get_ref_frame(i):
            base_off = 6 + i * 14
            return ref[base_off:base_off+14]

        mpu, obs = build_sim()
        load_bin(mpu, BUILD_DIR / "player.bin", 0x3000)
        pt3 = (TESTS_DIR / "pt3" / fname).read_bytes()
        for i, b in enumerate(pt3):
            mpu.memory[BASE + i] = b
        call_sub(mpu, PLAYER_INIT)
        # player_init_song(A=hi, X=lo)
        mpu.a = BASE >> 8
        mpu.x = BASE & 0xFF
        call_sub(mpu, PLAYER_INIT_SONG)

        # Frame 0 is reference initial state (all zeros).
        # Python emits frame 0 as zeros BEFORE the loop. We compare frame 1+.
        N = min(max_frames, n_ref_frames - 1)
        frame_pass = 0
        first_fail = None

        for f_idx in range(1, N + 1):
            call_sub(mpu, PLAYER_TICK)
            actual = bytes(mpu.memory[syms["shadow_ay"] + r] for r in range(14))
            expected = get_ref_frame(f_idx)
            if actual == expected:
                frame_pass += 1
            elif first_fail is None:
                diffs = [(r, actual[r], expected[r]) for r in range(14) if actual[r] != expected[r]]
                first_fail = (f_idx, diffs)

        if frame_pass == N:
            print(f"  {fname}: PASS ({frame_pass}/{N} frames bit-exact)")
            files_pass += 1
        else:
            ratio = 100.0 * frame_pass / N if N else 0.0
            print(f"  {fname}: FAIL ({frame_pass}/{N} frames, {ratio:.1f}%)")
            if first_fail:
                fi, diffs = first_fail
                print(f"    first mismatch at frame {fi}:")
                for r, got, exp in diffs[:8]:
                    print(f"      R{r:2d}: got ${got:02X}  exp ${exp:02X}")
            files_fail += 1

    print()
    print(f"  Result: {files_pass}/{files_pass + files_fail} files; bit-exact playback")
    return 0 if files_fail == 0 else 1


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
    elif cmd == "m5a":
        sys.exit(test_m5a())
    elif cmd == "m5b":
        sys.exit(test_m5b())
    elif cmd == "m6":
        sys.exit(test_m6())
    elif cmd == "all":
        r1 = test_m1()
        r2 = test_m2()
        r3 = test_m3()
        r4 = test_m4()
        r5 = test_m5a()
        r6 = test_m5b()
        r7 = test_m6()
        sys.exit(r1 | r2 | r3 | r4 | r5 | r6 | r7)
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
