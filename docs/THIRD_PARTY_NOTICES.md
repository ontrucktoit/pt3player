# Third-Party Notices

This project's PT3 player would not exist without the work of three
people who built and documented the Vortex Tracker II (VTII) ecosystem
on ZX Spectrum and Windows:

- **Sergey Bulba** (S.V.Bulba) — author of the VTII Z80 player and the
  Pascal source for the desktop tracker.
- **Ivan Roshin** — author of the note-table and volume-table generators
  used inside Bulba's Z80 player.
- **Ivan Pirog** — maintainer of VTII 2.x and the public source release.

This document is the canonical record of which parts of this repository
are ports or adaptations of their work, and where the originals can be
found.

---

## 1. trfuncs.pas → src/player.s

**What we use:** the high-level PT3 pattern decoder and per-tick playback
state machine. We developed a Python reference simulator as a line-by-line
port of `trfuncs.pas` (with inline comments citing specific line numbers
for non-obvious behaviors), then translated that simulator into 6502
assembly. The Python simulator is for our internal tests.

**Original source:**
- Author: Sergey Bulba © 2000–2009
- Maintained from version 2.0 onward by Ivan Pirog © 2017–2019
- Distribution: part of the Vortex Tracker II Pascal source release
- Public mirror (with the exact `trfuncs.pas` we ported from):
  https://github.com/z00m128/vortextracker25/blob/main/trfuncs.pas
- Original distribution: http://bulba.untergrund.net/vortex_e.htm

**Files in this repository derived (transitively, via the private Python
port) from `trfuncs.pas`:**
- `src/player.s` — pattern stream decoder (M5a milestone), multi-channel
  driver (M5b), playback engine (M6), `m6_compute_pat_len`. The relevant
  section headers in `player.s` carry inline attribution back to
  `trfuncs.pas`.

---

## 2. NoteTableCreator → pt3_tables.py / build_note_table

**What we use:** the runtime generator that produces the four PT3 tone
frequency tables (ST, ASM-PT2, ASM-PT3, REAL-PT3) from a small seed
table. This is what lets a real PT3 player compute correct frequencies
for any of the four tone-table variants without hardcoding 96-entry
tables for each.

**Original source:**
- Author: **Ivan Roshin**
- Released as part of VTII10 r7 (PT3 player for ZX Spectrum)
- Containing copyright: Sergey Bulba © 2004–2007
- Quote from Bulba's release notes (`PROTRACKER372_PT3PLAY_H`,
  bulba.untergrund.net / mus.msx.click):

  > "Thanks to Andrey Bogdanovich aka Spectre for help and UniSearch;
  > **Ivan Roshin for tone and volume tables generators**;
  > Alone Coder for TS format description and help."

- Distribution: http://bulba.untergrund.net/ (VTII Z80 player package,
  also widely mirrored, e.g. http://mus.msx.click/index.php?title=PROTRACKER372_PT3PLAY_H)

**Files in this repository derived from NoteTableCreator:**
- `src/player.s` — `player_build_note_table` (M2 milestone). The 6502
  port mirrors Roshin's algorithm structure verbatim; the seed table
  values are unchanged.

---

## 3. VolTableCreator → pt3_tables.py / build_volume_table

**What we use:** the runtime generator for the 256-entry volume
combination table that maps `(channel_volume, sample_volume)` pairs to
final AY amplitude values. There are two variants ("old" for PT 3.xx..3.4r,
"new" for PT 3.4x+ and VTII 1.0); both come from the same algorithm
with a one-bit version switch.

**Original source:**
- Author: **Ivan Roshin** (same as NoteTableCreator above)
- Released as part of VTII10 r7
- Distribution: see (2) above

**Files in this repository derived from VolTableCreator:**
- `src/player.s` — `player_build_volume_table` (M3 milestone). The 6502
  port follows Roshin's algorithm with the "new" volume table selected
  by default (see behavioral note below).

**Important behavioral note:** Bulba's original Z80 player selects the
"old" table for PT3 < 4 and the "new" table for PT3 ≥ 4. VTII (the
desktop tracker, `trfuncs.pas`) overrides this and uses the "new" table
for **all** versions when generating reference PSG output. We follow
VTII's behavior, not the asm player's, so that we match VTII's PSG
files bit-for-bit. This decision is implemented in `src/player.s`
(M3 milestone) and matches `trfuncs.pas` `Calc_Volume(...)` behavior.

---

## 4. Reference-only (NOT ported, NOT included)

