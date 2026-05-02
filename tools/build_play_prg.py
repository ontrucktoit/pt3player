#!/usr/bin/env python3
"""
Build a standalone <n>_play.prg by concatenating:
  startup.bin (255 B at $1001-$10FF, includes BASIC stub + jump to player)
  player.bin  (~5.2 KB at $1100-$2565)
  zero fill   ($2566-$3FFF)
  PT3 file    (at $4000+)

The single zero-fill region between the player and the PT3 is unfortunately
required because PRG files load contiguously from the load address: any
"hole" in addresses must be filled in the file. We cannot avoid that ~6.7 KB
gap without relinking the player to a higher address (which would defeat
the goal of having the player live in a single canonical location).

The output PRG is self-contained: load it on YAPE or real Plus/4 hardware
(with DigiMuz expansion), RUN, and the embedded PT3 plays automatically.

Usage: python3 tools/build_play_prg.py <pt3_path> [output_name]
"""
import os, sys, hashlib, subprocess

# Path to script's project root (for resolving src/, build/)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC  = os.path.join(ROOT, 'src')


def _find_cc65():
    """Locate cc65 toolchain (ca65 + ld65). Returns dir to prepend to PATH, or None."""
    candidates = [
        '/home/linumax/cc65/usr/bin',
        '/usr/local/cc65/bin',
        '/opt/cc65/bin',
    ]
    for c in candidates:
        if os.path.isfile(os.path.join(c, 'ca65')):
            return c
    for d in os.environ.get('PATH', '').split(':'):
        if d and os.path.isfile(os.path.join(d, 'ca65')):
            return None  # already on PATH
    raise SystemExit("ERROR: ca65/ld65 not found. Install cc65 toolchain.")


def _run(cmd, env=None):
    print(f"  $ {' '.join(cmd)}")
    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout)
        print(r.stderr)
        raise SystemExit(f"Command failed: {' '.join(cmd)}")


def _ensure_artifacts():
    """Build player.bin and play_template_startup.bin from src/ if not present."""
    os.makedirs(BUILD, exist_ok=True)
    cc65_dir = _find_cc65()
    env = os.environ.copy()
    if cc65_dir:
        env['PATH'] = f"{cc65_dir}:{env.get('PATH','')}"

    player = os.path.join(BUILD, 'player.bin')
    if not os.path.exists(player):
        print("[1/2] Building player.bin from src/player.s...")
        _run(['ca65', os.path.join(SRC, 'player.s'),
              '-o', os.path.join(BUILD, 'player.o')], env=env)
        _run(['ld65', '-C', os.path.join(SRC, 'player.cfg'),
              os.path.join(BUILD, 'player.o'), '-o', player], env=env)

    startup = os.path.join(BUILD, 'play_template_startup.bin')
    if not os.path.exists(startup):
        print("[2/2] Building play_template_startup.bin from src/play_template.s...")
        _run(['ca65', os.path.join(SRC, 'play_template.s'),
              '-o', os.path.join(BUILD, 'play_template.o')], env=env)
        _run(['ld65', '-C', os.path.join(SRC, 'play_template.cfg'),
              os.path.join(BUILD, 'play_template.o'),
              '-o', startup], env=env)

BUILD = os.path.join(ROOT, 'build')

PLAYER_LOAD_ADDR = 0x1100        # where player.bin is linked
PT3_LOAD_ADDR    = 0x4000        # where PT3 lives in memory
STARTUP_END      = 0x1100        # startup occupies $1001-$10FF (file addr $0000-$00FE
                                 # in PRG file is 2-byte header + 0x10FF-0x1001+1 = 257 B)


def build(pt3_path, out_name=None):
    if out_name is None:
        out_name = os.path.splitext(os.path.basename(pt3_path))[0] + '_play.prg'

    # Ensure player.bin and play_template_startup.bin exist (auto-build if not)
    _ensure_artifacts()

    startup = open(f'{BUILD}/play_template_startup.bin', 'rb').read()
    player  = open(f'{BUILD}/player.bin', 'rb').read()
    pt3     = open(pt3_path, 'rb').read()

    # startup.bin = 2-byte load addr + ($10FF - $1001 + 1) = 2 + 255 = 257 B
    assert len(startup) == 257, f"unexpected startup size {len(startup)} (want 257)"

    # player.bin = code + RODATA (no padding/fill in current cfg).
    # As long as it's smaller than (PT3_LOAD_ADDR - PLAYER_LOAD_ADDR) bytes, we're fine.
    max_player_size = PT3_LOAD_ADDR - PLAYER_LOAD_ADDR
    if len(player) > max_player_size:
        raise SystemExit(
            f"ERROR: player.bin size {len(player)} B exceeds available room "
            f"{max_player_size} B (between $1100 and $4000)"
        )

    # PT3 fits in 16 KB ($4000-$7FFF) without ROM gymnastics.
    if len(pt3) > 0x4000:
        print(f"  WARNING: PT3 size {len(pt3)} B exceeds $4000-$7FFF window ($4000 B)")

    # Build the PRG file:
    # bytes 0-1:        load addr ($01 $10 = $1001)
    # bytes 2-256:      startup code ($1001-$10FF, 255 B)
    # then player.bin   ($1100..)
    # then zero fill    until file offset reaches PT3_LOAD_ADDR - $1001
    # then PT3 file     ($4000+)
    out = bytearray()
    out.extend(startup)                                # 257 B (header + $1001-$10FF)
    out.extend(player)                                 # $1100..$1100+len(player)
    after_player = PLAYER_LOAD_ADDR + len(player)
    pad = PT3_LOAD_ADDR - after_player                 # zero fill until $4000
    out.extend(b'\x00' * pad)
    out.extend(pt3)

    out_path = f'{BUILD}/{out_name}'
    open(out_path, 'wb').write(out)
    sz = os.path.getsize(out_path)
    md5 = hashlib.md5(out).hexdigest()
    print(f"  {pt3_path}")
    print(f"    -> {out_path}")
    print(f"    PT3 {len(pt3)} B; total {sz} B; md5={md5}")
    return out_path


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    pt3 = sys.argv[1]
    name = sys.argv[2] if len(sys.argv) > 2 else None
    build(pt3, name)
