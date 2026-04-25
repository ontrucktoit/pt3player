#!/usr/bin/env python3
"""
PT3 Table Generators — Python port of Ivan Roshin's NoteTableCreator
and VolTableCreator algorithms.

Original Z80 source: VTII10 r7 (Vortex Tracker II PT3 player for ZX Spectrum),
                     released © 2004–2007 Sergey Bulba.

Per Bulba's release notes for VTII10:
    "Thanks to Andrey Bogdanovich aka Spectre for help and UniSearch;
     Ivan Roshin for tone and volume tables generators;
     Alone Coder for TS format description and help."

So the generators in this file are Ivan Roshin's algorithms; the wrapping
Z80 player is Bulba's. Source distribution: http://bulba.untergrund.net/
A public mirror of PROTRACKER372 PT3PLAY (Bulba's player containing the
Roshin generators) is at:
http://mus.msx.click/index.php?title=PROTRACKER372_PT3PLAY_H

This Python port is part of the PT3 player project for Commodore Plus/4 +
DigiMuz at https://github.com/ontrucktoit/pt3player. The port itself is
released under MIT — see LICENSE at the repository root. The original
algorithms (note-table seed table, depacking, generator state machine)
are Roshin's / Bulba's work, ported here line-by-line; see
docs/THIRD_PARTY_NOTICES.md for the full attribution.

Generates note frequency tables and volume combination tables at runtime
from the same compact seed data used in the original Z80 player. This
matches Vortex Tracker II / AY_Emul output bit-exactly — no hardcoded
tables anywhere.

Two generators:

  build_note_table(table_idx, version_is_old) -> list[int]
    Returns 96 16-bit tone period values.
    Index 0 = C-1 (lowest), 95 = B-8 (highest).
    table_idx: 0..3 (PT3 header byte 0x63)
    version_is_old: 1 if PT version < 4 (3.xx..3.4r), else 0

  build_volume_table(pt_version) -> list[int]
    Returns 256 bytes indexed as [(channel_vol << 4) | sample_vol].
    pt_version: e.g. 7 for PT 3.7. Internally splits at >=5 for new variant.

Both algorithms are direct transliterations of the Z80 asm so they can
also serve as a reference implementation for a future 6502 port.
"""


# ============================================================================
# T_PACK — compressed seed data for the 4 base tables
# ============================================================================
# Stored in the asm as a stream of either "absolute" (2 bytes: high, low) or
# "delta" (1 byte: +2*delta from previous value) records. Each of the 4 base
# tables contributes 12 consecutive values. After depacking, T1_ holds 49
# 16-bit words, written from the end of the buffer backwards by the asm loop.
#
# The 4 blocks correspond (in asm order) to base C-1 values 0x06EC, 0x066D,
# 0x0704, 0x07E0 — scaled *2 by the compressor.

T_PACK = [
    # Block 1: base #06EC*2 = 0x0DD8
    0x0D, 0xD8,
    0x0755 - 0x06EC, 0x07C5 - 0x0755, 0x083B - 0x07C5, 0x08B8 - 0x083B,
    0x093D - 0x08B8, 0x09CA - 0x093D, 0x0A5F - 0x09CA, 0x0AFC - 0x0A5F,
    0x0BA4 - 0x0AFC, 0x0C55 - 0x0BA4, 0x0D10 - 0x0C55,
    # Block 2: base #066D*2 = 0x0CDA
    0x0C, 0xDA,
    0x06CF - 0x066D, 0x0737 - 0x06CF, 0x07A4 - 0x0737, 0x0819 - 0x07A4,
    0x0894 - 0x0819, 0x0917 - 0x0894, 0x09A1 - 0x0917, 0x0A33 - 0x09A1,
    0x0ACF - 0x0A33, 0x0B73 - 0x0ACF, 0x0C22 - 0x0B73, 0x0CDA - 0x0C22,
    # Block 3: base #0704*2 = 0x0E08
    0x0E, 0x08,
    0x076E - 0x0704, 0x07E0 - 0x076E, 0x0858 - 0x07E0, 0x08D6 - 0x0858,
    0x095C - 0x08D6, 0x09EC - 0x095C, 0x0A82 - 0x09EC, 0x0B22 - 0x0A82,
    0x0BCC - 0x0B22, 0x0C80 - 0x0BCC, 0x0D3E - 0x0C80,
    # Block 4: base #07E0*2 = 0x0FC0  (ST table base, used by PT v3.7 / yerzmyey)
    0x0F, 0xC0,
    0x0858 - 0x07E0, 0x08E0 - 0x0858, 0x0960 - 0x08E0, 0x09F0 - 0x0960,
    0x0A88 - 0x09F0, 0x0B28 - 0x0A88, 0x0BD8 - 0x0B28, 0x0C80 - 0x0BD8,
    0x0D60 - 0x0C80, 0x0E10 - 0x0D60, 0x0EF8 - 0x0E10,
]


