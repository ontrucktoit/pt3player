# Third-Party Notices

This project's PT3 player would not exist without the work of three
people who built and documented the Vortex Tracker II (VTII) ecosystem
on ZX Spectrum, MSX, and Windows:

- **Sergey Bulba** (S.V.Bulba) — author of the VTII Z80 player and the
  Pascal source for the desktop tracker.
- **Ivan Roshin** — author of the note-table and volume-table generators
  used inside Bulba's Z80 player.
- **Ivan Pirog** — maintainer of VTII 2.x and the public source release.

This document is the canonical record of which parts of this repository
are ports or adaptations of their work, and where the originals can be
found.

---

## 1. trfuncs.pas → pt3_simulator.py + pt3_pattern_decoder.py

**What we use:** the high-level PT3 pattern decoder and per-tick playback
state machine. Our Python implementation is a line-by-line port; many
inline comments in `tools/pt3_python_sim/pt3_simulator.py` and
`pt3_pattern_decoder.py` cite specific line numbers in `trfuncs.pas`
for non-obvious behaviors.

**Original source:**
- Author: Sergey Bulba © 2000–2009
- Maintained from version 2.0 onward by Ivan Pirog © 2017–2019
- Distribution: part of the Vortex Tracker II Pascal source release
- Public mirror (with the exact `trfuncs.pas` we ported from):
  https://github.com/z00m128/vortextracker25/blob/main/trfuncs.pas
- Original distribution: http://bulba.untergrund.net/vortex_e.htm

**Files in this repository derived from `trfuncs.pas`:**
- `tools/pt3_python_sim/pt3_simulator.py` — playback engine
- `tools/pt3_python_sim/pt3_pattern_decoder.py` — pattern stream decoder

The C/A65 player (`src/player.s`) inherits this logic transitively
through the Python port, with attribution in the relevant section
headers (M5a pattern decoder, M5b multi-channel driver, M6 playback
engine, `m6_compute_pat_len`).

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
- `tools/pt3_python_sim/pt3_tables.py` — function `build_note_table()`
- `src/player.s` — `player_build_note_table` (M2 milestone)

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
- `tools/pt3_python_sim/pt3_tables.py` — function `build_volume_table()`
- `src/player.s` — `player_build_volume_table` (M3 milestone)

**Important behavioral note:** Bulba's original Z80 player selects the
"old" table for PT3 < 4 and the "new" table for PT3 ≥ 4. VTII (the
desktop tracker, `trfuncs.pas`) overrides this and uses the "new" table
for **all** versions when generating reference PSG output. We follow
VTII's behavior, not the asm player's, so that we match VTII's PSG
files bit-for-bit. This decision is documented in
`tools/pt3_python_sim/pt3_simulator.py` near the `build_volume_table(pt_version=7)`
call site.

---

## 4. Reference-only (NOT ported, NOT included)

These projects helped shape our understanding but **no code from them
is in this repository**. They are listed here for completeness so future
maintainers know what to consult.

### Vince Weaver's PT3 specification

`README_pt3.txt` — informal English-language specification of the PT3
file format. We reference it for terminology and offset numbers; we
diverge from it whenever VTII's actual behavior contradicts the spec
(see the design notes in `tools/pt3_python_sim/pt3_simulator.py`).

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
files** for our test corpus. The `.psg` files in
`tools/pt3_python_sim/test_files/` were produced by VTII's "Save as PSG"
feature on PT3 modules composed by their respective musicians (each
file has its composer credited in its filename). VTII the application
is freely redistributable from its official site
(http://bulba.untergrund.net/), and the music modules retain their
composers' rights — they are included here under fair use for testing
and reference purposes only and are not relicensed by this project.

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
