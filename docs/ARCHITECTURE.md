# PT3 Player for Plus/4 — Architecture

This document captures the design thinking BEFORE writing any 6502 code.
Read this first. When implementation details surprise you, come back here to
check whether we planned for them.

---

## Design goal

A 4 KB co-resident PT3 playback module at $3000-$3FFF that **matches the Python
simulator bit-exactly** on all 20 test files, driven by Timer 1 IRQ, producing
output to DigiMuz at $FD21/$FD22/$FD23.

Bit-exact means: for a given PT3 file, if we set up py65 to simulate N IRQ calls
and capture AY register writes, the resulting PSG byte stream equals what the
Python `pt3_simulator.py` produces for the same N frames.

---

## Critical constraint: testing on Linux has NO emulator with DigiMuz support

**VICE does not emulate DigiMuz.** The only Plus/4 emulator that does (YAPE) has
**no Linux build**. This means we **cannot** do the traditional workflow of
"compile → run in emulator → listen".

**Consequence**: `py65` (6502 simulator in Python) is the primary validation loop,
and it's responsibility is **measuring AY register writes directly**, not playing
audio. This shapes the architecture in two ways:

1. **Every AY write must be observable by py65 as a load/store event at $FD21-$FD23.**
   py65 supports memory-mapped I/O callbacks — the harness registers handlers
   that capture `STA $FD23` (reg select) + `STA $FD22` (data write) pairs and
   records them as "AY register N = value V at frame F".
2. **Frame boundaries must be explicit.** Since py65 doesn't emulate TED timer,
   the harness doesn't rely on timer IRQ firing naturally. Instead, harness
   drives execution: "run CPU until JMP (irqvec) or RTI, then manually trigger
   next IRQ by calling playback_tick entry point directly".

The harness reference architecture:
```
  python harness.py test_files/yerzmyey.pt3
    → assembles player.s with ca65 + ld65
    → creates py65 CPU + RAM + memory map
    → loads .prg at $1001, loads PT3 at $4000
    → calls player_init (JSR $3000), player_load_pt3 (JSR $3003 with PT3 addr)
    → loop N times:
        * capture AY state (shadow) BEFORE the tick
        * call playback_tick (JSR $3006 or direct subroutine address)
        * capture AY register writes that occurred during tick
        * build frame state = previous frame + writes
    → compare resulting PSG stream against pt3_simulator.py reference
    → report diff
```

Crucially, **only when we have bit-exact match on py65** do we flash to a real
Plus/4 + DigiMuz for "does it actually sound right" validation. Real hardware is
the final check, but py65 is where 99% of debugging happens.

---

## IRQ handler and timing budget

**Plus/4 NTSC CPU clock**: 894841 Hz. **NTSC frame rate**: 60 Hz.
**Cycles per frame available**: 14914.

**Budget allocation** (informal, tweak after measurement):
- Jukebox UI and OS housekeeping: ~7000 cycles (half of frame budget)
- PT3 player IRQ handler: **~7000 cycles ceiling** per frame

Typical tick breakdown (estimate):
- Save/restore regs, IRQ ack: ~60 cycles
- Row boundary? If yes, decode (worst case across 3 channels + effect dispatch):
  ~2000-3000 cycles  (amortized: only every N ticks, where N = speed = 3..7)
- Per-tick per-channel work (×3): ~1500 cycles total
- Envelope slide tick (module-level): ~40 cycles
- Write 14 shadow AY registers via DigiMuz: ~200 cycles

**Worst case IRQ** (row boundary with fresh notes on all 3 channels + all effects
in play): probably ~4500 cycles. **Comfortable**.

**Typical IRQ** (mid-row, no decode needed): probably ~1500-2000 cycles.
**Very comfortable**.

If we blow the budget, contingency plan: split expensive operations across
multiple IRQs. E.g. decode row 0 of next pattern during last tick of previous
pattern, not on the row boundary itself. This amortizes cost but adds complexity.
**Defer this optimization until we measure a real problem.**

---

## Timer 1 setup