def depack_t_pack() -> list[int]:
    """Depack T_PACK into 49 16-bit words (T1_ buffer).

    Port of asm TP_0..TP_2 loop. The asm writes into the T1_ buffer
    backwards (from T1_+97 down to T1_+0, using DEC BC). So the first
    value unpacked ends up at T1_[48], last at T1_[0].

    Terminator: the loop ends when the low byte of the last written value
    equals 0xF0 (SUB #F8*2 / JR NZ in asm — effectively SUB 0xF0).
    """
    forward = []
    hl = 0
    i = 0
    while i < len(T_PACK):
        a = T_PACK[i]; i += 1
        if a >= 15 * 2:
            # Delta: new_value = previous + 2*a
            hl = (hl + 2 * a) & 0xFFFF
        else:
            # Absolute: A is HIGH byte, next byte is LOW
            if i >= len(T_PACK):
                break
            low = T_PACK[i]; i += 1
            hl = (a << 8) | low
        forward.append(hl)
        if (hl & 0xFF) == 0xF0:
            break

    # Pad/truncate to exactly 49 words
    if len(forward) < 49:
        forward.extend([0] * (49 - len(forward)))
    else:
        forward = forward[:49]

    # asm writes backwards -> T1_ is the forward list reversed
    return list(reversed(forward))


# ============================================================================
# Correction tables (TCOLD_*, TCNEW_*) — per-note fixups applied after the
# octave-halving loop. Each byte is (note_byte_offset | sign_bit). sign_bit=1
# means subtract 1, sign_bit=0 means add 1. Terminated by 0.
# ============================================================================

TCOLD_0 = [0x00+1, 0x04+1, 0x08+1, 0x0A+1, 0x0C+1, 0x0E+1, 0x12+1, 0x14+1,
           0x18+1, 0x24+1, 0x3C+1, 0]
TCOLD_1 = [0x5C+1, 0]
TCOLD_2 = [0x30+1, 0x36+1, 0x4C+1, 0x52+1, 0x5E+1, 0x70+1, 0x82, 0x8C, 0x9C,
           0x9E, 0xA0, 0xA6, 0xA8, 0xAA, 0xAC, 0xAE, 0xAE, 0]
TCOLD_3 = [0x1E+1, 0x22+1, 0x24+1, 0x28+1, 0x2C+1, 0x2E+1, 0x32+1, 0xBE+1, 0]
TCNEW_0 = [0x1C+1, 0x20+1, 0x22+1, 0x26+1, 0x2A+1, 0x2C+1, 0x30+1, 0x54+1,
           0xBC+1, 0xBE+1, 0]
TCNEW_1 = TCOLD_1                  # identical in asm
TCNEW_2 = [0x1A+1, 0x20+1, 0x24+1, 0x28+1, 0x2A+1, 0x3A+1, 0x4C+1, 0x5E+1,
           0xBA+1, 0xBC+1, 0xBE+1, 0]
TCNEW_3 = [0x56+1]                 # asm has no terminator here; falls into TCOLD_3


# ============================================================================
# NT_SELECTOR — picks base data offset + correction list for each
# (table_idx, version) combination.
#
# Each entry holds the raw byte stored in asm's NT_DATA table. Bit 0 is a flag
# controlling octave-halving rounding mode (see build_note_table):
#   bit 0 = 1: truncate (asm self-modifies L3 to AND A, clearing carry)
#   bit 0 = 0: round on shift carry (asm L3 stays NOP)
# The upper bits (after SRL) give the byte offset into T1_ of the 12 base
# values for this table.
#
# version_is_old: 0 = PT 3.4x..VTII1.0 (NEW), 1 = PT 3.xx..3.4r (OLD)
# ============================================================================

NT_SELECTOR = [
    # table 0 (PT default)
    [(50 * 2,      TCNEW_0),                 # NEW
     (50 * 2 + 1,  TCOLD_0)],                # OLD
    # table 1 (ST — most common in VTII)
    [(0 * 2 + 1,   TCNEW_1),
     (0 * 2 + 1,   TCOLD_1)],
    # table 2 (ASM)
    [(74 * 2,      TCNEW_2),
     (24 * 2,      TCOLD_2)],
    # table 3
    [(48 * 2,      TCNEW_3 + TCOLD_3),       # TCNEW_3 lacks terminator; chains to TCOLD_3
     (48 * 2,      TCOLD_3)],
]


