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
