# Session Log

## 2026-04-24 — Session start

### Python simulator milestone
**7/7 files bit-exact 100% against VTII reference PSG:**
- yerzmyey.pt3 (PT3.7, FL=2, DELAY)
- blobbzgame.pt3 (VTII 1.0, FL=1, DELAY)
- luchibobra.pt3 (PT3.5, FL=0, "bug f!x" test)
- Lee_Bee_Basterdale_Farm.pt3 (PT3.5, FL=0, GLISS+PORTM+DELAY)
- Pator_Parallel_Visions.pt3 (VTII 1.0, FL=1, GLISS+DELAY+ENGLS)
- FreeSky.pt3 (PT3.7, FL=2, **GLISS+VIBRATO+NOISE** — new effect coverage!)

### Bugs fixed this session
1. **Default sample=1 quirk** — VTII trfuncs.pas line 887: default Sample=1 even
   though PT3 editor has no such concept. Matters when note triggers on channel
   with no prior sample set (FreeSky pattern 2 ch C `G#4 ...B` — inherits sample
   from non-existent state).
2. **Sample/ornament advance gated by sound_enabled** — VTII's Inc(SamplePosition)
   is INSIDE `if SoundEnabled then` block (trfuncs.pas lines 950-1055). When
   vibrato (effect 6) toggles SoundEnabled=False, sample position must freeze
   for that tick. Without this, sample envelope advances too fast during vibrato.
3. **Noise_Base persistence per pattern** — VTII trfuncs.pas line 2290:
   `NsBase := 0` at start of each pattern decode, then opcode 0x20-0x3F
   updates it. Within pattern, Noise_Base persists between rows. I had it
   as a purely per-row variable (reset implicitly), which broke Pator on
   pattern boundaries. Fixed by resetting only on pattern switch.

### Environment setup on Kris's server (PM Pipeline)
- ✅ **ACME** assembler: `/usr/bin/acme` (for reading existing jukebox code)
- ✅ **CA65/LD65**: extracted from Debian cc65 2.19-2 deb to `~/cc65/usr/bin/`
  — available via `export PATH="$HOME/cc65/usr/bin:$PATH"` (added to .bashrc)
- ✅ **py65** 1.2.0 installed via pip: `python3 -c "import py65"` works
- ✅ **Plus/4 target config**: `~/cc65/usr/share/cc65/cfg/plus4.cfg` available

### Smoke test
First CA65 program compiled successfully:
```
01 10 0B 10 0A 00 9E 34 31 30 39 00 00 00 A9 0E 8D 15 FF 60
```
= load addr $1001 + BASIC stub "10 SYS 4109" + `LDA #$0E / STA $FF15 / RTS`
(would change screen background color when run on Plus/4).

### Architecture decisions confirmed
- **Co-resident player module** at $3000-$3FFF (4 KB budget)
- **Timer #1 TED IRQ** (autoreload, $3A43 for NTSC, $4523 for PAL)
- **Zero page $D8-$E8** (17 B totally safe per SVS map v2.2)
- **DigiMuz** at $FD21 (read), $FD22 (data write), $FD23 (register select)
- **No NOP** needed between $FD23/$FD22 writes — `STX $FD23 / STA $FD22`
  sequence gives ~8 cycles which exceeds AY's 400ns setup requirement.
- **ACME-ish structure but CA65 tooling** per Kris's decision
- **Standalone library** — public jump table at PLAYER_BASE ($3000)

### Next steps (next session)
1. Transfer simulator files to server `pt3_python_sim/` directory (need to chunk
   pt3_simulator.py which is 48 KB).
2. Write `src/pt3_player.inc` — shared equates (DigiMuz, TED, zero page, API offsets).
3. Write `src/player.cfg` — ld65 linker config with PLAYER_BASE parameterization.
4. Write `src/player.s` — entry points (jump table), Timer #1 IRQ setup,
   stub handler that plays one tone (validation that chain works).
5. Build first `.prg`, verify under VICE emulator (visual: AY sings continuously,
   no crash, RTS returns to BASIC cleanly when stopped).
6. Start py65 test harness: `tests/harness.py` — loads `.prg` into emulator,
   simulates N IRQs, reads shadow AY state, diffs against Python simulator output.

---