These projects helped shape our understanding but **no code from them
is in this repository**. They are listed here for completeness so future
maintainers know what to consult.

### Vince Weaver's PT3 specification

`README_pt3.txt` — informal English-language specification of the PT3
file format by Vince Weaver. We reference it for terminology and offset
numbers; we diverge from it whenever VTII's actual behavior contradicts
the spec. The specific divergences are listed in section 5 below.

### ZXTune (Vitamin/CAIG)

A cross-platform open-source chiptune player covering ~50 chip music
formats, including PT3.

- Source: https://bitbucket.org/zxtune/zxtune (GitHub mirror at
  https://github.com/vitamin-caig/zxtune)
- License: LGPL-3.0
- We did not port any code from ZXTune. It is listed in
  `docs/REFERENCES.md` as a tie-breaker / consistency-check resource.
  Because we did not include any LGPL-3.0 code, the LGPL-3.0 license
  does not propagate to this project.

### Vortex Tracker II (the binary application)

The Windows desktop tracker we used to **generate reference PSG dump
files** during development for bit-exact regression testing. PSG files
were produced by VTII's "Save as PSG" feature on PT3 modules composed
by their respective musicians; this corpus is **not** redistributed in
this repository — the music modules retain their composers' rights, and
users wishing to test the player should bring their own PT3 files
(see README for suggested sources). VTII the application is freely
redistributable from its official site (http://bulba.untergrund.net/).

---

## 5. Where we diverge from Vince Weaver's `README_pt3.txt`

Weaver's spec is informative but predates several VTII behaviors that
modern PT3 files rely on. Where the spec and VTII's actual playback
disagree, **we follow VTII** (because matching VTII bit-exact is the
goal). The following list is the complete set of divergences we found
during M4–M6 development. Future maintainers should treat these as
documented design choices, not bugs.

### Glossary — VTII names vs Weaver's spec terminology

The internal names below come from `trfuncs.pas` (Pascal source of
Vortex Tracker II). They are the names used in our `src/player.s`
section headers and in the divergence notes that follow. Readers
familiar only with Weaver's `README_pt3.txt` may find this mapping
useful:

| Our name (VTII) | Weaver's name / not in spec | What it is |
|-----------------|------------------------------|------------|
| `PD_ESAM`       | not named in spec; corresponds to pattern stream opcodes `$10-$1F` | "Envelope + SAMple" command — sets envelope shape, optional envelope period (2 bytes), and a sample number to apply. Despite Weaver's spec implying 4-byte length for envelope-bearing variants, real files (and `trfuncs.pas`) use 3 bytes (see 5.5). |
| `T_PACK`        | not in spec                  | Compact, packed encoding of one channel's track-state data inside a pattern. The pattern-row decoder unpacks `T_PACK` bytes into a `T1_` slot (one per channel) where the per-tick state machine reads them. |
| `T1_` slot      | not in spec                  | Per-channel scratch area where unpacked `T_PACK` data lives during pattern playback (one slot for each of the three AY channels A/B/C). |
| `SETENV`        | "envelope shape command" in Weaver's prose | Pattern-stream opcode that selects one of the 8 AY envelope shapes (R13 values 0/1/4/8-15). VTII encodes shape as `(opcode & 0x0F) - 1`; the `-1` is non-obvious (see 5.4). |
| `ORN`           | "ornament" (same name in spec) | Index into the file's ornament table. `ORN=0` has special meaning (see 5.6). |
| `tone_table` (`$63`) | "Frequency table" in Weaver | 0=ST, 1=ASM-PT2, 2=ASM-PT3, 3=REAL-PT3. Selects which of the four 96-entry note-frequency tables to use. |

### 5.1 Header offsets — pointer tables

The PT3 header layout in `src/player.s` matches Weaver's spec for
**fixed offsets and pointer-table starts** (Weaver got these right);
divergences below concern interpretation, not layout.

For reference, the layout we (and Weaver) use:

| Offset       | Size       | Field                      | Notes                                                             |
|--------------|-----------:|----------------------------|-------------------------------------------------------------------|
| `$63`        | 1 byte     | tone_table                 | 0..3 (see Glossary above)                                         |
| `$64`        | 1 byte     | initial speed/delay        |                                                                   |
| `$65`        | 1 byte     | max pattern number + 1     | Weaver's "Number of patterns+1"; bounds pattern-id values         |
| `$66`        | 1 byte     | loop position (LPosPtr)    | Index into position list to loop back to                          |
| `$67-$68`    | 2 bytes    | PatsPtrs (LE)              | Pointer to patterns table (3 × 16-bit per pattern: ch A/B/C)      |
| `$69-$A8`    | 64 bytes   | SamPtrs[32] (LE)           | 32 × 16-bit pointers to sample data                               |
| `$A9-$C8`    | 32 bytes   | OrnPtrs[16] (LE)           | 16 × 16-bit pointers to ornament data                             |
| `$C9…`       | variable   | position list              | bytes = pattern_id × 3, `$FF`-terminated                          |

### 5.2 Position list is double-encoded

The position list is terminated by `$FF` (Weaver's spec is correct on
this). However, `trfuncs.pas` and the VTII Z80 player use **two
independent ways** of finding the end: (a) walk until `$FF`, and (b)
use the patterns-table pointer at `$67-68` (the position list ends just
before patterns-table data begins). Real files agree on both; our M4
parser cross-checks them as a sanity gate.

### 5.3 Envelope period is big-endian

This is the **only** big-endian field in PT3. Everywhere else is
little-endian. Easy to miss in a port.

### 5.4 `SETENV` opcode shape encoding

Envelope shape = `(opcode_byte & 0x0F) - 1`. Subtracting 1 is required
and not in the spec.

### 5.5 `PD_ESAM` opcode consumes 3 bytes, not 4

(See Glossary for what `PD_ESAM` is.) Weaver's spec implies 4 bytes
for the envelope-bearing variants. Real files use 3:

- Opcode byte (`$11-$1F`)
- Envelope period high byte
- Envelope period low byte (note: big-endian — see 5.3)

…with the sample-number byte coming from a separate pattern-stream
slot, not the `PD_ESAM` payload. Confirmed against `trfuncs.pas`
state-machine length tables.

### 5.6 `ORN=0` implies envelope off (sometimes)

If a row sets `ORN=0` and `env_type` was not already set on that channel,
the envelope is disabled implicitly. Weaver's spec doesn't mention this
edge case.

### 5.7 `T_PACK` is unpacked into the `T1_` slot in REVERSE byte order

(See Glossary for what `T_PACK` and `T1_` are.) When the pattern-row
decoder unpacks a `T_PACK`-encoded channel's track data into the per-
channel `T1_` scratch slot, the bytes are written **in reverse order**
(highest target address first, lowest last). This is what `trfuncs.pas`
does. Weaver's spec does not describe `T_PACK` packing or unpacking at
all, so there is no "diverge from Weaver" here per se — but readers
porting from a Weaver-only understanding will not have this detail and
will get scrambled track data if they don't reverse the unpack.

### 5.8 Volume table selection diverges from Bulba's Z80 player

Bulba's original Z80 player (`VTII10 r7`) uses the "old" volume table
for PT3 < 4 and the "new" table for PT3 ≥ 4. **VTII (the desktop
tracker) overrides this and uses the "new" table for ALL versions when
generating reference PSG output.** We follow VTII, not Bulba's asm
player. This is the single biggest behavioral divergence between our
player and a strict reading of either the spec or the Z80 player. See
`docs/THIRD_PARTY_NOTICES.md` section 3 for the full rationale.

### 5.9 R13 (envelope shape register) sentinel handling

PT3 convention: `$FF` in the AY shadow register slot for R13 means
**skip R13 this frame**. On a real AY chip, **any write to R13
re-triggers the envelope generator**, restarting it from phase 0.
Naively writing R13 every frame (as some ports do, including an early
prototype of this player) causes envelope effects to reset 50× per
second instead of running their natural course. Our M6 implementation
correctly skips R13 writes when the shadow value is `$FF`.

---

## On the absence of formal license headers in the originals

The `trfuncs.pas` and VTII10 files carry only authorship + copyright
notices, not formal open-source license texts (MIT, GPL, etc.).
This is consistent with the demoscene / ZX-coder release tradition
where source is published openly on personal sites and FidoNet for
study, porting, and adaptation, with the social expectation that
derivative work credits the original authors. This project complies
with that expectation:

- Original authors are named in this file, in the per-file headers
  of derived files, and in the project README.
- Where we have ported algorithms wholesale, we say so and link back.
- We do not claim our MIT license over the third-party portions —
  see `LICENSE` for the explicit carve-out.

If any of the original authors (Sergey Bulba, Ivan Roshin, Ivan Pirog,
or their estates) would prefer different attribution language or
believe this project misuses their work, please open an issue at
https://github.com/ontrucktoit/pt3player/issues — we will adjust
immediately.
