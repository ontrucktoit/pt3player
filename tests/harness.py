#!/usr/bin/env python3
"""
PT3 Player harness — py65 validation.

M1: hello-tone constant AY output
M2: note table generator vs Python reference (8 combinations)
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


M1_EXPECTED = (0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00,
               0x3E, 0x0F, 0x00, 0x00, 0x00, 0x00, 0x00)


def test_m1():
    print("=" * 70)
    print("M1 - Hello Tone")
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


def test_m2():
    print("=" * 70)
    print("M2 - Note Table Generator")
    print("=" * 70)
    assemble_player()

    note_table_addr = find_symbol("note_table")
    print(f"  note_table located at ${note_table_addr:04X}")

    total_passed = 0
    total_failed = 0

    for table_idx in range(4):
        for version in range(2):
            mpu, obs = build_sim()
            load_bin(mpu, BUILD_DIR / "player.bin", 0x3000)

            call_sub(mpu, PLAYER_INIT)

            mpu.a = table_idx
            mpu.x = version
            c = call_sub(mpu, PLAYER_BUILD_NOTE_TABLE)

            our = bytes([mpu.memory[note_table_addr + i] for i in range(192)])

            ref_path = TESTS_DIR / f"nt_ref_t{table_idx}_v{version}.bin"
            ref = ref_path.read_bytes()

            if our == ref:
                print(f"  table={table_idx} version={'OLD' if version else 'NEW'}: "
                      f"PASS ({c} steps)")
                total_passed += 1
            else:
                for i in range(192):
                    if our[i] != ref[i]:
                        word_idx = i // 2
                        octave = word_idx // 12
                        note = word_idx % 12
                        print(f"  table={table_idx} version={'OLD' if version else 'NEW'}: "
                              f"FAIL at byte {i} (note {note}, octave {octave+1})")
                        lo = max(0, i - 3)
                        hi = min(192, i + 5)
                        print(f"    our: {' '.join(f'{b:02X}' for b in our[lo:hi])}")
                        print(f"    ref: {' '.join(f'{b:02X}' for b in ref[lo:hi])}")
                        break
                total_failed += 1

    print()
    print(f"  Result: {total_passed}/{total_passed + total_failed} combinations passed")
    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd == "m1":
        sys.exit(test_m1())
    elif cmd == "m2":
        sys.exit(test_m2())
    elif cmd == "all":
        r1 = test_m1()
        r2 = test_m2()
        sys.exit(r1 | r2)
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
