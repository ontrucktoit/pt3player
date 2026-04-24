#!/usr/bin/env python3
"""
PT3 Player harness — py65-based validation for 6502 code.

Since there's no Plus/4 emulator with DigiMuz support on Linux (YAPE is
Windows/macOS only, VICE doesn't emulate DigiMuz), this harness is the
primary validation loop for the player library.

Workflow:
    1. Assemble player.s with ca65/ld65 → player.bin (raw 4 KB at $3000)
    2. Load player.bin into py65 memory at $3000
    3. Call player_init via simulated JSR
    4. Call player_play N times, capturing AY register writes each tick
    5. Reconstruct 14-register frame state; diff or report

Usage:
    python3 harness.py m1              # run M1 hello-tone test
    python3 harness.py build-only      # just assemble, no simulation
"""

import os
import sys
import subprocess
from pathlib import Path

from py65.devices.mpu6502 import MPU
from py65.memory import ObservableMemory

# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent
SRC_DIR = PROJECT_ROOT / "src"
BUILD_DIR = PROJECT_ROOT / "build"

# -----------------------------------------------------------------------------
# DigiMuz AY bus addresses
# -----------------------------------------------------------------------------
DIGIMUZ_DATA_W = 0xFD22
DIGIMUZ_REG_SEL = 0xFD23

# Player jump table offsets (must match src/pt3_player.inc)
PLAYER_BASE = 0x3000
PLAYER_INIT = PLAYER_BASE + 0x00
PLAYER_LOAD_PT3 = PLAYER_BASE + 0x03
PLAYER_PLAY = PLAYER_BASE + 0x06
PLAYER_STOP = PLAYER_BASE + 0x09


# -----------------------------------------------------------------------------
# Build helper
# -----------------------------------------------------------------------------
def assemble_player():
    """Run ca65 + ld65 to produce build/player.bin."""
    BUILD_DIR.mkdir(exist_ok=True)

    env = os.environ.copy()
    cc65_bin = Path.home() / "cc65" / "usr" / "bin"
    if cc65_bin.is_dir():
        env["PATH"] = f"{cc65_bin}:{env.get('PATH', '')}"

    # Assemble
    r = subprocess.run(
        ["ca65", "-I", str(SRC_DIR), "-o",
         str(BUILD_DIR / "player.o"), str(SRC_DIR / "player.s")],
        env=env, capture_output=True, text=True)
    if r.returncode != 0:
        print("ca65 FAILED:")
        print(r.stderr)
        sys.exit(1)

    # Link
    r = subprocess.run(
        ["ld65", "-C", str(SRC_DIR / "player.cfg"),
         "-o", str(BUILD_DIR / "player.bin"), str(BUILD_DIR / "player.o")],
        env=env, capture_output=True, text=True)
    if r.returncode != 0:
        print("ld65 FAILED:")
        print(r.stderr)
        sys.exit(1)

    binsz = (BUILD_DIR / "player.bin").stat().st_size
    print(f"  [ok] Built build/player.bin ({binsz} bytes)")


# -----------------------------------------------------------------------------
# AY bus observer — tracks a shadow AY state matching what DigiMuz receives
# -----------------------------------------------------------------------------
class AYBusObserver:
    """Watches writes to $FD22 (data) and $FD23 (register select), maintains
    a model of AY register state matching what the real chip would see."""

    def __init__(self):
        self.selected_reg = 0
        self.ay_state = [0] * 16            # model of current AY register values
        self.write_log = []                  # list of (reg, value) tuples this frame
        self.frame_end_states = []           # snapshot at end of each frame

    def on_reg_sel(self, addr, value):
        """$FD23 write — latches register select."""
        self.selected_reg = value & 0x0F     # AY has 16 regs (we use 14)

    def on_data_write(self, addr, value):
        """$FD22 write — stores value into currently selected AY register."""
        self.ay_state[self.selected_reg] = value
        self.write_log.append((self.selected_reg, value))

    def snapshot_frame_end(self):
        """Called after each simulated player_play call."""
        self.frame_end_states.append(tuple(self.ay_state[:14]))
        self.write_log = []


# -----------------------------------------------------------------------------
# py65 simulation driver
# -----------------------------------------------------------------------------
def load_player_bin(mpu, path=None):
    """Load the assembled player binary into simulator memory at $3000."""
    path = path or (BUILD_DIR / "player.bin")
    data = Path(path).read_bytes()
    assert len(data) == 4096, f"player.bin expected 4096 bytes, got {len(data)}"
    for i, b in enumerate(data):
        mpu.memory[0x3000 + i] = b


