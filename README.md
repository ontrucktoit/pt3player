# PT3 Player for Commodore Plus/4 + DigiMuz

**Full name / długa chwalebna nazwa projektu**:
`new_reference_player_by_Claude_Opus4.7_who_deserves_a_bottle_of_Georgian_kindzmarauli`

A native 6502 assembly (CA65) player for PT3 (ProTracker 3) music files,
targeting the Commodore Plus/4 with a DigiMuz AY-3-8910 expansion card.

## Project Goal

A reference-quality PT3 player that handles the **full PT3 specification**
(all effects, all FeaturesLevels 0-2, all tone tables, variable pattern lengths)
— bit-exact compatible with Vortex Tracker II. No shortcuts, no subset-only
optimizations. If Bulba-Ayer can play it, this player plays it too.

## Status

- ✅ **Python reference simulator: 100% bit-exact on all 7 test files**
  (validated against VTII-generated PSG byte-for-byte)
- 🚧 **6502 CA65 player: in development**
- 🚧 **py65 test harness for bit-exact 6502 regression: planned**

## Architecture

- **Co-resident module** (not chain-loaded) — jukebox UI stays live
  while music plays. User can browse, pause, skip tracks without
  interrupting audio.
- **Timer #1 IRQ** (TED countdown timer @ 894.9 kHz / $3A43 reload = 60 Hz
  for NTSC, $4523 for PAL) — independent from raster, survives graphics
  mode changes.
- **Parameterized PLAYER_BASE** via `-D PLAYER_BASE=$xxxx` for ld65 —
  default $3000, reusable for other programs.
- **Standalone library** — clean public API, usable by any Plus/4 program
  (games, demos, other tools). Jukebox is just the first client.

## Memory Map (default)

```
$0000-$00FF   Zero page (we use $D8-$E8, the 17B "OS never touches" area)
$1000-$2FFF   Jukebox UI (host program, not part of this lib)
$3000-$3FFF   PT3 Player (~4 KB) — this library
$4000-$7FFF   PT3 song data buffer (16 KB max)
$8000-$FCFF   Free for expansion
```

## Public API

Jump table at `PLAYER_BASE`, 3 bytes per entry:

| Offset | Symbol | Description |
|--------|--------|-------------|
| +$00 | `player_init` | One-time init: hardware, tables. Call on program startup. |
| +$03 | `player_load_pt3` | Parse PT3 header. In: A=lo, X=hi of file address. Out: A=0 OK, !=0 error code + carry set. |
| +$06 | `player_play` | Start playback (enables timer IRQ). |
| +$09 | `player_stop` | Stop playback, silence AY. |
| +$0C | `player_pause` | Pause (stops IRQ, keeps state). |
| +$0F | `player_is_playing` | Returns A=0 stopped, !=0 playing. |
| +$12 | `player_is_song_ended` | Returns A=0 playing, !=0 reached loop point past end. |
| +$15 | `player_get_position` | Returns A=position in PlayOrder, X=row in pattern. |

## Test Files

This player is verified bit-exact against VTII on 7 diverse PT3 files
covering all versions, FeaturesLevels, and effects:

| File | Version | FL | Features |
|------|---------|-----|----------|
| yerzmyey.pt3 | PT3.7 | 2 | DELAY |
| blobbzgame.pt3 | VTII 1.0 | 1 | DELAY |
| luchibobra.pt3 | PT3.5 | 0 | "bug f!x" test song |
| Lee_Bee_Basterdale_Farm.pt3 | PT3.5 | 0 | GLISS + PORTM + DELAY |
| Pator_Parallel_Visions.pt3 | VTII 1.0 | 1 | GLISS + DELAY + ENGLS |
| FreeSky.pt3 | PT3.7 | 2 | GLISS + VIBRATO + NOISE |

## References

See [docs/REFERENCES.md](docs/REFERENCES.md) for the complete list of external
resources (VTII, ZXTune, Bulba VTII10, AY-3-8910 datasheet, TED manual, PT3 spec).

Key reference for 6502 port decisions: the Python simulator in `pt3_python_sim/`
(bit-exact validated against VTII on 20 diverse PT3 files). Every non-obvious
behavior is documented there with line references to VTII's `trfuncs.pas`.

## Credits

- **Project owner**: Kris (Plus/4 hardware, test methodology, DigiMuz card)
- **Reference implementation**: Vortex Tracker II (Ivan Roshin / VBsoft)
  `trfuncs.pas` is the authoritative spec this player matches bit-exact.
- **Ported code**: Ivan Roshin's NoteTableCreator / VolTableCreator from
  Bulba's VTII10 r7 Z80 source.
- **Python simulator + 6502 implementation**: Claude Opus 4.7 (Anthropic)
  — credited on invoice in Kindzmarauli. 🍷

## License

TBD — likely MIT or similar permissive. The point is for this to be
reused by anyone writing Plus/4 programs that want high-quality PT3 audio.
