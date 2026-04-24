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

---

## Session 5 — 2026-04-24: M2 Note Table Generator

### M2 — Note Table Runtime Generator — PASS ✓ (8/8 bit-exact)

Ported Ivan Roshin's `NoteTableCreator` from Python reference (pt3_tables.py)
to CA65 assembly. Full bit-exact match against VTII-validated Python output
for all 8 combinations (4 tone tables × 2 version flags).

New public API:
```
player_build_note_table(A = tone_table_idx, X = version_is_old)
  → fills note_table at $3327 with 192 bytes (96 notes × 2 bytes LE)
```

Algorithm in 3 phases (each a separate subroutine):

1. **depack_t_pack** (depack T_PACK seed data into t1_buf):
   - Walks T_PACK_DATA bytes, distinguishing delta (>=30) from absolute (<30)
   - Writes backwards into 98-byte t1_buf, matching Z80 asm behavior
   - Terminates on low byte == $F0

2. **generate_notes** (build 96-note frequency table):
   - 12 outer iterations (one per base note) × 8 inner iterations (octaves)
   - 16-bit right-shift per octave using lsr/ror pair
   - Conditional rounding-via-carry based on truncate flag (NT_SELECTOR bit 0)

3. **apply_corrections** (per-note fixups):
   - Walks nul-terminated correction list pointed to by NT_SELECTOR
   - Each byte: LSB = sign (1=decrement), upper bits = word index
   - Also handles TCNEW_3 → TCOLD_3 chain (no terminator in TCNEW_3)
   - Special case: if table=1, force note_table[46] = $FD

Test results (py65 harness):
```
table=0 NEW: 5548 steps, PASS
table=0 OLD: 5660 steps, PASS
table=1 NEW: 5502 steps, PASS
table=1 OLD: 5502 steps, PASS
table=2 NEW: 5564 steps, PASS
table=2 OLD: 5649 steps, PASS
table=3 NEW: 5532 steps, PASS
table=3 OLD: 5516 steps, PASS
```

Note: ~5500 steps per invocation is the one-time init cost per loaded PT3
file. Not in the critical path (IRQ handler).

Code size after M2:
- player.bin: 674 of 4096 bytes (16.5% budget used)
- Remaining: 3422 bytes for M3-M11

Bug found during development:
- `(abs_label),y` indirect addressing doesn't exist on 6502 — only `(zp),y`
- Workaround: copy BSS pointer (nt_corr_ptr) to ZP_TEMP before use
- Pattern will recur in pattern decoder (3 per-channel stream pointers)

Deterministic build confirmed: same source produces identical binary on
Claude's sandbox (ca65 2.19) and Kris's server (ca65 2.18).

### M2 real-world test pending

Kris will YAPE-test `build/m2_test.prg`:
- Boots, calls player_init, then player_build_note_table(1, 0)
- Copies note_table[47*2..95] ($00FC) to shadow R0/R1
- Hooks raster IRQ, idle loops
- Expected: sustained tone at ~440 Hz (musically A-4 at 1.77 MHz AY clock)
- Distinguishable from M1's ~433 Hz (hardcoded $0100) by slightly higher pitch

### Next: M3 — Volume Table Generator

Port `build_volume_table(pt_version)` from `pt3_tables.py`. Similar structure
but more complex: 16-bit accumulator arithmetic (Z80 ADD HL,DE equivalent),
conditional RLA in inner loop, IX register emulation. Expected ~500 bytes
of code, 256 bytes of output table. Same validation pattern: 2 combinations
(old/new volume table) bit-exact against Python reference.


## Session 6 — 2026-04-24: M3 + M4 + STATUS.md

### M3 — Volume Table Generator — PASS ✓ (2/2 bit-exact)

Port of `build_volume_table(pt_version)` from `pt3_tables.py`. Runtime generator
producing 256-byte table at `$35ED`. Dispatches on A on entry: `pt_version<5`
initializes HL=$0010/DE=$0010/use_rla=0 (OLD variant for PT 3.0-3.4x),
`pt_version>=5` initializes HL=$0011/DE=$0000/use_rla=1 (NEW variant for PT 3.5+).

