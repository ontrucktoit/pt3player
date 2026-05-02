#!/usr/bin/env python3
"""
Build the standalone pt3player.prg.

The output is a single .prg file containing:
  $1001-$100C   2-byte load addr + BASIC stub "10 SYS 4109"
  $100D-$10FF   Startup code (assembled from src/pt3player.s)
  $1100-$2565   player.bin (~5.2 KB)

NO PT3 is embedded. The user loads any PT3 module manually via the
Plus/4 machine monitor (default load address $4000, configurable in
src/pt3player.s as PT3_BASE).

Total file size: ~5.5 KB (vs ~16 KB for the previous layout). This makes
loading from SD2IEC ~3x faster because there's no zero-fill region in
the middle of the file.

Usage: python3 tools/build_pt3player.py
       (no arguments — reads src/pt3player.s, src/pt3player.cfg, and
        build/player.bin; writes build/pt3player.prg)

Requires cc65 toolchain (ca65 + ld65) on PATH or at /home/linumax/cc65/usr/bin.
"""
import os, sys, subprocess, hashlib

ROOT  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC   = os.path.join(ROOT, 'src')
BUILD = os.path.join(ROOT, 'build')


def find_cc65():
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
            return None
    raise SystemExit("ERROR: ca65/ld65 not found. Install cc65.")


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

    # Step 1: build player.bin from src/player.s if missing
    # (player.bin is the 5.2 KB engine library at $1100-$2565)
    if not os.path.exists(player):
        print("[1/4] Building player.bin from src/player.s...")
        player_s   = os.path.join(SRC,   'player.s')
        player_cfg = os.path.join(SRC,   'player.cfg')
        player_o   = os.path.join(BUILD, 'player.o')
        run(['ca65', player_s, '-o', player_o], env=env)
        run(['ld65', '-C', player_cfg, player_o, '-o', player], env=env)
        if not os.path.exists(player):
            raise SystemExit(f"ERROR: ld65 ran but {player} was not produced")

    # Step 2: assemble pt3player.s (the standalone wrapper around player.bin)
    print("[2/4] Assembling pt3player.s...")
    run(['ca65', src_s, '-o', obj], env=env)

    # Step 3: link wrapper
    print("[3/4] Linking with pt3player.cfg...")
    run(['ld65', '-C', src_cfg, obj, '-o', startup], env=env)

    # Step 4: assemble final .prg by concatenating startup + player.bin
    print("[4/4] Building final pt3player.prg...")
    startup_bytes = open(startup, 'rb').read()
    player_bytes  = open(player,  'rb').read()

    # startup.bin = 2-byte load addr + content $1001-$10FF (255 B) = 257 B total
    if len(startup_bytes) != 257:
        print(f"  WARNING: startup.bin size {len(startup_bytes)} != 257")

    # player.bin should be the real code+RODATA size (no fill padding)
    print(f"  player.bin: {len(player_bytes)} B (engine code + RODATA, no padding)")

    # PRG layout (gęsty, bez padding'u w środku):
    #   bytes 0-1:        load addr ($01 $10 = $1001)
    #   bytes 2-256:      startup code (255 B at $1001-$10FF)
    #   then player.bin   ($1100..)
    #   END
    out = bytearray()
    out.extend(startup_bytes)        # 2 + 255 = 257 B  ($file 0-256, $mem $1001-$10FF)
    out.extend(player_bytes)         # ($mem $1100..$1100+len(player)-1)

    with open(out_prg, 'wb') as f:
        f.write(out)

    sz  = len(out)
    md5 = hashlib.md5(out).hexdigest()
    last_addr = 0x1100 + len(player_bytes) - 1

    print()
    print(f"  -> {out_prg}")
    print(f"     total {sz} B  (~{sz//1024} KB; previous layout was ~16 KB)")
    print(f"     md5={md5}")
    print(f"     load address: $1001")
    print(f"     player engine: $1100-${last_addr:04X}")
    print(f"     start address (G xxxx): $100D ({0x100D})")
    print()
    print("USER WORKFLOW (on Plus/4 / YAPE):")
    print("  LOAD\"PT3PLAYER\",8,1")
    print("  (enter monitor, e.g. via SYS 1024 if TEDMON is built in)")
    print("  L \"TUNE.PT3\" 08 4000")
    print("  G 100D")
    print()


if __name__ == '__main__':
    main()