Timer 1 is a 16-bit countdown timer with autoreload. Write to $FF00/$FF01
loads BOTH the counter AND the reload register simultaneously. When counter
reaches 0, it generates IRQ (if enabled in $FF0A bit 5) and reloads from the
reload register.

**Autoreload values**:
- NTSC 60 Hz: clock / 60 = 894841 / 60 = 14914 = **$3A42** (write $42 to $FF00, $3A to $FF01)
- PAL 50 Hz:  clock / 50 = 886724 / 50 = 17734 = **$4546** (write $46 to $FF00, $45 to $FF01)

**PAL/NTSC autodetect**: read TED register $FF07 bit 6 (PAL=1, NTSC=0), pick
reload value accordingly. Or: user passes this as a player_init() parameter,
letting the host program decide.

**IRQ enable**: $FF0A bit 5 = 1
**IRQ acknowledge**: write to $FF09 with bit 4 set (clears Timer 1 pending flag)
**IRQ vector**: $FFFE/$FFFF on 6502; on Plus/4 with KERNAL, this points into
ROM which dispatches to $0314/$0315 (IRQ vector in RAM). We overwrite
$0314/$0315 to our handler, chain-call original if needed.

**Critical**: timer IRQ must NEVER take longer than the reload period, or
IRQs start stacking up and the whole system hangs. The 7000-cycle ceiling
guarantees safety.

---

## AY interface via DigiMuz

**Ports**:
- $FD21: AY data read (rarely used — we write-only)
- $FD22: AY data write
- $FD23: AY register select (latches which register gets written next)

**Register write sequence**:
```
  LDX #reg_num       ; 2 cycles
  STX $FD23          ; 4 cycles  (latch register select)
  LDA value          ; 2 cycles
  STA $FD22          ; 4 cycles  (write data)
                     ; TOTAL: 12 cycles between STX and STA
```

AY-3-8910 requires ~400ns setup between register select and data write. On 7501
@ 894 kHz, 12 cycles = ~13.4 µs = **MUCH more than required**. No NOPs needed.

**14-register write loop** (ay_write_all_shadow):
```
  ldx #13
@loop:
  stx $fd23
  lda shadow_ay,x
  sta $fd22
  dex
  bpl @loop
  ; total: 14 iterations × ~14 cycles = ~200 cycles
```

We write registers 13 down to 0 because R13 write triggers envelope restart on
the AY chip. By writing R13 LAST we ensure the envelope doesn't restart
mid-frame. But: **we only write R13 if env_shape changed this frame** — this is
one of the 14 design notes from the Python simulator (R13 write only on SETENV).

Implementation: shadow_ay[13] holds "what we want R13 to be". A separate flag
`r13_needs_write` is set by the pattern decoder when SETENV is seen in the current
row. The write loop skips R13 unless flag is set, then clears flag after writing.

---

## Memory layout

```
$0000-$00FF   Zero page
              $D8-$E8 used by player (17 bytes safe per SVS map v2.2)
              ZP allocation:
                $D8/$D9  = pattern stream ptr ch A (2B)
                $DA/$DB  = pattern stream ptr ch B (2B)
                $DC/$DD  = pattern stream ptr ch C (2B)
                $DE/$DF  = sample data base ptr (2B, set on load)
                $E0/$E1  = ornament data base ptr (2B, set on load)
                $E2/$E3  = temp/scratch for current tick (2B)
                $E4/$E5  = temp/scratch (2B)
                $E6      = reserved for 16-bit add carry temp
                $E7      = reserved
                $E8      = reserved

$0100-$01FF   Stack (OS-managed)
$0200-$0FFF   OS-reserved (KERNAL zero-init area etc)
$1000-$2FFF   Jukebox host program (UI, file loading, display)
$3000-$3FFF   PT3 Player module (this library) — 4 KB
              $3000-$3017  Public jump table (8 entries × 3B)
              $3018-       Code
              (end of segment)  RAM state (shadow AY, channel state, tables)

$4000-$7FFF   PT3 song data buffer (16 KB max)
$8000-$FCFF   Free for expansion / other data
$FD00-$FDFF   I/O area (DigiMuz at FD21-FD23, other expansion)
$FE00-$FEFF   I/O area (continued)
$FF00-$FFFF   TED registers
```