Implements Z80's nested 16×16 loop emulating ADD HL,DE / SBC HL,HL / EX DE,HL
on 6502 with explicit carry propagation through BSS state (`vt_carry`). Inner
loop does optional RLA (rotate-left-through-carry on A, capturing old bit 7),
then A = H + carry, writes to table, advances HL += DE. Outer loop swaps HL↔DE,
bumps E if E==$77 (quirk of original asm).

OLD variant: 7822 py65 steps. NEW variant: 10330 steps. Both match Python
reference byte-for-byte.

Code size after M3: 962 bytes (+288 from M2). player.bin md5:
`ab37dcb641957e4a321aaf68ffca5817`.

Two bugs during development:
- **Long BNE out of range**: `BNE @outer` from `@skip_einc` was >128 bytes away.
  Fixed with `BEQ @done / JMP @outer` idiom. 6502 branch limit bit us.
- **L/E swap inverted**: in the Z80 EX DE,HL emulation, the L↔E swap block
  had STA/STX targets reversed, writing originals back to their own slots
  instead of swapping. H↔D was correct, so symptom was "inner loop produces
  all zeros because DE stays at its pre-swap value". Subtle — only one of
  two swap pairs broken.

### M4 — PT3 Header Parser — PASS ✓ (3/3 files)

`player_load_pt3(A=base_hi, X=base_lo)` at `$3003` (replaces M1 stub).
Parses PT3 header into 17-byte BSS struct with absolute pointers.

Sanity-checks first 3 bytes for "Pro" or "Vor" (sets `pt3_parse_error=1`
on mismatch). Extracts:
- `version_char` from offset `$0D` and derives `features_level` (0/1/2)
  per VTII `trfuncs.pas` rules
- `tone_table`, `delay`, `num_positions`, `loop_position` from `$63-$66`
- `patterns_ptr` = base + file[$67:$69]
- `sample_table` = base + $69 (start of 32 sample pointers)
- `ornament_table` = base + $A9 (start of 16 ornament pointers)
- `position_list` = base + $C9 (`num_positions` bytes)

All three reference files pass all 12 field checks on first try — no debug
cycle needed. Steps: yerzmyey.pt3 77, luchibobra.pt3 75, blobbzgame.pt3 74.

Code size after M4: 1181 bytes (+219 from M3, 28.8% of 4096). player.bin md5:
`ad5ccbafec9b0fd7a1e0a9e2db2f7675`.

PT3 format correction confirmed vs earlier docs/memory:
- **Position list has NO `$FF` terminator.** `num_positions` at offset `$65`
  is authoritative. Verified against all 3 files.
- **Position list bytes are `pattern_num × 3`** (0, 3, 6, ...), not raw
  pattern numbers. Consumer divides by 3 (or uses byte directly as
  offset into 3-byte-per-pattern indexing — deferred to M5).
- **Patterns table is array of 6-byte entries**, confirmed by Deater's spec
  cited by Kris. Each entry = 3 × 2-byte LE stream pointers (A, B, C).
  M5 consumes this.

### Workflow improvements this session

- **Branch-first development**: `feature/m4-header-parser` created before work,
  merged with `--no-ff` to preserve topology, then deleted (local+remote).
  Rollback safety: merge commit preserves full branch history.
- **Patch transport instead of full file**: M4 moved 11 KB of diff vs 33 KB
  of full file. `diff -u --label a/... --label b/...` + `patch -p1 --fuzz=3`.
  Fuzzy patch saved the day when trailing-newline context drifted.

### docs/STATUS.md — new living document

Complement to frozen ARCHITECTURE.md. Captures real state after each milestone:
sizes from git archaeology, full memory map from `.sym`, BSS inventory, jump
table status, learnings, open questions. Updated after each milestone rather
than rewritten.

### Next: M5 — Pattern Opcode Decoder

Per-channel stream decoder for pattern data. Single-channel initially, no
state advancement — "given stream pointer, return next decoded row". Design
questions listed in STATUS.md open questions section. Budget: ~400-500 bytes.
