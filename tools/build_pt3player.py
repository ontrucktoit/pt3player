#!/usr/bin/env python3
"""
Build the standalone pt3player.prg.

The output is a single .prg file containing:
  $1001-$100C   2-byte load addr + BASIC stub "10 SYS 4109"
  $100D-$10FF   Startup code (assembled from src/pt3player.s)
  $1100-$2FFF   zero fill
  $3000-$4FFF   player.bin (player engine + BSS, 8 KB)

NO PT3 is embedded. The user loads any PT3 module manually via the
Plus/4 machine monitor (default load address $6000, configurable in
src/pt3player.s as PT3_BASE).

Usage: python3 tools/build_pt3player.py
       (no arguments — reads src/pt3player.s, src/pt3player.cfg, and
        build/player.bin; writes build/pt3player.prg)

Requires cc65 toolchain (ca65 + ld65) on PATH or at /home/linumax/cc65/usr/bin.
"""
import os, sys, subprocess, hashlib

ROOT  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC   = os.path.join(ROOT, 'src')
BUILD = os.path.join(ROOT, 'build')

# Try to locate cc65 binaries
def find_cc65():
    """Return PATH (str) where ca65/ld65 can be found, or None if on PATH."""
    candidates = [
        '/home/linumax/cc65/usr/bin',  # Kris's install
        '/usr/local/cc65/bin',
        '/opt/cc65/bin',
    ]
    for c in candidates:
        if os.path.isfile(os.path.join(c, 'ca65')):
            return c
    # try to find ca65 on existing PATH
    for d in os.environ.get('PATH', '').split(':'):
        if d and os.path.isfile(os.path.join(d, 'ca65')):
            return None  # already on PATH
    raise SystemExit("ERROR: ca65/ld65 not found. Install cc65 or edit find_cc65() in this script.")


def run(cmd, env=None):
    print(f"  $ {' '.join(cmd)}")
    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout)
        print(r.stderr)
        raise SystemExit(f"Command failed: {' '.join(cmd)}")


def main():
    os.makedirs(BUILD, exist_ok=True)

    cc65_dir = find_cc65()
    env = os.environ.copy()
    if cc65_dir:
        env['PATH'] = f"{cc65_dir}:{env.get('PATH','')}"

    src_s   = os.path.join(SRC,   'pt3player.s')
    src_cfg = os.path.join(SRC,   'pt3player.cfg')
    obj     = os.path.join(BUILD, 'pt3player.o')
    startup = os.path.join(BUILD, 'pt3player_startup.bin')
    player  = os.path.join(BUILD, 'player.bin')
    out_prg = os.path.join(BUILD, 'pt3player.prg')

    if not os.path.exists(player):
        raise SystemExit(f"ERROR: {player} not found. Build the player engine first "
                         "(e.g. via tests/harness.py m6).")

    # Step 1: assemble pt3player.s
    print("[1/3] Assembling pt3player.s...")
    run(['ca65', src_s, '-o', obj], env=env)

    # Step 2: link
    print("[2/3] Linking with pt3player.cfg...")
    run(['ld65', '-C', src_cfg, obj, '-o', startup], env=env)

    # Step 3: assemble final .prg
    print("[3/3] Building final pt3player.prg...")
    startup_bytes = open(startup, 'rb').read()
    player_bytes  = open(player,  'rb').read()

    # Verify shapes
    if len(startup_bytes) != 257:
        print(f"  WARNING: startup.bin size {len(startup_bytes)} != 257 (load_addr_hdr + 255 B)")
    if len(player_bytes) != 0x2000:
        print(f"  WARNING: player.bin size {len(player_bytes)} != 8192")

    # PRG layout:
    #   bytes 0-1:        load addr ($01 $10 = $1001)
    #   bytes 2-256:      startup code (255 B at $1001-$10FF)
    #   then zero pad up to $3000
    #   then player.bin   (8 KB at $3000-$4FFF)
    # Total file size: 2 + 0x2000 + (0x3000 - 0x1100) + 0x2000 = 18434 B (~18 KB)
    out = bytearray()
    out.extend(startup_bytes)                       # 2 + 255 = 257 B  ($0000-$0100 in file)
    out.extend(b'\x00' * (0x3000 - 0x1100))         # zero fill $1100-$2FFF
    out.extend(player_bytes)                        # 8192 B  $3000-$4FFF

    with open(out_prg, 'wb') as f:
        f.write(out)

    sz  = len(out)
    md5 = hashlib.md5(out).hexdigest()

    print()
    print(f"  -> {out_prg}")
    print(f"     total {sz} B  (~{sz//1024} KB)")
    print(f"     md5={md5}")
    print(f"     load address: $1001")
    print(f"     start address (G xxxx): $100D ({0x100D})")
    print()
    print("USER WORKFLOW (on Plus/4 / YAPE):")
    print("  LOAD\"PT3PLAYER\",8,1")
    print("  (enter monitor, e.g. via SYS 1024 if TEDMON is built in)")
    print("  L \"TUNE.PT3\" 08 6000")
    print("  G 100D")
    print()


if __name__ == '__main__':
    main()