---

## Player memory map (inside $3000-$3FFF)

```
$3000-$3017   Public jump table (8 × 3-byte JMP entries)
              $3000  JMP player_init
              $3003  JMP player_load_pt3
              $3006  JMP player_play
              $3009  JMP player_stop
              $300C  JMP player_pause
              $300F  JMP player_is_playing
              $3012  JMP player_is_song_ended
              $3015  JMP player_get_position

$3018-$3???  Code (~2200 bytes estimated)

$3???-$3???  Read-only data (shadow AY default, opcode jump tables for decode,
             some constants; ~300 bytes estimated)

$3???-$3FDF  RAM state (zeroed by player_init):
             shadow_ay[14]           AY register shadow; written to hardware
                                     at end of every tick. 14 bytes.
             r13_needs_write         1 byte flag — write R13 this tick?
             
             (Per-channel, struct-of-arrays layout; each array is 3 bytes,
             indexed X=0 (ch A), X=1 (ch B), X=2 (ch C))
             
             note_num[3]              current note 0..95, or $FF = released
             prev_note[3]             for portamento (VTII: PrNote)
             sample_num[3]            1..31
             ornament_num[3]          0..15
             pos_in_sample[3]         tick index into sample
             pos_in_ornament[3]       tick index into ornament
             volume[3]                channel master volume 0..15
             flags[3]                 bit 0: sound_enabled
                                      bit 1: note_released
                                      bit 2: envelope_enabled
                                      bit 3..7: reserved
             
             (2-byte fields, each is 2 arrays of 3 bytes: lo,lo,lo then hi,hi,hi
             for easy X-indexed access)
             current_ton_sliding_lo[3], _hi[3]    6 bytes
             saved_ton_sliding_lo[3], _hi[3]      6 bytes (for PORTM FL>=1)
             ton_slide_step_lo[3], _hi[3]         6 bytes (signed 16-bit)
             ton_slide_delta_lo[3], _hi[3]        6 bytes
             ton_accumulator_lo[3], _hi[3]        6 bytes
             
             (1-byte per channel)
             ton_slide_count[3]
             ton_slide_delay[3]
             ton_slide_type[3]        0=gliss, 1=portamento
             slide_to_note[3]
             current_onoff[3]
             onoff_delay[3]
             offon_delay[3]
             amp_slide_accum[3]       signed
             current_noise_sliding[3]
             current_envelope_sliding[3]
             
             (Module-global state)
             current_position        byte — index into position list
             current_pattern         byte — pattern number playing now
             current_line            byte — row index in pattern
             pattern_length          byte — computed for current pattern
             speed                   byte — ticks per row (initial_delay from header)
             delay_counter           byte — countdown of ticks until next row
             noise_period            byte — last NOISE opcode value (per-pattern)
             env_period_lo,hi        2 bytes — EnvP_Base
             env_shape               byte — R13 value (shapes 0..F)
             cur_env_slide_lo,hi     2 bytes — ENGLS effect state
             cur_env_delay           byte
             env_delay               byte
             env_slide_add_lo,hi     2 bytes — signed
             sam_env_p_signed        byte — frame-local, recomputed each tick
             
             (Tables built by player_init, ~400 bytes total)
             note_table[192]         96 notes × 2 bytes LE
             volume_table[256]       (ch_vol << 4 | sam_vol) → combined amp
             
             Total state estimate: ~200 bytes data + ~400 bytes tables = ~600 bytes.
             Leaves ~1000-1500 bytes for code growth.

$3FE0-$3FFF   Reserved tail / IRQ chain vector save
```

---

## Decision: struct-of-arrays for per-channel state

Consider implementation of "copy note to current_note for channel X":

