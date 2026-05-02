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
- `src/player.s` — pattern stream decoder (`player_decode_row`),
  multi-channel driver (`player_decode_row_all`), playback engine
  (`player_tick`), `m6_compute_pat_len`. The relevant section headers
  in `player.s` carry inline attribution back to `trfuncs.pas`.

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
- `src/player.s` — `player_build_note_table`. The 6502
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
- `src/player.s` — `player_build_volume_table`. The 6502
  port follows Roshin's algorithm with the "new" volume table selected
  by default (see behavioral note below).

**Important behavioral note — volume table selection:** Bulba's original
Z80 player (`VTII10 r7`) selects the "old" table for PT3 < 4 and the
"new" table for PT3 ≥ 4. VTII (the desktop tracker, `trfuncs.pas`)
overrides this and uses the "new" table for **all** versions when
generating reference PSG output. We follow VTII's behavior, not the
Z80 asm player's, so that we match VTII's PSG files bit-for-bit. In
`src/player.s`, `player_init_song` calls
`player_build_volume_table` with a hard-coded `pt_version=7` regardless
of the file's actual PT3 version, which lands in the NEW variant branch
(`pt_version >= 5` → NEW). This matches `trfuncs.pas`'s `Calc_Volume(...)`
behavior. This is the single biggest behavioral divergence between our
player and a strict reading of either Deater's spec or the Z80 player.

---

## 4. Reference-only (NOT ported, NOT included)

These projects helped shape our understanding but **no code from them
is in this repository**. They are listed here for completeness so future
maintainers know what to consult.

### Vince "Deater" Weaver's PT3 specification

`README_pt3.txt` — informal English-language specification of the PT3
file format by Vince "Deater" Weaver, dated 10 September 2019. This
was our entry point into the format: Deater's writeup is the only
comprehensive English-language PT3 documentation we know of, and it
saved us significant time deciphering the Russian-commented Pascal
source.

The spec covers everything we needed for the player's pattern decoder
faithfully. One small detail it leaves ambiguous: under opcode `$40-$4f`
("set ornament") it notes "possibly setting 0 counts as disabling" —
in practice, `$40` (i.e. `ORN=0`) also implicitly disables the envelope
when no envelope was set on the current row (`row_env_type` still has
the sentinel `$FF`). Our implementation reflects this in `src/player.s`
(lines ~993-1004), matching `trfuncs.pas`.

### ZXTune (Vitamin/CAIG)

A cross-platform open-source chiptune player covering ~50 chip music
formats, including PT3.

- Source: https://bitbucket.org/zxtune/zxtune (GitHub mirror at
  https://github.com/vitamin-caig/zxtune)
- License: LGPL-3.0
- We did not port any code from ZXTune. It is mentioned here as a
  tie-breaker / consistency-check resource.
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

## 5. AY chip implementation note — R13 sentinel handling

This is **not** about the PT3 file format or Deater's spec — it's a
detail of how a PT3 player should drive the AY-3-8910 chip itself.

PT3 convention: `$FF` in the AY shadow register slot for R13 means
**skip R13 this frame**. On a real AY chip, **any write to R13
re-triggers the envelope generator**, restarting it from phase 0.
Naively writing R13 every frame (as some ports do, including an early
prototype of this player) causes envelope effects to reset 50× per
second instead of running their natural course.

Our implementation correctly skips R13 writes when the shadow value
is `$FF` (`src/player.s` lines ~1913-1964 — comment block titled
"Writing R13 to AY restarts the envelope generator, even with same
value").

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
