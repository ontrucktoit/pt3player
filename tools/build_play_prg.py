#!/usr/bin/env python3
"""
Build a standalone <name>_play.prg by concatenating:
  startup.bin (255 B at $1001-$10FF, includes BASIC stub + jump to player)
  zero fill   ($1100-$2FFF)
  player.bin  (8 KB at $3000-$4FFF)
  zero fill   ($5000-$7FFF)
  PT3 file    (at $8000+)

Usage: python3 tools/build_play_prg.py <pt3_path> [output_name]
"""
import os, sys, hashlib

BUILD = 'build'

def build(pt3_path, out_name=None):
    if out_name is None:
        out_name = os.path.splitext(os.path.basename(pt3_path))[0] + '_play.prg'

    startup = open(f'{BUILD}/luchibobra_startup.bin','rb').read()
    player  = open(f'{BUILD}/player.bin','rb').read()
    pt3     = open(pt3_path, 'rb').read()

    assert len(startup) == 257
    assert len(player)  == 0x2000
    if len(pt3) > 0x4000:
        print(f"  WARNING: PT3 size {len(pt3)} B exceeds $8000-$BFFF window ($4000 B)")

    out = bytearray()
    out.extend(startup)
    out.extend(b'\x00' * (0x3000 - 0x1100))
    out.extend(player)
    out.extend(b'\x00' * (0x8000 - 0x5000))
    out.extend(pt3)

    out_path = f'{BUILD}/{out_name}'
    open(out_path,'wb').write(out)
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
