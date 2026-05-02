# PT3 Player for Commodore Plus/4 + DigiMuz

A native 6502 assembly (CA65) player for **PT3 (ProTracker 3)** music files,
targeting the Commodore Plus/4 with a [DigiMuz AY-3-8910 expansion card](https://retrocombs.com/digimuz) or [DigiMoooZ](https://plus4world.powweb.com/forum/47657#top).

Bit-exact compatible with **Vortex Tracker II** — every register write to the
AY chip matches the VTII reference output, frame-for-frame, on a 19-file
test corpus including PT3.5/PT3.7/VTII1.0/VTII2.0 files using all four tone
tables and the full PT3 effect set.

---

## Status

✅ **M1–M6 complete and shipping** — full playback engine, bit-exact.

Validated against a 19-file PT3 corpus spanning PT3.5, PT3.7, VTII 1.0, and
VTII 2.0 — 100% bit-exact AY register match versus Vortex Tracker II reference
PSG output, frame-for-frame. Live-tested on real Plus/4 hardware with DigiMuz
expansion as well as YAPE in both PAL and NTSC modes.

---

## Embedding the player in your own program

The player exposes a 16-entry jump table at `$1100`. For most users, only the
first three matter (init, load song, tick). The rest are exposed for advanced
uses.

| Address | Symbol               | Description                                                            |
|---------|----------------------|------------------------------------------------------------------------|
| `$1100` | `PLAYER_INIT`        | One-time init: zero state, build note/volume tables                    |
| `$112A` | `PLAYER_INIT_SONG`   | Load PT3 file. In: `A`=hi, `X`=lo of file address                      |
| `$112D` | `PLAYER_TICK`        | Advance by one frame. Call at 50 Hz (PT3 spec; same on PAL and NTSC).  |

If you embed the player in your own program, you are responsible for 
calling PLAYER_TICK at 50 Hz — see src/pt3player.s lines ~184-200 for reference.

The remaining entries (`PLAYER_BUILD_NOTE_TABLE`, `PLAYER_DECODE_ROW`, etc.)
are documented in `src/pt3_player.inc` and exposed for advanced users who need
fine-grained access to the player's internals.

---

For a complete reference, see:

- **`src/pt3player.s`** — the standalone player
- **`src/play_template.s`** — template that bundles a specific PT3 via `.incbin`
- **`src/pt3_player.inc`** — full equates list with all jump table entries

Both reference programs include PAL/NTSC auto-detection and clean-screen
startup, ~250 bytes of bootstrap code.

---

## Memory map (default)

```
$0000-$00FF   Zero page (player uses $D8-$E8, the 17 B "OS-safe" area)
$1001-$10FF   BASIC stub + startup code (host program)
$1100-$2565   PT3 player library (engine + RODATA, ~5.2 KB)
$2566-$28D1   Player BSS (allocated at runtime)
$4000-$7FFF   PT3 song data (default; configurable in pt3player.s)
$8000-$BFFF   Free RAM (BASIC ROM area; standalone player disables ROM
              via $FF3F to expose this region — library users may keep
              ROM enabled if they don't need this RAM)
$FD21-$FD23   DigiMuz AY-3-8910 register interface
```


## Testing your own PT3 files

The player accepts any standard PT3 file (versions 3.0 through 3.7, plus
Vortex Tracker II 1.0/2.0 dialects). Tone tables 0-3 (ST, ASM-PT2, ASM-PT3,
REAL-PT3) are all supported, as is the full PT3 effect set: GLISS, PORTM,
SAMPLE-OFFSET, ORNAMENT-OFFSET, VIBRATO, ENVELOPE-SLIDE, NOISE-SLIDE, DELAY,
NO-NOTE-NO-LOOP, GLISS-NOTE, NOISE-BASE, and ENGLS.

To test a PT3 file: bundle it with the player using
`python3 tools/build_play_prg.py your_file.pt3`, which produces a self-contained
`.prg` runnable on YAPE or real Plus/4 hardware (with DigiMuz expansion).

---

## Building from source

Requirements: [`cc65`](https://cc65.github.io/) toolchain (`ca65` + `ld65`),
Python 3.10+ (for the build scripts).

```bash
# Build standalone pt3player.prg (loads PT3 from disk at runtime)
python3 tools/build_pt3player.py

# Bundle a specific PT3 into a self-contained .prg (PT3 embedded inside)
python3 tools/build_play_prg.py path/to/your.pt3
```

---

## Architecture

- **Pure subroutine library** — the host owns the IRQ. Player has zero
  knowledge of timing, screen, or system state. Just writes to AY when called.
- **Zero hardcoded tables** — note tables and volume tables are generated at
  runtime via Ivan Roshin's `NoteTableCreator` and `VolTableCreator`
  algorithms, ported line-by-line from Bulba's VTII10 r7 Z80 source. Saves
  ~1 KB of ROM compared to lookup tables.
- **PT3 stream is stateful** — same byte means different things depending on
  decoder state. Implementation matches Bulba's `PTDECOD` reference exactly.
- **Pre-computed pattern lengths** — patterns can have variable lengths
  (PT3.7 spec). We compute them all once at song load time so per-tick work
  fits inside the 35795-cycle 50 Hz IRQ budget on Plus/4 NTSC. The whole
  engine compiles to \$1100-\$2565 (~5.2 KB) plus ~876 B of BSS.

For deeper rationale, see [`docs/REFERENCES.md`](docs/REFERENCES.md) and
the heavily commented `src/player.s` (135 KB of source, half of which is
prose).

---

## Acknowledgments

This project would not exist without the work of three people who built and
documented the Vortex Tracker II ecosystem on ZX Spectrum and Windows
over the past two decades. Their decision to release source code publicly is
what made it possible for a Plus/4 player to exist at all.

- **Sergey Bulba** (S.V.Bulba) — author of the VTII Z80 player for ZX
  Spectrum (`VTII10 r7`, ©2004–2007) and the Pascal source for the desktop
  tracker (`trfuncs.pas`, ©2000–2009). The Pascal source served as the
  executable specification we worked against during development.
  The Z80 player is what supplied our note-table and volume-table generators.
  Project page: <http://bulba.untergrund.net/>

- **Ivan Roshin** — author of the `NoteTableCreator` and `VolTableCreator`
  algorithms inside Bulba's Z80 player. These are the runtime generators
  that produce the four PT3 tone tables (ST, ASM-PT2, ASM-PT3, REAL-PT3)
  and the 256-entry volume combination table.

- **Ivan Pirog** — maintainer of Vortex Tracker II 2.x (©2017–2019). The
  VTII 2.x source release is what the publicly available `trfuncs.pas` we
  ported from comes from
  ([backup](https://github.com/z00m128/vortextracker25) of Pirog's Bitbucket).

The PT3 music format itself was created by Bulba's tracker. This repository
does not bundle PT3 music files — bring your own. Use any of the many archives
maintained by the ZX Spectrum scene (such as <https://vtrd.in> or
<https://zxart.ee>) to obtain PT3 files for testing.

For attribution details and license carve-outs covering the ported algorithms,
see [`docs/THIRD_PARTY_NOTICES.md`](docs/THIRD_PARTY_NOTICES.md).

### Project work

- **Kris** (project owner) — test methodology, bit-exact validation strategy, 
  listening tests on YAPE and Plus/4 + DigiMuz hardware, that drove diagnosis
  of the R13 envelope-retrigger and pattern-boundary IRQ-overrun bugs.
- **Claude Opus 4.7** (Anthropic) — CA65 6502 implementation; pair-programmed
  with Kris against a private Python reference simulator and py65 test harness
  (developed alongside the player but not redistributed).

---

## License

MIT — see [`LICENSE`](LICENSE) for the full text.

Portions ported from Vortex Tracker II source remain governed by their
original authors' release terms; see
[`docs/THIRD_PARTY_NOTICES.md`](docs/THIRD_PARTY_NOTICES.md) for details
and the carve-out language in `LICENSE`.