def build_note_table(table_idx: int, version_is_old: int) -> list[int]:
    """Build 96-note tone period table.

    Direct port of Ivan Roshin's NoteTableCreator from Bulba's VTII10 r7.

    Args:
        table_idx: 0..3, PT3 header byte 0x63 (low 2 bits)
        version_is_old: 0 for PT 3.4x..VTII1.0, 1 for PT 3.xx..3.4r

    Returns:
        List of 96 16-bit tone period values. index 0 = C-1 (lowest pitch,
        longest period), index 95 = B-8 (highest pitch, shortest period).
    """
    table_idx &= 3
    version_is_old &= 1

    # 1) Depack T_PACK into T1_ buffer
    t1_ = depack_t_pack()

    # 2) Look up NT_DATA entry: raw byte encodes T1_ byte offset and round mode
    raw_byte, corr_list = NT_SELECTOR[table_idx][version_is_old]
    bit0 = raw_byte & 1                     # rounding mode flag
    t1_byte_offset = raw_byte >> 1          # actual byte offset into T1_
    t1_word_idx = t1_byte_offset // 2       # word index in our list
    truncate = (bit0 == 1)                  # asm L3 = AND A (clear carry)

    # 3) Fetch 12 base values for this table
    base_values = []
    for i in range(12):
        idx = t1_word_idx + i
        base_values.append(t1_[idx] if idx < len(t1_) else 0)

    # 4) Generate 8 octaves per base note by repeated halving
    # asm L2 loop: SRL B / RR C (16-bit right shift), then L3 (NOP or AND A)
    # decides whether carry from the shift is added back via ADC A,0.
    nt_ = [0] * 96
    for note_i in range(12):
        bc = base_values[note_i]
        for octave in range(8):
            # 16-bit right shift, LSB -> carry
            shift_carry = bc & 1
            bc = (bc >> 1) & 0x7FFF

            # L3: NOP (carry preserved) or AND A (carry cleared)
            carry_for_adc = 0 if truncate else shift_carry

            # LD A,C / ADC A,D (D=0) — add carry to low byte
            low = (bc & 0xFF) + carry_for_adc
            carry_out = 1 if low > 0xFF else 0
            low &= 0xFF

            # LD A,B / ADC A,D (D=0) — propagate carry to high byte
            high = ((bc >> 8) + carry_out) & 0xFF

            value = (high << 8) | low
            slot = note_i + octave * 12
            if slot < 96:
                nt_[slot] = value

    # 5) Special case: if using TC*_1 corrections, write 0xFD to NT_[byte 0x2E]
    # (asm: CP TCOLD_1 / LD (NT_+#2E),#FD)
    # NT_+0x2E is byte offset 46 = low byte of word 23 (B-2 note).
    if corr_list is TCOLD_1 or corr_list is TCNEW_1:
        nt_[23] = (nt_[23] & 0xFF00) | 0xFD

    # 6) Apply per-note corrections
    # Each byte: bit 0 = sign (1 = -1, 0 = +1), bits 1+ = word index.
    for corr_byte in corr_list:
        if corr_byte == 0:
            break
        word_idx = corr_byte >> 1
        sign = corr_byte & 1
        if word_idx < 96:
            low = nt_[word_idx] & 0xFF
            high_bits = nt_[word_idx] & 0xFF00
            if sign == 1:
                low = (low - 1) & 0xFF
            else:
                low = (low + 1) & 0xFF
            nt_[word_idx] = high_bits | low

    return nt_


# ============================================================================
# Volume table generator
# ============================================================================