def call_subroutine(mpu, addr, max_cycles=100000):
    """Simulate JSR to `addr` by pushing a sentinel return address,
    setting PC to `addr`, and running until PC hits the sentinel."""
    SENTINEL = 0xFF00
    # Push sentinel-1 onto stack (6502 JSR pushes return-1; RTS pops and +1)
    mpu.stPush(((SENTINEL - 1) >> 8) & 0xFF)
    mpu.stPush((SENTINEL - 1) & 0xFF)
    mpu.pc = addr

    cycles = 0
    while mpu.pc != SENTINEL and cycles < max_cycles:
        mpu.step()
        cycles += 1

    if cycles >= max_cycles:
        raise RuntimeError(f"call_subroutine hit cycle limit ({max_cycles})")
    return cycles


def build_simulator():
    """Construct MPU + observable memory with AY bus hooks."""
    observer = AYBusObserver()

    mem = ObservableMemory()
    mem.subscribe_to_write([DIGIMUZ_REG_SEL], observer.on_reg_sel)
    mem.subscribe_to_write([DIGIMUZ_DATA_W], observer.on_data_write)

    mpu = MPU(memory=mem)
    mpu.reset()

    return mpu, observer


# -----------------------------------------------------------------------------
# M1 test
# -----------------------------------------------------------------------------
# Expected AY state after M1's hardcoded "A-4 on ch A" setup:
#   R0 = 0x00  (tone A lo)
#   R1 = 0x01  (tone A hi)
#   R2 = 0x00  (tone B lo)
#   R3 = 0x00
#   R4 = 0x00
#   R5 = 0x00
#   R6 = 0x00  (noise period)
#   R7 = 0x3E  (mixer: only ch A tone enabled)
#   R8 = 0x0F  (ch A full vol)
#   R9 = 0x00
#   R10 = 0x00
#   R11 = 0x00  (env period lo)
#   R12 = 0x00  (env period hi)
#   R13 = 0x00  (env shape — in M1 we don't gate, so it gets written as 0)
M1_EXPECTED_FRAME = (
    0x00, 0x01,   # R0, R1
    0x00, 0x00,   # R2, R3
    0x00, 0x00,   # R4, R5
    0x00,         # R6
    0x3E,         # R7
    0x0F,         # R8
    0x00, 0x00,   # R9, R10
    0x00, 0x00,   # R11, R12
    0x00,         # R13
)


def run_m1_test(num_frames=60):
    """Run M1 test: init + N frames of player_play, verify constant output."""
    print("=" * 70)
    print("M1 — Hello Tone")
    print("=" * 70)

    print("  Assembling player...")
    assemble_player()

    print("  Building simulator...")
    mpu, obs = build_simulator()
    load_player_bin(mpu)

    print("  Calling player_init...")
    cycles = call_subroutine(mpu, PLAYER_INIT)
    print(f"  [ok] player_init took {cycles} CPU cycles")

    # Snapshot after init (not a "frame" per se, but should reflect setup state)
    obs.snapshot_frame_end()

    print(f"  Calling player_play × {num_frames}...")
    total_cycles = 0
    for frame in range(num_frames):
        c = call_subroutine(mpu, PLAYER_PLAY)
        total_cycles += c
        obs.snapshot_frame_end()

    avg = total_cycles / num_frames
    print(f"  [ok] player_play avg {avg:.0f} cycles/frame "
          f"({total_cycles} total over {num_frames} frames)")

    # Verify: all frames should be identical (M1 is deterministic, no state
    # advancement)
    print()
    print("  Validation:")

    # Skip frame 0 (the post-init snapshot) — look at frames from first
    # player_play onward (frames[1..num_frames])
    playback_frames = obs.frame_end_states[1:]

    all_match_expected = True
    all_identical = True
    first_frame = playback_frames[0]

    for i, frame in enumerate(playback_frames):
        if frame != first_frame:
            all_identical = False
            print(f"    FAIL: frame {i} differs from frame 0")
            print(f"       frame {i}: {' '.join(f'{b:02X}' for b in frame)}")
            print(f"       frame 0:  {' '.join(f'{b:02X}' for b in first_frame)}")
            break

    if first_frame != M1_EXPECTED_FRAME:
        all_match_expected = False
        print(f"    FAIL: frame state doesn't match expected")
        print(f"       got:      {' '.join(f'{b:02X}' for b in first_frame)}")
        print(f"       expected: {' '.join(f'{b:02X}' for b in M1_EXPECTED_FRAME)}")

    print(f"    all frames identical:  {'✓ PASS' if all_identical else '✗ FAIL'}")
    print(f"    frame matches M1 spec: {'✓ PASS' if all_match_expected else '✗ FAIL'}")
    print()
    print(f"  First playback frame state (R0..R13):")
    for i, val in enumerate(first_frame):
        mark = "  " if M1_EXPECTED_FRAME[i] == val else " *"
        print(f"    R{i:<2} = ${val:02X}{mark}")

    ok = all_identical and all_match_expected
    print()
    print("  " + ("M1 PASS 🎉" if ok else "M1 FAIL"))
    print("=" * 70)
    return 0 if ok else 1


# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "m1"
    if cmd == "build-only":
        assemble_player()
        sys.exit(0)
    elif cmd == "m1":
        sys.exit(run_m1_test())
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)
