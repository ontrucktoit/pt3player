# PT3 Player — Project Status

**Last updated:** 2026-04-25 (after PR #6 — pt3player.prg standalone)
**Current milestone:** M6 complete — full playback engine shipping
**Binary footprint:** 8192 / 8192 bytes (player.bin filled to 8 KB; engine code ends at \$47D2, then BSS)
**Regression:** 7/7 corpus files bit-exact PASS (M2/M3/M4/M5a/M5b/M6 all green)
**Deterministic build:** `player.bin` md5 = `dac3c056f6773678743e3c2b12dc9bf2`
**Public artifacts:** `pt3player.prg` (16 KB, md5 `9fdca8d6e20ce746f1642b48b6e222b3`) + 7 bundled `*_play.prg`

This document is the living snapshot of where we are. The original design intent
lives in [ARCHITECTURE.md](ARCHITECTURE.md) — that one is frozen as-planned and
does not get rewritten. This one is updated at the end of each milestone with
real measurements and any design adjustments.

---

## Milestone table

| ID  | Name                          | Status | Tests  | Size after | Delta | md5 of player.bin                      |
|-----|-------------------------------|--------|--------|-----------:|------:|----------------------------------------|
| M1  | Hello Tone (IRQ + AY write)   | DONE   | 1/1    |     152 B  |  +152 | (pre-tag)                              |
| M2  | Note Table Generator          | DONE   | 8/8    |     674 B  |  +522 | 28014f60b777708fd96646fe3b62fd22       |
| M3  | Volume Table Generator        | DONE   | 2/2    |     962 B  |  +288 | ab37dcb641957e4a321aaf68ffca5817       |
| M4  | PT3 Header Parser             | DONE   | 3/3    |    1181 B  |  +219 | ad5ccbafec9b0fd7a1e0a9e2db2f7675       |
| M5a | Pattern Opcode Decoder (1 ch) | DONE   | 3/3    |    1850 B  |  +669 | aabe39775c81802fd04e3e191d021e2a       |
| M5b | Skip + Multi-channel Driver   | DONE   | 3/3    |    2281 B  |  +431 | ab8aaba089bd69c94763139b75627dce       |
| M6  | Full playback (notes+samples+ornaments+all effects) | DONE | 7/7    | engine \$3000-\$47D2 (~6 KB) | +large | dac3c056f6773678743e3c2b12dc9bf2       |

NOTE: Original plan had M7 (samples), M8 (ornaments), M9 (effects a-f), M10 (edge cases), M11 (regression) as separate milestones. M6 absorbed all of them — bit-exact playback of the full 7-file corpus implies that samples, ornaments, and effects all work correctly.

Post-M6 work has been delivered as PRs:
- PR #1 (M6 merge): full playback engine
- PR #2: R13 envelope retrigger fix (write-only-on-change)
- PR #3: pattern-boundary IRQ overrun fix (precompute pattern lengths)
- PR #4: legal cleanup (LICENSE, attribution, third-party notices)
- PR #5: rename PT3 test files to proper attribution
- PR #6: standalone pt3player.prg + auto-detect PAL/NTSC + clean screen + naming cleanup

Total regression status: **all six core milestones PASS**.
- M1: 1/1 (hello tone)
- M2: 8/8 (note table generator, both pt_versions × 4 tone tables)
- M3: 2/2 (volume table generator, OLD + NEW variants)
- M4: 3/3 (PT3 header parser, 3 sample files)
- M5a: 3/3 (4381/4381 rows bit-exact, all 14 opcode ranges)
- M5b: 3/3 (2405/2405 ticks bit-exact, multi-channel driver)
- M6: 7/7 (full corpus, bit-exact PSG match vs VTII reference)

---

## Memory map (current, after M5b)

Player is a co-resident library at `$3000-$3FFF` (4 KB budget).

```
$3000 .. $3020   Jump table             33 B     (11 entries × 3 bytes; M5a added one)
$3021 .. ~$34A0  Code + RODATA        ~1152 B   (M1..M4 code + SPC_CMD_PARAM_TABLE,
                                                 T_PACK_DATA, NT_SELECTOR_RAW,
                                                 TCOLD/NEW_*_LIST)
$34A1 .. ~$36ED  M5a decoder code      ~589 B   (player_decode_row + consume_spec_params +
                                                 all 14 opcode-range handlers)
~$36EE .. $36FD  BSS: scratch         ~133 B    (shadow_ay + flags + nt_* + dp_* + gn_*
                                                 + t1_buf[98])
$36FE .. $37BD   BSS: note_table       192 B    (M2)
$37BE .. $37C8   BSS: vt_* state        11 B    (M3 scratch)
$37C9 .. $38C8   BSS: volume_table     256 B    (M3)
$38C9 .. $38D9   BSS: pt3_* state       17 B    (M4 parsed header)
$38DA .. $3905   BSS: row_out_ch_a/b/c  36 B    (M5a — 12 bytes per channel)
$3906 .. $390B   BSS: ch_nn_skip + ch_end_flag   6 B   (M5a per-channel state)
$390C .. $3911   BSS: dec_* scratch      6 B    (M5a decoder temporaries)
$3912 .. $3FFF   FREE                 ~1815 B   (for M6..M11 code + BSS growth)
                                                 (M5b added ~431 B code + 8 B BSS)
```

Note: offsets are approximate — the assembler may pack code and BSS slightly
differently; what matters is the binary size (1850 B) and BSS total (~657 B).

**Binary remaining**: 4096 - 2281 = **1815 bytes** for M6-M11.

**Budget for M6-M11**: 1815 bytes. M5b came in at 431 B vs estimated 150 B —
3-way channel dispatch triplet is verbose on 6502. Revised estimates:
- M6 (playback): ~300-500 B code + small BSS
- M7-M9 (samples, ornaments, effects a-f): ~800-1200 B total
- M10-M11: regression only

Optimization available if tight: M5a and M5b both have ~100-200 B each of
easy savings by replacing per-channel if-else triplets with table-driven
dispatch (3 address pairs → indirect jump). Defer until budget demands it.
- M7 (samples): ~300 B code + sample-state BSS per channel × 3
- M8 (ornaments): ~200 B code + ornament-state BSS per channel × 3
- M9 (effects a-f): ~500 B code + effect-state BSS per channel × 3
- **Projected total**: ~2000 B; comfortable headroom of ~300 B.

---

## Jump table

| Offset | Entry                     | Added | Status |
|--------|---------------------------|-------|--------|
| $3000  | player_init               | M1    | DONE |
| $3003  | player_load_pt3           | M4    | DONE |
| $3006  | player_play               | M1    | stub (writes shadow_ay to AY each call; IRQ-driven) |
| $3009  | player_stop               | M1    | DONE |
| $300C  | player_rewind             | M1    | stub (calls player_stop; full reset deferred) |
| $300F  | player_is_playing         | M1    | DONE |
| $3012  | player_is_song_ended      | M1    | stub (always returns 0; real logic in M6) |
| $3015  | player_set_flags          | M1    | DONE |
| $3018  | player_build_note_table   | M2    | DONE |
| $301B  | player_build_volume_table | M3    | DONE |

---

## BSS fields (M1-M4)

### Basic state
- `shadow_ay[14]`: mirror of AY registers, written to $FD22/$FD23 each frame
- `playing_flag`: 1 if playing, 0 if stopped
- `flags_byte`: loop flags (track / playlist)

### Note table generator (M2) — 8 + 4 + 7 + 98 = 117 bytes
- `nt_arg_table`, `nt_arg_version`, `nt_raw_byte`, `nt_corr_ptr_lo/hi`,
  `nt_truncate`, `nt_t1_byte_off`, `nt_sel_tmp` (8 bytes)
- `dp_hl_lo/hi`, `dp_write_idx`, `dp_temp` — depack_t_pack scratch (4 bytes)
- `gn_note_i`, `gn_octave`, `gn_bc_lo/hi`, `gn_tmp_lo/hi`, `gn_dest_tmp` —
  generate_notes scratch (7 bytes)
- `t1_buf[98]`: working buffer for depacked T_PACK data
- `note_table[192]`: final output, exported for harness

### Volume table generator (M3) — 11 + 256 = 267 bytes
- `vt_H`, `vt_L`, `vt_D`, `vt_E`, `vt_saveH`, `vt_saveL`, `vt_use_rla`,
  `vt_carry`, `vt_write_idx`, `vt_C`, `vt_tmp` (11 bytes)
- `volume_table[256]`: final output, exported for harness

### Parsed PT3 header (M4) — 17 bytes
- `pt3_base_lo/hi`: absolute base address of PT3 file in RAM
- `pt3_version_char`: raw byte from file offset `$0D` (e.g. `'7'` for PT3.7, `'r'` for Vortex)
- `pt3_features_level`: 0 (PT 3.0-3.5), 1 (PT 3.6 / Vortex), or 2 (PT 3.7+)
- `pt3_tone_table` (0..3), `pt3_delay`, `pt3_num_positions`, `pt3_loop_position`
- `pt3_patterns_ptr_lo/hi`: ABSOLUTE pointer to patterns table (6-byte entries,
  one per pattern, each entry = 3 × 2-byte channel stream pointers)
- `pt3_sample_table_lo/hi`: ABSOLUTE = base + `$69`, start of 32 × 2-byte sample pointers
- `pt3_ornament_table_lo/hi`: ABSOLUTE = base + `$A9`, start of 16 × 2-byte ornament pointers
- `pt3_position_list_lo/hi`: ABSOLUTE = base + `$C9`, `num_positions` bytes,
  each byte = `pattern_num × 3`
- `pt3_parse_error`: 0 = OK, 1 = bad signature or `num_positions == 0`

---

## Test files in corpus

Committed to `tests/pt3/`:

| File            | Size   | PT3 version | features_lvl | tone_tbl | num_pos | loop_pos | Why in corpus |
|-----------------|--------|-------------|--------------|----------|---------|----------|---------------|
| yerzmyey_fifteen_colours_2014.pt3    | 8646 B | 3.7         | 2            | 1        | 28      | 0        | Python reference 100% match, primary validation target |
| luchibobra_pt3_player_bug_fix_2000.pt3  | 2236 B | 3.5         | 0            | 2        | 9       | 0        | "ProTracker 3.5 player bug f!x" test file, exercises PT3.5 edge cases |
| v0yager_blobbzgame.pt3  |  839 B | Vortex      | 1            | 2        | 8       | 2        | Smallest file; plays cleanly; exercises Vortex signature branch |

At M11 we add the remaining 17 files from `pt3_python_sim/test_files/` for the
full 20-file regression set.

Reference data derived from these files (also in `tests/`):
- `nt_ref_t{0..3}_v{0,1}.bin`: 8 note-table reference binaries (M2)
- `vt_ref_{old,new}.bin`: 2 volume-table reference binaries (M3)

---

## Build + validate workflow (established)

1. **Design on paper**, milestones spelled out in ARCHITECTURE.md
2. **Implement in Claude sandbox**: edit `player.s` / `harness.py`
3. **Validate locally**: `ca65 + ld65` build → `python3 harness.py m<N>` passes
4. **Transport diff**: `share_artifact` of unified patch (3× smaller than full file)
5. **Apply on branch**: `git checkout -b feature/m<N>-<n>`, apply patch with
   `patch -p1 --fuzz=3` (fuzzy tolerates context drift like missing trailing newlines)
6. **Cross-validate**: rebuild on server → verify `player.bin` md5 matches sandbox
   → run full regression (`python3 tests/harness.py all`)
7. **Commit**: on feature branch with `claude@anthropic.local` git author
8. **Merge**: `git merge --no-ff` to master preserving branch topology in the graph
9. **Tag**: `m<N>-complete` with milestone summary in tag message
10. **Cleanup**: delete feature branch locally and from origin

**Rollback safety**: feature branches exist separately from master until merge.
If M<N> breaks something discovered later, `git revert -m 1 <merge-sha>` rolls
back cleanly; the merge commit preserves full branch history in the graph.

---

## Tooling

### Assembler
- **ca65 / ld65 V2.18** (Kris's server)
- **ca65 / ld65 V2.19** (Claude sandbox)
- Deterministic build confirmed across both versions and both machines — same
  source produces byte-identical `player.bin`. This has been our main integration
  sanity check on every milestone since M1.
- Build config: `src/player.cfg` puts CODE at `$3000`, with hard 4 KB ceiling

### Simulation
- **py65 1.2.0** (Python 6502 emulator) for CPU-level validation
- Custom `AYBusObserver` in `tests/harness.py` hooks writes to `$FD22` / `$FD23`
- Call-sentinel trick: push `0xFEFF` as return address, step CPU until `PC == 0xFF00`,
  so we can invoke any subroutine from Python without simulating IRQ hardware

### Reference
- **pt3_simulator.py** (Python PT3 decoder) — 100% VTII text-dump match on yerzmyey_fifteen_colours_2014.pt3
  (1408/1408 rows, 439/439 sample ticks), 100% bit-exact PSG match (8961/8961 frames)
- **pt3_tables.py** — ports of Bulba VTII10 r7's `NoteTableCreator` + `VolTableCreator`
- All reference binaries in `tests/` generated deterministically from these scripts

### Real hardware
- **YAPE 1.2.7** (Windows) for Plus/4 + DigiMuz emulation — M1 YAPE test passed
- **Real Plus/4 + DigiMuz card** at Kris's home — M1 real-hardware test passed
- VICE does NOT emulate DigiMuz, so YAPE is the only emulator option

---

## Learnings and principles (updated each milestone)

### Assembly gotchas
- **Long BNE / BEQ**: 6502 branches are 8-bit signed, max range ±128 bytes.
  For long loops that span more than that, use `BEQ @done / JMP @target`
  idiom. Bit us in M3 (outer loop to `@outer` was out of range from
  `@skip_einc`; fixed to `BEQ @done / JMP @outer`).
- **`(indirect),y` requires ZP pointer**: 6502 indirect addressing only works
  through zero page. If your pointer lives in absolute memory (BSS), you
  must first copy lo/hi to ZP. We reserved `ZP_TEMP_LO/HI = $E2/$E3` for this.
  Bit us in M2 (nt_corr_ptr lived in BSS, had to copy to ZP before walking).
- **Swap-pair store ordering**: when swapping two pairs of bytes, be careful
  about STA/STX targets. Correct pattern is:
  ```
  lda A_lo   ;  A = A_lo (original)
  ldx B_lo   ;  X = B_lo (original)
  sta B_lo   ;  B_lo = original A_lo  ← target is the OTHER side
  stx A_lo   ;  A_lo = original B_lo  ← target is the OTHER side
  ```
  Inverting STA/STX targets writes originals back to their own slots, making
  swap a no-op. Bit us in M3 (L/E swap wrote originals back; H/D swap was
  correct by accident, so the bug was subtle and only one pair).
- **BSS pointer used in `(zp),y` → Range error at assembly time**, not at runtime.
  In M5a initially I declared `dec_ptr_lo/hi` and `dec_out_ptr_lo/hi` as BSS
  labels (`.res 1`), then wrote `sta (dec_ptr_lo),y`. ca65 emits 50+ "Range
  error" at every such instruction because `(zp),y` addressing mode encodes
  the ZP address as a single byte in the opcode — BSS labels at `$36xx` don't
  fit. Fix: declare ZP aliases in `.inc` file (`M5_PTR_LO = ZP_TEMP_LO`, etc.)
  and use those instead. The BSS entries can be deleted since ZP slots are
  physically there. **Shared ZP slot trick**: M5_PTR and M5_OUT alias to the
  same `ZP_TEMP` slots that apply_corrections uses (M2). Safe because those
  two routines never run concurrently — apply_corrections runs during
  player_build_note_table (init time), pattern decoder runs during playback.
- **Long BCC/BCS to deferred targets also hit range limits** in M5a dispatch
  ladder. A `bcc @range_b0_bf` over 160+ bytes won't link. Fix is the same
  `BCC @skip / JMP @target / @skip:` idiom as BEQ/BNE. Inverting the sense
  and using a local 2-byte branch to a JMP trampoline gives full 16-bit
  range at the cost of 3 extra bytes per branch.

### PT3 format surprises (vs prior docs / memory)
- **Position list has `0xFF` terminator AND `num_positions` count — both are authoritative.**
  Verified against all 19 test files in corpus: byte at offset `$C9 + num_positions`
  is `$FF` in every file. Deater's PT3 spec documents the terminator explicitly;
  Python simulator uses `num_positions` as length and ignores the terminator byte,
  so both interpretations work on well-formed files. M4 uses `num_positions`.
  Defensive M5 code may want to validate the terminator is `$FF` as a corruption
  check. **Earlier sessions (including M4 commit message) incorrectly claimed
  there was no terminator — that was wrong.**
- **Position list bytes are `pattern_num × 3`**, stored as `pn*3` (0, 3, 6, ...).
  To get the actual pattern number you either divide by 3 or index directly
  using the byte as an offset into a 3-byte-per-pattern lookup scheme. VTII
  and Python sim divide to get `pn`. M5 design will use this.
- **Patterns table is array of 6-byte entries**, not a flat pointer.
  Entry X at `pat_ptr + X*6` contains 3 × 2-byte LE pointers for streams A, B, C.
  M5 consumes this.
- **Header pointers are file-relative**. M4 converts them to absolute
  (`base + file_offset`) at parse time — simplifies M5+ which can use them
  directly without adding base each time.
- **features_level matters for effects**: Gliss/Portamento behavior differs
  between PT3.5 (level 0), PT3.6/Vortex (level 1), PT3.7+ (level 2).
  Parsed in M4, consumed in M9. Documented in VTII `trfuncs.pas` lines 2346-2356.

### Workflow learnings
- **Python reference before 6502 code**. Every milestone starts by confirming
  expected output from Python, then matches bit-exactly. Reduces debug cycles
  because the target is unambiguous.
- **Patches beat full files for transport**. M4 used 11 KB of diff vs 33 KB
  of full file. Use `diff -u --label "a/..." --label "b/..."` for clean
  `patch -p1`-compatible output.
- **Fuzzy patch saves the day** when context drifts. `patch --fuzz=3` tolerates
  up to 3 lines of context mismatch (e.g. missing trailing newlines after
  a previous transport). After apply, always re-run full regression to catch
  any actual semantic drift.
- **Deterministic build is our primary integration check**. If md5 of `player.bin`
  matches between sandbox and server after transport + rebuild, we know the
  transport was lossless and the two toolchains agree. Any mismatch is a
  red flag before even looking at test output.
- **Golden reference binary for bulk validation**. M5a needs to validate 4381
  rows × 12 bytes = ~53 KB of expected output. Writing that inline in Python
  test code is awful. Instead: generate a binary file via Python sim
  (`tests/m5a_ref_*.bin`) with a simple framing format — magic + seq count,
  then per seq: pattern_num, channel, start_ptr, num_rows, then rows inline.
  Harness iterates the file, calls decoder, diffs byte-by-byte. Fast, scalable,
  language-agnostic. Approach reusable for M5b, M6, M7+.
- **M5a under budget pressure**: estimated 280B, actual 669B (2.4× over).
  Dispatch ladder with 14 opcode ranges + SPC_CMD consumption is verbose on
  6502 — every handler starts with `ldy #offset / sta (M5_OUT_LO),y / jmp
  @decode_loop`, and per-channel prolog/epilog triplets repeat. Accepted for
  M5a because it works bit-exact first try. If budget gets tight in M8-M9,
  collapse triplets into table-driven dispatch for ~100-200 B savings.

---

## Open questions for M5+

1. **Per-channel state layout**: struct-of-arrays (3 arrays indexed by channel)
   or array-of-structs (3 struct copies)? ARCHITECTURE.md picked SoA for
   cache locality. Confirm when implementing M5.

2. **Pattern stream pointer update**: keep 3 separate "current stream pointer"
   fields (one per channel) or one that gets swapped in/out? Likely 3 separate
   ZP pointer slots for speed.

3. **Row-advance trigger**: PT3 has per-channel `skip` counter. Row advances
   when all three reach zero. Lockstep or independent per-channel advance?

4. **Pattern length detection**: VTII detects length by "row count until
   channel A stream hits `$00`". We need this too (design note #14: variable
   pattern length). Cache per pattern, or recompute each entry?

5. **Effect state allocation**: some effects (PORTM, VIBRT, ENGLS) need
   per-channel accumulators. 3 channels × 5-10 bytes per effect state =
   150-300 bytes just for effect state BSS. Budget carefully.

### Deferred hardware questions
1. Will we support Sukkopera-style alternative AY cards (e.g. DigiMoooZ
   on LittleSixteen)? Likely yes via register-address indirection through
   a jump-table entry.
2. Real-hardware validation protocol for M5+: Kris runs each milestone's
   `m<N>_test.prg` on real Plus/4 + DigiMuz, listens for audible issues.
   If py65 passes but real hardware sounds wrong, the bug is in our AY-bus
   understanding, not the decoder.