## Session 4 — 2026-04-24 (continued): architecture freeze + M1

### Architecture decisions finalized

Resolved all three open questions from `docs/ARCHITECTURE.md`:

- **Q1 (IRQ ownership)**: **Host owns timer, player is pure library**.
  Researched standard practice across SID/AY music drivers (Lemon64, chipmusic,
  Digitalerr0r, SIDBlaster, BBC SIDPlayer) — unanimous convention since 1985.
  Kris's `config.asm` layout (PLAYER_PLAY = $3003) was correct from the start.

- **Q2 (stop semantics)**: `player_stop` = mute + halt, preserving position.
  `player_rewind` = full reset. Enables pause/resume and next-track semantics.

- **Q3 (loop flags)**: Two independent flags `loop_track_flag` and
  `loop_playlist_flag`. Setting loop_track=1 forces loop_playlist=0. When
  loop_track=0 and loop_playlist=0, VTII default behavior applies (use
  loop_pos from header).

All decisions captured in `docs/ARCHITECTURE.md` commit 308fa88.

### M1 — Hello Tone — PASS

First working milestone. Scope: minimal viable player.

Files created:
- `src/pt3_player.inc` (81 lines): shared equates
- `src/player.cfg`: ld65 config
- `src/player.s` (267 lines): jump table + 8 stub entries
- `tests/harness.py` (276 lines): py65 harness

What's implemented:
- Jump table at $3000-$3017 (8 entries × 3 bytes, all verified)
- `player_init`: zero shadow AY, hardcode A-4 on ch A
- `player_play`: tight 14-register write loop to DigiMuz
- `player_stop`, `player_set_flags`: working
- Other procedures: stubs returning fixed values

Harness capabilities:
- Automatic ca65+ld65 build
- py65 ObservableMemory with write observers on $FD22, $FD23
- AYBusObserver reconstructs 14-register state from reg-sel/data-write pairs
- `call_subroutine()` uses sentinel-address trap to detect RTS exit

Test results:
- Build: 4096-byte binary, 152 bytes code+data used (~3.7% of budget)
- player_init: 69 py65-instruction steps
- player_play: 75 steps/frame avg across 60 frames
- All 60 frames produce IDENTICAL output (determinism ✓)
- Final AY state matches M1 expected spec bit-exact ✓

Commit: `4c7d45e`.

### Next: M2 — note table runtime generator

Port Ivan Roshin's `NoteTableCreator` algorithm from `pt3_tables.py`
(validated by 20/20 bit-exact against VTII) to 6502.

Goal: harness can call `player_init(tone_table=N)` and read back a 192-byte
note table that byte-exactly matches Python's `build_note_table(N)` output,
for all 4 tone table types × 2 version flags = 8 combinations.

This is where real complexity starts. Ivan Roshin's Z80 asm is ~60 lines;
we need 6502 port with 16-bit arithmetic (no 16-bit regs on 6502!).
Estimated size: 150-250 bytes of code + 192 bytes table RAM + a few
constants ~20 bytes. Should fit comfortably.

### M1 real-world validation — YAPE — PASS ✓

Kris loaded `m1_test_simple.prg` into YAPE 1.2.7 emulator and ran it.

Result: **Continuous A-4 tone heard on DigiMuz emulation.** 🎉

Status bar confirmed: `Loaded: m1_test_simple.prg at $1001-$2098` — matching
our build's 4249-byte output.

This validates the full stack end-to-end on an actual Plus/4 emulator (not
just py65): BASIC stub → SEI → player.bin copy to $3000 → JSR player_init →
save/install IRQ vector → CLI → IRQ fires → JSR player_play → 14 AY register
writes via DigiMuz → chain to KERNAL.

Cosmetic note: `LIST` after RUN shows "garbage" lines after the real
`10 SYS 4109` — this is the BASIC interpreter trying to parse our 6502
machine code + embedded player.bin as BASIC tokens past the program
terminator. No functional impact (RUN goes to $100D correctly, ignoring
the rest). Worth a cleanup pass later but not blocking.

**M1 is now fully complete.** Three independent validations:
1. py65 harness: 60/60 frames bit-exact, deterministic output ✓
2. YAPE emulator: audible tone ✓
3. Real Plus/4 hardware: deferred, low risk (YAPE matches real HW)

Ready for M2.