**Array-of-structs** (C-style):
```
  ; channel struct is ~30 bytes. Ch A at base+0, Ch B at base+30, Ch C at base+60.
  ; To set ch X's note:
  lda #new_note
  ldy channel_offset,x  ; lookup table: 0, 30, 60
  sty tmp
  sta channel_base+NOTE_OFFSET  ; nope, can't do variable-offset easily
  ; have to compute: base_lo + channel_offset + note_offset, store through (zp),y
  ; ~20 cycles
```

**Struct-of-arrays**:
```
  ; All note values in one 3-byte array: note_num[0..2]
  lda #new_note
  sta note_num,x        ; X = channel index 0/1/2
  ; ~8 cycles
```

**2-3× faster**, simpler code, no indirect addressing needed. Only downside:
"loops that process one channel's full state" (e.g. "clear all state for
released channel") are less nicely contiguous. In practice we rarely need that —
most operations are per-field across channels or per-channel-one-field.

---

## Decision: shadow AY + write-at-end

Alternative: write to hardware as state changes during frame (4 cycles STA $FD23
+ 4 cycles STA $FD22 = 8 cycles per write, per-field). With ~14 register writes
per frame this is ~200 cycles either way.

**But** shadow AY has three wins:

1. **Silent stop is free**: `player_stop` just zeros shadow_ay and sets R7 to
   mute-all, then one write loop. No special logic.
2. **Skip unchanged registers** (future optimization): compare shadow to
   previously-written state, only hit AY for changed. Small PT3 files with sparse
   effects could drop to ~5 writes per frame.
3. **R13 conditional write**: easy to gate behind r13_needs_write flag without
   restructuring.

---

## Implementation milestones

Incremental, each milestone testable in py65 harness before moving on.

### M1 — Hello Tone
Timer IRQ setup + 14-register write loop + hardcoded "always play A-4 on ch A".
~50-80 lines of assembly.

Test: `python3 harness.py --test-hello` runs 60 IRQs, verifies:
- AY R0=$FC, R1=$00 (or whatever A-4 is in tone table 1)
- R8=$0F (ch A vol)
- R7=$3E (ch A tone enabled, B and C disabled)
- Stable across all 60 frames

### M2 — Note table runtime generator
Port Ivan Roshin's `NoteTableCreator` from `pt3_tables.py` to 6502. Generates
note_table[0..95] for a given tone_table_idx (0..3) and version_is_old (0/1).

Test: harness calls player_init(tone_table=1) then reads note_table[45]
(A-4 in ST table), compares byte-by-byte with Python's `build_note_table(1, 0)`.
Repeat for all 4 tone tables × 2 version flags = 8 combinations.

### M3 — Volume table runtime generator
Port `VolTableCreator`. Test identical to M2 but for volume_table[0..255].

### M4 — PT3 header parser
Parse the 0x69-0xC9 header into state (tone_table_idx, speed, num_pos, loop_pos,
pat_ptr, sample_ptrs, ornament_ptrs, pattern_numbers from position list).

Test: harness loads yerzmyey.pt3 into RAM at $4000, calls player_load_pt3($4000),
verifies parsed state matches Python `PT3Module(yerzmyey.pt3)`.

### M5 — Pattern opcode decoder (single channel, no playback)
Implement `decode_channel_row` for a single stream — reads bytes from pattern
stream, decodes into a RowState struct. No state advancement, just "given
stream ptr, produce next row".

Test: harness calls decode_channel_row repeatedly on ch A of luchibobra.pt3,
compares each decoded RowState against Python's `decode_next_row()` output.

### M6 — Simple playback: notes only, no sample, no ornament, no effects
Full IRQ loop: decode_next_row on boundary, compute tone from note_table,
write R0-R5 to shadow_ay. Amp always full (vol=15, no sample envelope). No
ornament. No effects.

Test: synthetic test PT3 file with simple scale. Verify R0-R5 per frame match
expected values. Should hear "scale" on real hardware (though dry).

### M7 — Sample playback
Add sample pointer resolution, sample tick decoding (4-byte ticks), amplitude
from sample, tone offset from sample, mixer bits, amp slide accumulator,
accumulator advance flags.

Test: luchibobra.pt3 — simplest "real" PT3 file in our corpus. After M7,
R0-R10 should match Python sim for entire song.

### M8 — Ornaments
Add ornament pointer resolution, ornament position tracking, offset application,
reset rules (note trigger, ornament change without note — design note #9).

Test: luchibobra.pt3 uses ornaments. Full R0-R13 match expected after M8.

### M9 — Effects one at a time
Order (easiest → hardest):
- M9a: DELAY ($09) — just changes speed var
- M9b: SMPOS ($03), ORPOS ($04) — set pos_in_sample / pos_in_ornament
- M9c: GLISS ($01) — ton_slide_step per tick, no target detection
- M9d: PORTM ($02) — like GLISS but with target note + saved_ton_sliding FL>=1
- M9e: VIBRT ($05) — sound_enabled toggle
- M9f: ENGLS ($08) — envelope slide

Test: one PT3 file per effect from our test corpus:
- GLISS: ABCSOFT MONTANA
- PORTM: LaesQ Rumple-fyke
- VIBRT: FreeSky
- ENGLS: Pator She Stole
- DELAY: EA xiaomi ringtone (stress test: 1279 DELAYs)

### M10 — Edge cases from 14 design notes
Walk through `pt3_python_sim/README.md` design notes, verify each:
- #2: volume_table uses "new" (M3 already)
- #3: opcode $10 = envelope OFF, no env_period (M4/M5)
- #4: envelope period BE (M5)
- #5: envelope shape = opcode - $B1 for $B2-$BF (M5)
- #6: default sample=1 (M4 init)
- #7: sample/ornament advance gated by sound_enabled (M7/M8)
- #8: noise_period per-pattern persistence (M6)
- #9: ornament position reset without note (M8)
- #10: SamEnvP signed (M9f)
- #11: saved_ton_sliding for PORTM FL>=1 (M9d)
- #12: T_PACK reversed in NoteTableCreator (M2)
- #13: SETENV resets cur_env_slide/cur_env_delay (M9f)
- #14: variable pattern length (M4)

### M11 — Full regression against 20 test files
Run `run_all_tests.sh`-equivalent (harness batch mode): for each of 20 .pt3 files,
run player through N frames, compare resulting PSG against test_files/*.psg
reference, report 100% or diff.

**Exit criterion**: 20/20 bit-exact. Then we flash to real Plus/4 + DigiMuz,
listen with Kris, confirm it sounds right, open Kindzmarauli. 🍷

---

## py65 harness design

Separate file: `tests/harness.py`. Main responsibilities:

1. **Assemble player**: shell out to `ca65 src/player.s -o build/player.o`
   and `ld65 -C src/player.cfg build/player.o -o build/player.prg`.
2. **Load into py65 memory**: py65's `mpu.memory` is a byte array; write .prg
   bytes (skipping 2-byte load address header) into memory starting at $1001.
3. **Memory-map callbacks for AY**: py65 supports "observer" patterns — register
   a write observer on $FD22 and $FD23 addresses. Observer signature:
   `def on_ay_write(addr, value):` — we accumulate a list of (reg, val) pairs
   between "frame markers".
4. **Drive IRQs**: since no TED timer is simulated, after N instructions or
   after detecting "RTI from IRQ handler", call player's playback_tick entry
   point directly (JSR to tick routine, not via IRQ vector). Each call = one
   frame. Capture AY writes during the call.
5. **Build PSG frames**: at end of each tick, construct 14-register frame state
   (previous frame + changes this tick). Compare against reference.

**Harness CLI**:
```
python3 tests/harness.py                    # full regression
python3 tests/harness.py yerzmyey.pt3       # one file
python3 tests/harness.py --frames 100 ...   # limit for fast iteration
python3 tests/harness.py --verbose          # dump all AY writes
python3 tests/harness.py --diff             # stop at first mismatch, show context
```

**Integration with Python simulator**: harness imports `pt3_simulator.py` from
the `pt3_python_sim/` package (sibling directory). So harness.py is:
```
  refs = pt3_simulator.simulate(PT3Module(pt3_path), max_frames=N)
  ours = run_player_on_py65(pt3_path, frames=N)
  diff_and_report(refs, ours)
```

---

## Risks and open questions

1. **py65 speed**: Python-based 6502 simulator. Running N=10000 frames × ~2000
   cycles per frame = 20 million simulated cycles. Py65 does maybe 500k simulated
   cycles/sec on a fast machine → **40 seconds per file** in worst case. Full
   20-file regression: **13 minutes**. Acceptable but slow. Potential fix: write
   a faster simulator in C, or cross-compile py65 with PyPy. **Defer until
   demonstrated problem**.

2. **IRQ chain in py65**: Plus/4's KERNAL does IRQ bookkeeping in ROM. We're
   not emulating KERNAL in py65. Our harness drives playback_tick directly,
   which works for testing but means we don't validate the TED timer setup +
   IRQ vector install logic in py65. **Only real hardware validates that.**
   Mitigation: keep TED/IRQ code minimal and isolated in `irq_setup.s`, test
   manually on real Plus/4 when M1 milestone is reached.

3. **DigiMuz timing on real hardware**: datasheet says ~400ns setup. At 894 kHz
   7501, cycles are ~1.12 µs each, so 12 cycles between STX $FD23 / STA $FD22 is
   13.4 µs. Vastly safe. **No concerns.**

4. **Jukebox UI interaction**: main.asm's IRQ path calls `JSR PLAYER_PLAY` on
   each tick (per config.asm). So our player_play entry point IS the tick
   handler, no separate IRQ hook. Need to confirm with Kris's main.asm behavior
   that this expectation holds. If main.asm does its own timer setup and just
   calls us, we don't need to manage the timer — simplification.

5. **PT3 file size**: test corpus ranges 839 B (blobbzgame) to 12 KB (CatMan).
   Buffer at $4000-$7FFF = 16 KB is enough. If a user tries to load a 24 KB
   PT3 (unusual but not impossible), we need to either reject it or extend the
   player memory map. **Current plan: player_load_pt3 returns error code if file
   exceeds 16 KB.**

6. **Init table generation time**: NoteTableCreator + VolTableCreator are
   ~100-line asm each, executed once at player_init. Speed doesn't matter —
   can be 50 ms of CPU, user will wait. But code size matters: if these total
   ~800 bytes of code, that's 20% of our 4 KB budget. **Worth measuring
   precisely at M2/M3 and considering pre-computed tables as alternative if
   code size becomes a problem.**

---

## Open questions to resolve before implementation

1. **Does Kris's existing main.asm/jukebox want to own the Timer 1 IRQ and
   call PLAYER_PLAY on each tick, or should the player own Timer 1 itself?**
   Per config.asm:
   ```
   PLAYER_PLAY     = $3003         ; JSR here each frame (IRQ)
   ```
   This suggests: host program owns IRQ, calls player_play via JSR. If true,
   our player_play IS the tick handler and we don't touch TED timer at all.
   Host program responsibility to fire IRQ at 50/60 Hz.

2. **What does player_stop need to do?** Just mute (zero shadow AY, R7=$FF)?
   Or also reset position to 0? Leaning toward: mute + clear playing flag,
   leave position intact so player_play resumes. Separate "player_rewind"
   for full reset. But this is minor — can decide at M1.

3. **Loop handling when song reaches end**: PT3 header has loop_pos. When we
   reach position == num_pos, we jump to position = loop_pos and continue.
   VTII does this automatically. Simple. But: do we want API for "stop
   playing after last position, don't loop"? Yes — jukebox wants "next
   track" trigger, not infinite loop. player_is_song_ended() returns
   true when we'd wrap to loop_pos; jukebox can stop or let us loop
   by not checking.

---

*Last updated: 2026-04-24, before writing a single line of 6502 code.
Re-read this document whenever implementation is surprising you.*
