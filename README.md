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

| Test corpus              | Files | Result                             |
|--------------------------|------:|------------------------------------|
| Bundled regression set   |     7 | 100% bit-exact PSG match vs VTII   |
| Extended test corpus     |    19 | Engine handles all without crash   |
| Live hardware test       |   1+1 | Plus/4 + DigiMuz, plus YAPE PAL/NTSC |

---

## Embedding the player in your own program

The player exposes a 16-entry jump table at `$1100`. For most users, only the
first three matter (init, load song, tick). The rest are exposed for testing
and advanced uses.

| Address | Symbol               | Description                                                            |
|---------|----------------------|------------------------------------------------------------------------|
| `$1100` | `PLAYER_INIT`        | One-time init: zero state, build note/volume tables                    |
| `$112A` | `PLAYER_INIT_SONG`   | Load PT3 file. In: `A`=hi, `X`=lo of file address                      |
| `$112D` | `PLAYER_TICK`        | Advance by one frame. Call at 50 Hz (PT3 spec; same on PAL and NTSC).  |

If you embed the player in your own program, you are responsible for 
calling PLAYER_TICK at 50 Hz — see src/pt3player.s lines ~184-200 for reference.

The remaining entries (`PLAYER_BUILD_NOTE_TABLE`, `PLAYER_DECODE_ROW`, etc.)
are documented in `src/pt3_player.inc` and used primarily by the regression
harness in `tests/harness.py`.

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
$8000-$BFFF   Free RAM (with ROM disabled at startup)
$FD21-$FD23   DigiMuz AY-3-8910 register interface
```


## Test corpus

Bit-exact regression on 7 PT3 files covering all PT3 versions and effect
combinations:

| File                                    | Version  | FL | Effects                           |
|-----------------------------------------|----------|----|-----------------------------------|
| `yerzmyey_fifteen_colours_2014.pt3`     | PT3.7    | 2  | DELAY                             |
| `v0yager_blobbzgame.pt3`                | VTII 1.0 | 1  | DELAY                             |
| `luchibobra_pt3_player_bug_fix_2000.pt3`| PT3.5    | 0  | "bug f!x" stress test (Black Groove) |
| `leebee_farm.pt3`                       | PT3.5    | 0  | GLISS + PORTM + DELAY             |
| `pator_cat.pt3`                         | VTII 1.0 | 1  | GLISS + DELAY + ENGLS             |
| `kuvo_free_sky.pt3`                     | PT3.7    | 2  | GLISS + VIBRATO + NOISE           |
| `mmcm_xiaomi.pt3`                       | PT3.7    | 2  | DiHalt 2025 entry                 |

Plus a 12-file extended corpus in `tests/pt3_corpus/` for additional engine
coverage. All files attributed to their composers in
[`docs/THIRD_PARTY_NOTICES.md`](docs/THIRD_PARTY_NOTICES.md).

---

## Building from source

Requirements: [`cc65`](https://cc65.github.io/) toolchain (`ca65` + `ld65`),
Python 3.10+ (for the regression harness).

```bash
# Build the engine + run full regression
PATH=/path/to/cc65/bin:$PATH python3 tests/harness.py all

# Build standalone pt3player.prg
python3 tools/build_pt3player.py

# Bundle a specific PT3 into a self-contained .prg
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
documented the Vortex Tracker II ecosystem on ZX Spectrum, MSX, and Windows
over the past two decades. Their decision to release source code publicly is
what made it possible for a Plus/4 player to exist at all.

- **Sergey Bulba** (S.V.Bulba) — author of the VTII Z80 player for ZX
  Spectrum (`VTII10 r7`, ©2004–2007) and the Pascal source for the desktop
  tracker (`trfuncs.pas`, ©2000–2009). The Pascal source is the executable
  specification that our Python simulator was line-by-line ported from.
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

The PT3 music format itself was created by Bulba's tracker. Test files in
this repository were composed by their respective musicians (credited in
filenames), with reference PSG dumps generated by VTII.

For per-file attribution and license carve-outs, see
[`docs/THIRD_PARTY_NOTICES.md`](docs/THIRD_PARTY_NOTICES.md).

### Project work

- **Kris** (project owner) — test methodology, bit-exact validation strategy, 
  listening tests on YAPE and Plus/4 + DigiMuz hardware, that drove diagnosis
  of the R13 envelope-retrigger and pattern-boundary IRQ-overrun bugs.
- **Claude Opus 4.7** (Anthropic) — Python reference simulator, CA65 6502
  implementation, py65 test harness — pair-programmed with Kris.

---

## License

MIT — see [`LICENSE`](LICENSE) for the full text.

Portions ported from Vortex Tracker II source remain governed by their
original authors' release terms; see
[`docs/THIRD_PARTY_NOTICES.md`](docs/THIRD_PARTY_NOTICES.md) for details
and the carve-out language in `LICENSE`.
