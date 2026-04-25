#!/usr/bin/env python3
"""
Build luchibobra_play.prg by concatenating:
  startup.bin (255 B at $1001-$10FF)
  zero fill   ($1100-$2FFF: 7936 B)
  player.bin  (8 KB at $3000-$4FFF)
  zero fill   ($5000-$7FFF: 12288 B)
  PT3 file    (at $8000+)

Output: build/luchibobra_play.prg
"""
import os, sys

BUILD = 'build'
PT3 = 'tests/pt3/luchibobra_pt3_player_bug_fix_2000.pt3'

def main():
    startup = open(f'{BUILD}/luchibobra_startup.bin','rb').read()
    player  = open(f'{BUILD}/player.bin','rb').read()
    pt3     = open(PT3, 'rb').read()

    # Sanity sizes
    assert len(startup) == 257, f"startup must be 2+255=257 B (PRG hdr + body), got {len(startup)}"
    assert len(player)  == 0x2000, f"player must be 8 KB, got {len(player)}"
    print(f"  startup.bin: {len(startup)} B")
    print(f"  player.bin:  {len(player)} B")
    print(f"  pt3 file:    {len(pt3)} B")

    out = bytearray()
    # $1001-$10FF: startup (the cfg wrote PRG header in first 2 bytes)
    out.extend(startup)
    # Pad to $3000 (= file offset $3000 - $1001 + 2 = $2001 from start of file)
    # The PRG header is 2 bytes, so file_offset = $1001 -> 0, $3000 -> $1FFF
    # Actually: PRG layout is [load_lo, load_hi, byte0_at_$1001, byte1_at_$1002, ...]
    # So data byte at $X = file offset (X - 0x1001 + 2). For $3000: 0x3000 - 0x1001 + 2 = 0x2001.
    # Currently len(out) = 255 bytes (startup includes the 2-byte header? Yes, startup
    # is the .prg output of ld65 with the BASIC + CODE segments — includes 2-byte hdr).
    # So len(out) covers $1001-$10FF inclusive = 255 B (header + 253 body? no).
    # Actually startup.bin is exactly 255 bytes. file offset 0,1 = load addr. data offset
    # 2..254 = $1001..$10FF = 253 bytes of code/basic. But cfg said HEADER size $0C +
    # STARTUP size $F3 = $FF = 255 — total user bytes. + 2-byte ld65 PRG header = 257?
    # Let's just check what we got:
    print(f"  startup load addr: ${startup[1]:02X}{startup[0]:02X}")
    # If startup[0:2] = $01,$10, then bytes 2..254 are $1001..$10FF (253 bytes). Need
    # to pad up to $3000-1 inclusive then append player.bin.
    # File size when done = 2 (hdr) + ($BFFF - $1001 + 1) - depends on PT3 length.

    # Pad zero from end of startup ($1100) to $2FFF (start of player at $3000)
    fill_a = 0x3000 - 0x1100
    out.extend(b'\x00' * fill_a)
    print(f"  fill $1100-$2FFF: {fill_a} B")

    # Append player.bin at $3000
    out.extend(player)

    # Pad zero from $5000 to $7FFF (start of PT3 at $8000)
    fill_b = 0x8000 - 0x5000
    out.extend(b'\x00' * fill_b)
    print(f"  fill $5000-$7FFF: {fill_b} B")

    # Append PT3 at $8000
    out.extend(pt3)

    # Total length: 2 hdr + (last_addr - $1001 + 1)
    last_addr = 0x8000 + len(pt3) - 1
    expected = 2 + (last_addr - 0x1001 + 1)
    print(f"  last byte at: ${last_addr:04X}")
    print(f"  expected file size: {expected} B")
    print(f"  actual:             {len(out)} B")
    assert len(out) == expected, f"size mismatch: {len(out)} vs {expected}"

    out_path = f'{BUILD}/luchibobra_play.prg'
    open(out_path,'wb').write(out)
    sz = os.path.getsize(out_path)
    print(f"\nWrote {out_path} ({sz} B)")
    # md5 for repro
    import hashlib
    print(f"md5: {hashlib.md5(out).hexdigest()}")

if __name__ == '__main__':
    main()