def build_volume_table(pt_version: int) -> list[int]:
    """Build 256-byte volume combination table.

    Indexed as VT_[(channel_vol << 4) | sample_vol] -> final AY amplitude 0..15.

    Direct port of Ivan Roshin's VolTableCreator from Bulba's VTII10 r7.

    pt_version < 5 -> old table (PT 3.xx..3.4x)
    pt_version >= 5 -> new table with rounding (PT 3.5x..3.6x..VTII1.0)

    The algorithm effectively computes a logarithmic (channel * sample) / 16
    combination using 16-bit fixed-point arithmetic, matching the AY chip's
    own logarithmic D/A converter behavior.
    """
    vt = [0] * 256

    # Initial Z80 register state (per asm):
    #   CP 5 ; LD HL,#11 ; LD D,H ; LD E,H ; LD A,#17 ; JR NC,M1
    #   (version < 5:) DEC L ; LD E,L ; XOR A
    #   M1: LD (M2),A  -- M2 byte becomes 0x00 (NOP) or 0x17 (RLA)
    #
    # LD D,H / LD E,H with H=0 gives D=E=0, so DE = 0x0000 initially.
    H, L = 0x00, 0x11
    D, E = 0x00, 0x00
    if pt_version < 5:
        L = 0x10
        E = 0x10
        use_rla = False          # M2 = NOP
    else:
        use_rla = True           # M2 = RLA (rotate A left through carry)

    write_idx = 16               # IX = VT_+16 (first 16 entries stay 0)
    C = 0x10                     # combined counter; inner breaks every 16 iters
    carry = 0

    # INITV2 outer loop — runs until C wraps back to 0 (16 outer iterations)
    outer_iter = 0
    while outer_iter < 17:       # safety
        # PUSH HL (save)
        saved_H, saved_L = H, L

        # ADD HL,DE
        r = ((H << 8) | L) + ((D << 8) | E)
        carry = 1 if r > 0xFFFF else 0
        H, L = (r >> 8) & 0xFF, r & 0xFF

        # EX DE,HL
        H, L, D, E = D, E, H, L

        # SBC HL,HL — HL = -carry (0x0000 or 0xFFFF)
        v = (-carry) & 0xFFFF
        H, L = (v >> 8) & 0xFF, v & 0xFF

        # INITV1 inner loop
        while True:
            # LD A,L
            A = L

            # M2: NOP or RLA
            if use_rla:
                new_carry = (A >> 7) & 1
                A = ((A << 1) | carry) & 0xFF
                carry = new_carry
            # else NOP: A and carry unchanged

            # LD A,H (overwrites A with H, carry preserved)
            A = H

            # ADC A,0 (A = A + 0 + carry)
            r = A + carry
            A = r & 0xFF
            carry = 1 if r > 0xFF else 0

            # LD (IX),A / INC IX
            if write_idx < 256:
                vt[write_idx] = A
            write_idx += 1

            # ADD HL,DE
            r = ((H << 8) | L) + ((D << 8) | E)
            carry = 1 if r > 0xFFFF else 0
            H, L = (r >> 8) & 0xFF, r & 0xFF

            # INC C / LD A,C / AND 15 / JR NZ,INITV1
            C = (C + 1) & 0xFF
            if (C & 0x0F) == 0:
                break

        # POP HL (restore)
        H, L = saved_H, saved_L

        # LD A,E / CP #77 / JR NZ,M3 / INC E / M3:
        if E == 0x77:
            E = (E + 1) & 0xFF

        # LD A,C / AND A / JR NZ,INITV2
        if C == 0:
            break

        outer_iter += 1

    return vt


# ============================================================================
# Self-test
# ============================================================================

if __name__ == '__main__':
    nt = build_note_table(table_idx=1, version_is_old=0)

    notes = ['C-', 'C#', 'D-', 'D#', 'E-', 'F-', 'F#', 'G-', 'G#', 'A-', 'A#', 'B-']
    print("Note table 1 (ST), version NEW (PT 3.4x..VTII1.0):")
    for octave in range(8):
        row = []
        for n in range(12):
            idx = octave * 12 + n
            row.append(f"{notes[n]}{octave+1}={nt[idx]:04X}")
        print("  " + "  ".join(row))

    # Expected values measured from VTII-generated yerzmyey_ref.psg
    checks = [
        (45, 0x011C, "A-4"),
        (46, 0x010A, "A#-4"),   # famous off-by-one from naive bit-shift
        (47, 0x00FC, "B-4"),
        (48, 0x00EF, "C-5"),
    ]
    print("\nCritical values check:")
    all_ok = True
    for idx, expected, name in checks:
        status = "OK" if nt[idx] == expected else "FAIL"
        if status == "FAIL":
            all_ok = False
        print(f"  {name:5s} (idx {idx}): {nt[idx]:04X}  expected {expected:04X}  [{status}]")

    print("\nVolume table, PT 3.7 (new variant):")
    vt = build_volume_table(pt_version=7)
    print("     sample_vol: 0  1  2  3  4  5  6  7  8  9  A  B  C  D  E  F")
    for cv in range(16):
        row = f"  ch_vol={cv:2d}: "
        for sv in range(16):
            row += f"{vt[cv * 16 + sv]:2X} "
        print(row)

    print("\nSanity checks on volume table:")
    checks_vt = [
        (0,  0,  0,  "ch=0 sv=0: silent"),
        (0,  15, 0,  "ch=0 sv=F: silent (channel mutes sample)"),
        (15, 0,  0,  "ch=F sv=0: silent (sample mutes)"),
        (15, 15, 15, "ch=F sv=F: full pass-through"),
    ]
    for cv, sv, expected, desc in checks_vt:
        actual = vt[(cv << 4) | sv]
        status = "OK" if actual == expected else "FAIL"
        if status == "FAIL":
            all_ok = False
        print(f"  {desc:45s}  expected {expected:2d}  got {actual:2d}  [{status}]")

    print(f"\n{'=' * 60}")
    print("OVERALL: " + ("ALL CHECKS PASSED" if all_ok else "SOME CHECKS FAILED"))
