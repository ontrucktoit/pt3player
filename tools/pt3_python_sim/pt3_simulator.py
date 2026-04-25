#!/usr/bin/env python3
"""
PT3 Per-Tick Simulator -> PSG stream generator.

This is the second half of the PT3 specification (the first half being
the pattern/sample/ornament parser). It simulates what the player does
PER TICK (50Hz), computing the 14 AY registers and emitting a PSG file.

This should match AY_Emul / Vortex Tracker II's PSG export exactly.
Gaps between our output and theirs tell us exactly where our bit-level
interpretation is wrong.

Model:
  - 50 Hz master tick
  - Every `Speed` ticks, a new pattern row is decoded (per channel, but with skip)
  - Every tick: per-channel CHREGS computes AY register values:
      * advance sample position (with loop wrap)
      * advance ornament position (with loop wrap)
      * compute tone period = note_table[note + ornament_offset] + sample_tone_offset
      * compute volume = sample_amplitude (+ envelope flags)
      * mixer bits from sample byte 1 T/N flags
      * envelope period/shape from pattern opcodes
  - Write 14 AY registers to the output stream
  - Output: PSG file

Register layout (AY-3-8910):
  R0/R1:  Channel A tone period (12-bit, LE)
  R2/R3:  Channel B tone period
  R4/R5:  Channel C tone period
  R6:     Noise period (5-bit)
  R7:     Mixer (bit 0-5: tone/noise enable per channel, 0 = enable)
  R8:     Channel A amplitude (4 bits + bit 4 = envelope mode)
  R9:     Channel B amplitude
  R10:    Channel C amplitude
  R11/R12: Envelope period (16-bit LE)
  R13:    Envelope shape (0-15)
"""

import struct
from pathlib import Path
from typing import List, Optional

from pt3_pattern_decoder import (
    ChannelStreamState, RowState, SpecCmd,
    decode_next_row, SPC_CMD_PARAM_BYTES,
)
from pt3_sample_decoder import decode_all_samples


# -------- Note table (Vortex Tracker II "ST" - table 1, most common) ---------
# First octave reference values (from published Vortex sources, ZX clock 1773400 Hz):
NT_ST_OCT1 = [
    0x0EF8, 0x0E10, 0x0D60, 0x0C80, 0x0BD8, 0x0B28,
    0x0A88, 0x09F0, 0x0960, 0x08E0, 0x0858, 0x07E0,
]


def build_note_table_st() -> List[int]:
    """Build full 96-note table (C-1..B-8) for ST tuning."""
    table = list(NT_ST_OCT1)
    for octave in range(1, 8):
        for i in range(12):
            table.append(NT_ST_OCT1[i] >> octave)
    return table


NOTE_TABLE_ST = build_note_table_st()


# -------- Parsed module container --------
def _compute_pattern_length(data: bytes, ch_ptrs) -> int:
    """Compute pattern length by porting VTII load logic (trfuncs.pas 2284-2312).
    
    Iterates through the pattern incrementing row counter `i` for each row.
    Ch A (channel 0) controls end: when it's time to decode ch A and the next byte
    in ch A stream is $00, pattern ends with length = i (not incremented).
    
    This is the canonical algorithm — does NOT assume 64 rows. PT3.6/VTII 1.0
    files can have arbitrary lengths (Pator has patterns of 64 and 128 rows).
    """
    from pt3_pattern_decoder import decode_next_row, ChannelStreamState
    states = [ChannelStreamState(ptr=p) for p in ch_ptrs]
    i = 0
    quit_flag = False
    while not quit_flag and i < 256:
        for k in range(3):
            states[k].skip_counter -= 1
            if states[k].skip_counter == 0:
                if k == 0 and states[0].ptr < len(data) and data[states[0].ptr] == 0x00:
                    quit_flag = True
                    break
                if states[k].ptr < len(data):
                    decode_next_row(data, states[k])
        if quit_flag:
            break
        i += 1
    return i


class PT3Module:
    def __init__(self, path: str):
        data = Path(path).read_bytes()
        self.data = data
        
        # Header
        self.version = chr(data[0x0D])
        
        # FeaturesLevel detection (VTII trfuncs.pas line 2346-2356):
        # "ProTracker 3." + char at [13]:
        #   '0'..'5' -> level 0 (classic PT3)
        #   '7'..'9' -> level 2 (PT3.7+ behaviors)
        #   else      -> level 1
        # "Vortex Tracker II" -> level 1
        # other -> level 0
        # 
        # FeaturesLevel affects effects 1/2/3 (Gliss/Portamento) behavior:
        #   - >=2: if Gls delay == 0, Inc(Gls) so counter is 1 (effects 1,2)
        #   - >=1: portamento (effect 3) allows release as source
        #   - >=1: portamento uses existing Current_Ton_Sliding as start (effect 3)
        name_prefix_pt3 = b'ProTracker 3.'
        name_prefix_vortex = b'Vortex Tracker II'
        if data[:len(name_prefix_pt3)] == name_prefix_pt3:
            ver_char = data[13]
            if 0x30 <= ver_char <= 0x35:  # '0'..'5'
                self.features_level = 0
            elif 0x37 <= ver_char <= 0x39:  # '7'..'9'
                self.features_level = 2
            else:  # '6' or other
                self.features_level = 1
        elif data[:len(name_prefix_vortex)] == name_prefix_vortex:
            self.features_level = 1
        else:
            self.features_level = 0
        
        self.tone_table_idx = data[0x63]
        self.initial_speed = data[0x64]
        self.num_pos = data[0x65]
        self.loop_pos = data[0x66]
        self.pat_ptr = struct.unpack('<H', data[0x67:0x69])[0]
        
        # Sample/ornament pointers
        self.sample_ptrs = [struct.unpack('<H', data[0x69 + i*2:0x69 + i*2 + 2])[0]
                            for i in range(32)]
        self.ornament_ptrs = [struct.unpack('<H', data[0xA9 + i*2:0xA9 + i*2 + 2])[0]
                              for i in range(16)]
        
        # Position list
        positions = list(data[0xC9:0xC9 + self.num_pos])
        self.pattern_numbers = [p // 3 for p in positions]
        
        # Compute per-pattern length by porting VTII load logic (trfuncs.pas 2284-2312):
        # Pattern length = number of rows until ChPtr[0] (ch A) points to $00.
        # Critical for VTII 1.0 / PT3.6 files where patterns can have non-standard
        # lengths (not always 64). VTII TXT "pattern 4" in Pator has 128 rows.
        self.pattern_lengths = {}
        unique_pats = set(self.pattern_numbers)
        for pat_num in unique_pats:
            base = self.pat_ptr + pat_num * 6
            ch_a = struct.unpack('<H', data[base:base+2])[0]
            ch_b = struct.unpack('<H', data[base+2:base+4])[0]
            ch_c = struct.unpack('<H', data[base+4:base+6])[0]
            self.pattern_lengths[pat_num] = _compute_pattern_length(data, (ch_a, ch_b, ch_c))
        
        # Parse samples
        self.samples = decode_all_samples(data, self.sample_ptrs)
        
        # Parse ornaments
        self.ornaments = {}
        for idx, ptr in enumerate(self.ornament_ptrs):
            if ptr != 0:
                loop_pos = data[ptr]
                length = data[ptr + 1]
                values = []
                for i in range(length):
                    b = data[ptr + 2 + i]
                    values.append(b - 256 if b >= 128 else b)
                self.ornaments[idx] = {
                    'loop_pos': loop_pos, 'length': length, 'values': values
                }
        
        # Build note and volume tables at runtime using Ivan Roshin's algorithms
        # (ports of Bulba's VTII10 r7 asm code, guarantees bit-exact VTII/AY_Emul match).
        from pt3_tables import build_note_table, build_volume_table
        # Map PT3 version character to Bulba's version: '3','4','5','6','7' -> 3,4,5,6,7
        # clamped to 6 if >= 10 (asm does SUB #30 then CP 10 / JR C / LD A,6)
        try:
            pt_version = int(self.version) if self.version.isdigit() else 6
        except (AttributeError, ValueError):
            pt_version = 6
        if pt_version >= 10:
            pt_version = 6
        # VersionForNoteTable: asm does CP 4, sets carry if version<4.
        # In our NT_SELECTOR[table][idx]: idx 0 = NEW (version>=4), idx 1 = OLD (version<4).
        version_is_old = 1 if pt_version < 4 else 0
        self.note_table = build_note_table(self.tone_table_idx, version_is_old)
        # Volume table: VTII uses a single hardcoded table (trfuncs.pas line 723,
        # PT3_Vol, labeled "Volume table of Pro Tracker 3.5x") for ALL PT3 versions
        # regardless of source file. When VTII generates reference PSG output from
        # e.g. PT3.3 or PT3.4 files, it still uses this "new" table. To match VTII
        # bit-exact we must pass pt_version=7 (ensures use_rla=True branch in
        # build_volume_table, which produces the new table). Discovered via Foxx-1998
        # PT3.3 test file — all amp registers were off-by-1 using the "old" table
        # that Bulba's original asm selected for pt_version<5.
        self.volume_table = build_volume_table(pt_version=7)


# -------- Channel state during playback --------
class Channel:
    def __init__(self, name: str):
        self.name = name  # 'A', 'B', 'C'
        
        # Pattern stream state (reuses parser's state)
        self.stream_state: Optional[ChannelStreamState] = None
        
        # Note and modifiers
        self.note: Optional[int] = None         # 0-95, None if no note yet
        self.prev_note: Optional[int] = None    # Saved previous note for portamento (VTII: PrNote)
        self.note_released: bool = False        # True after release
        self.volume: int = 0xF                  # 0-F master volume for channel
        
        # Current sample and ornament references.
        # VTII quirk (trfuncs.pas line 887): default Sample = 1 even though PT3
        # original editor has no concept of default sample. Matters when a note
        # triggers on a channel that never had an explicit sample set — without
        # this default, note plays silently (sample_num=0 means "no sample").
        # Comment in VTII source: "сэмпла по умолчанию в PT3 нет, а здесь сделано"
        # = "no default sample in PT3, but we made one here".
        self.sample_num: int = 1
        self.pos_in_sample: int = 0
        self.ornament_num: int = 0
        self.pos_in_ornament: int = 0
        
        # Envelope
        self.envelope_enabled: bool = False     # true when env_type is 1..E
        
        # Amplitude slide accumulator (driven by sample byte 0 bit 7)
        # Persists across ticks, resets on new note trigger.
        self.amp_slide_accum: int = 0
        
        # Tone accumulator (driven by sample byte 1 bit 6 "Accumulate Tone")
        # When bit set, sample's Add_to_Ton gets accumulated across ticks.
        # Port of VTII: if Ton_Accumulation then Ton_Accumulator := Ton
        self.ton_accumulator: int = 0
        
        # Per-channel envelope/noise slide accumulators (driven by sample byte 1
        # bit 6 + Add_to_Envelope_or_Noise). These persist across ticks until
        # note retrigger.
        self.current_envelope_sliding: int = 0
        self.current_noise_sliding: int = 0
        
        # Ton slide state (effects 1/2/3: glissando up/down, portamento)
        # Port of VTII: Ton_Slide_Delay (reload value), Ton_Slide_Count (countdown),
        # Ton_Slide_Step (step per trigger), Ton_Slide_Delta (target delta for portamento),
        # Slide_To_Note (target note for portamento), Ton_Slide_Type (0=gliss, 1=portamento).
        self.ton_slide_delay: int = 0
        self.ton_slide_count: int = 0
        self.ton_slide_step: int = 0
        self.ton_slide_delta: int = 0
        self.slide_to_note: int = 0
        self.ton_slide_type: int = 0
        self.current_ton_sliding: int = 0
        # Saved Current_Ton_Sliding captured BEFORE note trigger reset, used by
        # PORTM (effect 3) for FeaturesLevel >= 1 (VTII trfuncs.pas lines 1232-1233):
        # "if FeaturesLevel >= 1 then Current_Ton_Sliding := TS" where TS is the
        # pre-trigger value. Without this, chained portamento loses accumulated slide.
        self.saved_ton_sliding: int = 0
        
        # Vibrato state (effect 6: on/off toggle)
        # Port of VTII: OnOff_Delay/OffOn_Delay = timer reload values,
        # Current_OnOff = countdown until toggle, SoundEnabled = current mute state.
        self.onoff_delay: int = 0
        self.offon_delay: int = 0
        self.current_onoff: int = 0
        
        # Flags
        self.enabled: bool = False              # becomes true after first note
        self.sound_enabled: bool = True         # VTII: SoundEnabled. Toggled by vibrato (effect 6).
                                                # When False, amplitude = 0 regardless of volume.
    
    def reset_sample_ornament(self):
        """Called when a new note is played (PD_NOTE / PD_REL trigger).
        
        Port of VTII: note trigger resets all per-channel effect accumulators.
        """
        self.pos_in_sample = 0
        self.pos_in_ornament = 0
        self.amp_slide_accum = 0
        self.ton_accumulator = 0
        self.current_envelope_sliding = 0
        self.current_noise_sliding = 0
        self.current_ton_sliding = 0
        self.ton_slide_count = 0
        self.current_onoff = 0


# -------- PSG writer --------
class PSGWriter:
    def __init__(self):
        self.frames: List[dict] = []  # each frame is dict {reg: value} of CHANGES (PSG-format)
        self.raw_frames: List[List[int]] = []  # each frame is full [R0..R13] snapshot, may contain R13=0xFF sentinel
        self.last_state = [0] * 14
    
    def write_frame(self, new_state: List[int]):
        """Record a frame. Only writes that changed from last frame are stored.

        R13 (envelope shape) honors the 0xFF sentinel meaning 'do not write R13
        this frame' — see simulate() and the comment in pt3_player.s about why
        unconditional R13 writes restart the envelope generator on real AY.

        - new_state[13] == 0xFF: do not record an R13 write (sentinel)
        - new_state[13] != 0xFF AND differs from last_state[13]: record
        - last_state[13] is updated only when we actually write, so the
          'previous shape' tracking matches what the AY chip really saw.
        """
        changes = {}
        for r in range(14):
            if r == 13:
                # R13: skip when sentinel; only record real writes that change shape
                if new_state[13] == 0xFF:
                    continue
                if new_state[13] != self.last_state[13]:
                    changes[13] = new_state[13]
                    self.last_state[13] = new_state[13]
                continue
            if new_state[r] != self.last_state[r]:
                changes[r] = new_state[r]
                self.last_state[r] = new_state[r]
        self.frames.append(changes)
        # Also keep a raw snapshot of the full register state (with 0xFF
        # sentinel preserved). This is what the 6502 player's shadow_ay holds
        # at the end of player_tick, and is used by gen_m6_golden.py to
        # produce the m6_ref_*.bin oracle for harness.py bit-exact tests.
        self.raw_frames.append(list(new_state))
    
    def emit_psg_bytes(self) -> bytes:
        """Produce PSG binary."""
        out = bytearray()
        # Header
        out.extend(b'PSG\x1a')
        out.extend(b'\x00' * 12)  # padding
        
        # Stream
        for frame in self.frames:
            out.append(0xFF)  # frame marker
            for r in sorted(frame.keys()):
                out.append(r)
                out.append(frame[r])
        
        return bytes(out)


# -------- Simulator --------
def simulate(mod: PT3Module, max_frames: int = 100, verbose: bool = False) -> PSGWriter:
    """Run PT3 simulation for `max_frames` and return PSG-ready frame list."""
    psg = PSGWriter()
    channels = [Channel('A'), Channel('B'), Channel('C')]
    
    # AY register state
    ay_regs = [0] * 14
    
    # Global state
    speed = mod.initial_speed
    noise_period = 0
    env_period = 0
    env_shape = 0   # R13
    add_to_noise = 0  # persistent between frames; updated only when a channel writes
    sam_noise = 0  # VTII: SamNoise - sticky between frames, updated when a channel has Mixer_Noise
    sam_env_p = 0  # VTII: SamEnvP - reset at start of each frame, accumulated per channel
    tick_in_row = 0  # counts 0..speed-1; at 0, decode new row
    position_idx = 0  # index in position list (which pattern)
    current_line = 0  # row index within current pattern (VTII: CurrentLine)
    current_pattern_length = 64  # will be set by load_pattern
    
    # Envelope slide state (effects 9, 10 - EnvSlide down/up)
    # Global, not per-channel. Port of VTII: Env_Delay (reload), Cur_Env_Delay
    # (countdown), Env_Slide_Add (step per trigger), Cur_Env_Slide (accumulated slide).
    env_delay = 0
    cur_env_delay = 0
    env_slide_add = 0
    cur_env_slide = 0
    
    # Initialize channel stream pointers for first pattern
    def load_pattern(pat_num: int):
        nonlocal current_pattern_length, current_line, noise_period
        base = mod.pat_ptr + pat_num * 6
        ch_a = struct.unpack('<H', mod.data[base:base+2])[0]
        ch_b = struct.unpack('<H', mod.data[base+2:base+4])[0]
        ch_c = struct.unpack('<H', mod.data[base+4:base+6])[0]
        for ch, ptr in zip(channels, [ch_a, ch_b, ch_c]):
            ch.stream_state = ChannelStreamState(ptr=ptr)
        current_pattern_length = mod.pattern_lengths.get(pat_num, 64)
        current_line = 0
        # VTII trfuncs.pas line 2290: NsBase := 0 at start of each pattern decode.
        # Noise_Base (our noise_period) is persistent within pattern (last opcode
        # 0x20-0x3F seen), but resets to 0 when switching to new pattern.
        noise_period = 0
    
    load_pattern(mod.pattern_numbers[position_idx])
    
    # Frame 0 is the "initial" frame - all zeros
    psg.write_frame(ay_regs)
    
    for frame in range(1, max_frames + 1):
        # VTII trfuncs.pas line 1100: SamEnvP := 0 at start of each frame
        # (SamNoise NOT reset - it's sticky between frames)
        sam_env_p = 0
        
        # PT3 R13 convention: AY envelope shape register is only WRITTEN when
        # the row contains an explicit SETENV opcode (env_type 1..14). Writing
        # R13 with the same value on every frame retriggers the envelope
        # generator at 50 Hz, producing audible buzz in any song using envelopes.
        # We set this flag in the SETENV branch below; if False at frame end,
        # we mark R13 in ay_regs as 0xFF (= "do not write to AY" sentinel).
        env_retrigger_this_frame = False
        
        # On row boundaries (tick_in_row == 0), decode new pattern row per channel
        if tick_in_row == 0:
            # VTII pattern length check (trfuncs.pas 1284-1289):
            # if Patterns[CurrentPattern].Length <= CurrentLine then end pattern.
            # Must be checked BEFORE decode, to avoid reading past pattern end.
            if current_line >= current_pattern_length:
                for ch in channels:
                    ch.stream_state.end_of_pattern = True
            
            # First try decode for each channel. If any returns None (end of pattern),
            # check if ALL channels ended; if so, load next pattern and re-decode.
            decoded_this_tick = [False, False, False]
            
            for attempt in range(2):  # at most 2 attempts: before and after pattern switch
                for ci, ch in enumerate(channels):
                    if decoded_this_tick[ci]:
                        continue
                    if ch.stream_state.end_of_pattern:
                        continue
                    ch.stream_state.skip_counter -= 1
                    if ch.stream_state.skip_counter > 0:
                        decoded_this_tick[ci] = True  # skip = no decode needed this row
                        continue
                    row = decode_next_row(mod.data, ch.stream_state)
                    if row is None:
                        # end_of_pattern just got set; leave decoded_this_tick[ci]=False
                        continue
                    decoded_this_tick[ci] = True
                    apply_row_to_channel(ch, row, mod)
                    if row.env_period is not None:
                        env_period = row.env_period
                    if row.env_type is not None and 1 <= row.env_type <= 14:
                        env_shape = row.env_type
                        # VTII trfuncs.pas line 1184-1185: a row with env_type in 1..14
                        # (i.e. Envelope not in [0, 15]) resets cur_env_slide and 
                        # cur_env_delay. This stops any prior EnvSlide effect.
                        cur_env_slide = 0
                        cur_env_delay = 0
                        # Mark R13 as needing a real write to AY this frame.
                        env_retrigger_this_frame = True
                    if row.noise_period is not None:
                        noise_period = row.noise_period
                    # Dispatch PT3 binary spec_cmd (0x01..0x09) into VTII effects.
                    # Port of VTII trfuncs.pas lines 1200-1266 (case Number of)
                    # combined with PT3->VTII semantic mapping (lines 2184-2270).
                    #
                    # PT3 cmd -> VTII effect number:
                    #   $01 + positive amount -> effect 1 (gliss down)
                    #   $01 + negative amount -> effect 2 (gliss up, |amount|)
                    #   $02                   -> effect 3 (portamento to note)
                    #   $03                   -> effect 4 (sample position)
                    #   $04                   -> effect 5 (ornament position)
                    #   $05                   -> effect 6 (vibrato)
                    #   $08 + positive amount -> effect 9 (envslide down)
                    #   $08 + negative amount -> effect 10 (envslide up)
                    #   $09                   -> effect 11 (delay/speed change)
                    if row.spec_cmd is not None:
                        sc = row.spec_cmd
                        cmd = sc.cmd
                        raw = sc.raw_bytes
                        
                        if cmd == 0x09:
                            # Speed change (VTII effect 11)
                            if raw:
                                new_delay = raw[0]
                                if new_delay != 0:
                                    speed = new_delay
                        
                        elif cmd == 0x01 and len(raw) >= 3:
                            # PT3 $01 = GLISS. raw = [delay, amount_lo, amount_hi] (signed 16-bit LE).
                            # VTII: Ton_Slide_Delay, Ton_Slide_Step, Ton_Slide_Type=0.
                            delay = raw[0]
                            amount = raw[1] | (raw[2] << 8)
                            if amount >= 0x8000:
                                amount -= 0x10000
                            # FeaturesLevel >= 2: if delay == 0, treat as 1 
                            gls = delay
                            if gls == 0 and mod.features_level >= 2:
                                gls = 1
                            ch.ton_slide_delay = gls
                            ch.ton_slide_count = gls
                            # VTII: effect 1 (pos) uses +amount, effect 2 (neg) uses -(-amount) = -amount
                            # So: step = amount (both cases give correct sign)
                            ch.ton_slide_step = amount if amount >= 0 else -(-amount)
                            # Wait: VTII case 1 uses +param, case 2 uses -param (where param is the
                            # absolute value stored). In PT3, raw amount preserves sign.
                            # Simplification: step is the original signed amount.
                            ch.ton_slide_step = amount
                            ch.ton_slide_type = 0
                            ch.current_onoff = 0
                        
                        elif cmd == 0x02 and len(raw) >= 5:
                            # PT3 $02 = PORTM. raw = [delay, ?, ?, amount_lo, amount_hi].
                            # Per VTII line 2209-2222: delay = raw[0], skip 2 bytes, then
                            # 2-byte signed amount. |Tmp| stored as Parameter (unsigned).
                            delay = raw[0]
                            amount = raw[3] | (raw[4] << 8)
                            if amount >= 0x8000:
                                amount -= 0x10000
                            abs_amount = amount if amount >= 0 else -amount
                            
                            # VTII effect 3 (portamento to note). Applied when:
                            #   Note >= 0  (new note this row), OR
                            #   Note != -2 (not release) AND FeaturesLevel >= 1.
                            # Here row.note is the new note (or 'release' for -2, or None for no note).
                            # In VTII: Note is the note field stored in Items (after pattern decode).
                            #   Note = -1 means "no note this row"
                            #   Note = -2 means release ('R--')
                            apply_portamento = False
                            if row.note is not None and row.note != 'release':
                                apply_portamento = True  # new note this row
                            elif row.note is None and mod.features_level >= 1:
                                apply_portamento = True  # no note but PT3.6+
                            # Otherwise (release or FeaturesLevel 0 with no note): skip
                            
                            if apply_portamento and ch.note is not None:
                                prev_note = ch.prev_note if ch.prev_note is not None else ch.note
                                target_note = ch.note
                                
                                ch.ton_slide_delay = delay
                                ch.ton_slide_count = delay
                                # Delta = target_freq - source_freq
                                source_freq = mod.note_table[max(0, min(95, prev_note))]
                                target_freq = mod.note_table[max(0, min(95, target_note))]
                                ch.ton_slide_delta = target_freq - source_freq
                                ch.slide_to_note = target_note
                                ch.note = prev_note  # VTII: set Chans[Ch].Note := PrNote
                                # VTII trfuncs.pas lines 1232-1233: for FeaturesLevel >= 1,
                                # preserve pre-trigger Current_Ton_Sliding (TS) across the
                                # note reset. Without this, portamento "reaching target" 
                                # detection misbehaves when portamento chain continues across
                                # row boundaries. ch.saved_ton_sliding is captured in
                                # apply_row_to_channel BEFORE the reset.
                                if mod.features_level >= 1:
                                    ch.current_ton_sliding = ch.saved_ton_sliding
                                
                                # Step = abs_amount, sign-reversed if delta - sliding < 0
                                step = abs_amount
                                if ch.ton_slide_delta - ch.current_ton_sliding < 0:
                                    step = -step
                                ch.ton_slide_step = step
                                ch.ton_slide_type = 1
                                ch.current_onoff = 0
                        
                        elif cmd == 0x03 and len(raw) >= 1:
                            # PT3 $03 = SMPOS -> VTII effect 4: SamplePosition := Parameter
                            ch.pos_in_sample = raw[0]
                        
                        elif cmd == 0x04 and len(raw) >= 1:
                            # PT3 $04 = ORPOS -> VTII effect 5: OrnamentPosition := Parameter
                            ch.pos_in_ornament = raw[0]
                        
                        elif cmd == 0x05 and len(raw) >= 2:
                            # PT3 $05 = VIBRT -> VTII effect 6: on/off toggle
                            # VTII: OffOn_Delay = Parameter and 15, OnOff_Delay = Parameter shr 4
                            # Parameter in VTII = (raw[0] shl 4) | raw[1] (per line 2237-2241)
                            param = (raw[0] << 4) | raw[1]
                            ch.offon_delay = param & 0x0F
                            ch.onoff_delay = (param >> 4) & 0x0F
                            ch.current_onoff = ch.onoff_delay
                            ch.ton_slide_count = 0
                            ch.current_ton_sliding = 0
                        
                        elif cmd == 0x08 and len(raw) >= 3:
                            # PT3 $08 = ENGLS. raw = [delay, amount_lo, amount_hi] (signed 16-bit).
                            # VTII effect 9 (pos) or 10 (neg):
                            #   Env_Delay := delay, Cur_Env_Delay := Env_Delay
                            #   Env_Slide_Add := +amount (effect 9) or -|amount| (effect 10)
                            # In PT3, raw amount is signed; we use it directly.
                            delay = raw[0]
                            amount = raw[1] | (raw[2] << 8)
                            if amount >= 0x8000:
                                amount -= 0x10000
                            env_delay = delay
                            cur_env_delay = env_delay
                            env_slide_add = amount
                
                # Did all channels decode (or skip)? Done.
                if all(decoded_this_tick):
                    # VTII: Inc(CurrentLine) after a successful row decode 
                    # (trfuncs.pas line 1293).
                    current_line += 1
                    break
                
                # Some channel hit end_of_pattern. If ALL ended, advance pattern.
                if all(ch.stream_state.end_of_pattern for ch in channels):
                    position_idx += 1
                    if position_idx >= len(mod.pattern_numbers):
                        position_idx = mod.loop_pos
                    load_pattern(mod.pattern_numbers[position_idx])
                    # After load_pattern, end_of_pattern is reset, try decoding again
                else:
                    # Only some channels ended. The remaining ones will stay silent this row.
                    # This shouldn't really happen in well-formed PT3 files.
                    break
        
        # Per-tick: compute AY registers for each channel
        # Note: noise R6 = (Ns_Base + AddToNs) & 0x1F, where AddToNs is a GLOBAL
        # value written per-tick by each channel's sample. Channels process in 
        # order A -> B -> C; last channel that writes AddToNs wins. Writes happen
        # only when sample byte[1] bit 7 = 0 (noise mode, not envelope-slide mode).
        mixer = 0
        # add_to_noise is persistent across frames - only updated when a channel writes to it
        for ci, ch in enumerate(channels):
            if not ch.enabled or ch.note is None:
                # Channel has never played yet. PT3 INIT sets mixer = 0 (all enabled
                # on AY chip after reset). We must NOT force disable bits here —
                # ref PSG shows these channels as enabled in mixer but silent via
                # amplitude=0 and tone_period=0.
                amp_reg = 0
                tone_period = 0
                # Don't touch mixer bits — leave as 0 (= enabled).
            elif ch.note_released:
                # RELEASE: keep previous tone register values (don't write them),
                # amplitude = 0, but continue sample/ornament advance.
                # Don't force mixer bits - leave previous mixer state (or 0=enabled).
                amp_reg = 0
                tone_period = None  # sentinel: don't write R4/R5
            elif not ch.sound_enabled:
                # Vibrato muted this tick (SoundEnabled=False via effect 6).
                # VTII sets Amplitude := 0 (line 1057) and skips sample/ornament 
                # advance for this tick. Tone register keeps previous value.
                amp_reg = 0
                tone_period = None
                # BUT: we still need to run Ton_Slide and Vibrato countdown this tick
                # (VTII lines 979-1071 run outside the SoundEnabled check).
                # Ton slide:
                if ch.ton_slide_count > 0:
                    ch.ton_slide_count -= 1
                    if ch.ton_slide_count == 0:
                        ch.current_ton_sliding += ch.ton_slide_step
                        ch.ton_slide_count = ch.ton_slide_delay
                        if ch.ton_slide_type == 1:
                            reached = False
                            if ch.ton_slide_step < 0 and ch.current_ton_sliding <= ch.ton_slide_delta:
                                reached = True
                            elif ch.ton_slide_step >= 0 and ch.current_ton_sliding >= ch.ton_slide_delta:
                                reached = True
                            if reached:
                                ch.note = ch.slide_to_note
                                ch.ton_slide_count = 0
                                ch.current_ton_sliding = 0
                # Vibrato countdown:
                if ch.current_onoff > 0:
                    ch.current_onoff -= 1
                    if ch.current_onoff == 0:
                        ch.sound_enabled = not ch.sound_enabled
                        ch.current_onoff = ch.onoff_delay if ch.sound_enabled else ch.offon_delay
            else:
                # Compute tone period from note + ornament offset + sample tone offset
                orn_offset = 0
                if ch.ornament_num != 0 and ch.ornament_num in mod.ornaments:
                    orn = mod.ornaments[ch.ornament_num]
                    if ch.pos_in_ornament < len(orn['values']):
                        orn_offset = orn['values'][ch.pos_in_ornament]
                
                effective_note = max(0, min(95, ch.note + orn_offset))
                base_period = mod.note_table[effective_note]
                
                sample_tone_offset = 0
                sample_volume = 0xF
                sample_tone_on = True
                sample_noise_on = False
                sample_env_on = False
                
                if ch.sample_num != 0 and ch.sample_num in mod.samples:
                    samp = mod.samples[ch.sample_num]
                    if ch.pos_in_sample < len(samp.ticks):
                        tick = samp.ticks[ch.pos_in_sample]
                        # Port of VTII trfuncs.pas line 957:
                        #   Ton := Ton_Accumulator + Samples[...].Add_to_Ton;
                        #   if Ton_Accumulation then Ton_Accumulator := Ton;
                        # The accumulator always contributes; Ton_Accumulation 
                        # flag controls whether the current sum is stored back.
                        sample_tone_offset = ch.ton_accumulator + tick.tone_offset
                        if tick.tone_accumulate:
                            ch.ton_accumulator = sample_tone_offset
                        sample_volume = tick.volume
                        sample_tone_on = tick.tone_on
                        sample_noise_on = tick.noise_on
                        sample_env_on = tick.envelope_on
                        
                        # Port of VTII trfuncs.pas lines 1019-1034: noise/envelope sliding.
                        # 
                        # Add_to_Envelope_or_Noise is a signed 5-bit value:
                        #   raw_byte0 >> 1 masked to 5 bits, sign-extended from bit 4.
                        # 
                        # Routing depends on Mixer_Noise (= byte[1] & 0x80 == 0):
                        #   - Mixer_Noise=True  (byte1 bit 7 == 0, noise enabled): 
                        #         SamNoise := Current_Noise_Sliding + Add_to_EorN
                        #         if accumulation flag: Current_Noise_Sliding := SamNoise
                        #     (SamNoise is sticky between frames, last channel with
                        #      Mixer_Noise=True wins for this frame)
                        #   - Mixer_Noise=False (byte1 bit 7 == 1, noise disabled):
                        #         j := Current_Envelope_Sliding + Add_to_EorN
                        #         if accumulation flag: Current_Envelope_Sliding := j
                        #         SamEnvP += j  (accumulated across all 3 channels per frame)
                        add_to_eorn_5 = (tick.raw_byte0 >> 1) & 0x1F
                        # Sign-extend from bit 4
                        if add_to_eorn_5 & 0x10:
                            add_to_eorn = add_to_eorn_5 - 0x20
                        else:
                            add_to_eorn = add_to_eorn_5
                        
                        if tick.raw_byte1 & 0x80:
                            # Mixer_Noise=False -> envelope slide path
                            j = ch.current_envelope_sliding + add_to_eorn
                            if tick.envelope_accumulate:
                                ch.current_envelope_sliding = j
                            sam_env_p = (sam_env_p + j) & 0xFF  # VTII: SamEnvP is shortint
                        else:
                            # Mixer_Noise=True -> noise slide path
                            sam_noise = (ch.current_noise_sliding + add_to_eorn) & 0xFF
                            if tick.noise_accumulate:
                                ch.current_noise_sliding = sam_noise
                        
                        # Amplitude slide (byte 0 bit 7 = enable, bit 6 = direction)
                        # Port of VTII trfuncs.pas GetRegisters:
                        #   if Amplitude_Slide_Up then
                        #     if Current_Amplitude_Sliding < 15 then Inc(...)
                        #   else
                        #     if Current_Amplitude_Sliding > -15 then Dec(...)
                        # Accumulator saturates at [-15, +15] on its own, independent
                        # of sample_volume. Effective amplitude is clamped [0, 15] 
                        # AFTER addition.
                        if tick.raw_byte0 & 0x80:
                            if tick.raw_byte0 & 0x40:  # slide up
                                if ch.amp_slide_accum < 15:
                                    ch.amp_slide_accum += 1
                            else:  # slide down
                                if ch.amp_slide_accum > -15:
                                    ch.amp_slide_accum -= 1
                
                # Apply amp slide accumulator to sample volume, then clamp to [0, 15].
                # VTII uses signed 8-bit cast to detect underflow:
                #   Inc(Amplitude, Current_Amplitude_Sliding);
                #   if shortint(Amplitude) < 0 then Amplitude := 0
                #   else if Amplitude > 15 then Amplitude := 15;
                effective_sample_vol = sample_volume + ch.amp_slide_accum
                if effective_sample_vol < 0:
                    effective_sample_vol = 0
                elif effective_sample_vol > 15:
                    effective_sample_vol = 15
                
                tone_period = (base_period + sample_tone_offset + ch.current_ton_sliding) & 0xFFF
                
                # Ton slide logic (effects 1/2/3: gliss up/down, portamento)
                # Port of VTII trfuncs.pas lines 979-994:
                #   if Ton_Slide_Count > 0 then begin
                #     Dec(Ton_Slide_Count);
                #     if Ton_Slide_Count = 0 then begin
                #       Inc(Current_Ton_Sliding, Ton_Slide_Step);
                #       Ton_Slide_Count := Ton_Slide_Delay;
                #       if Ton_Slide_Type = 1 then  // portamento - check for target hit
                #         if ((Ton_Slide_Step < 0) and (Current_Ton_Sliding <= Ton_Slide_Delta)) or
                #            ((Ton_Slide_Step >= 0) and (Current_Ton_Sliding >= Ton_Slide_Delta)) then begin
                #           Note := Slide_To_Note; Ton_Slide_Count := 0; Current_Ton_Sliding := 0;
                #         end;
                #     end;
                #   end;
                if ch.ton_slide_count > 0:
                    ch.ton_slide_count -= 1
                    if ch.ton_slide_count == 0:
                        ch.current_ton_sliding += ch.ton_slide_step
                        ch.ton_slide_count = ch.ton_slide_delay
                        if ch.ton_slide_type == 1:
                            # Portamento: check if we've reached target
                            reached = False
                            if ch.ton_slide_step < 0 and ch.current_ton_sliding <= ch.ton_slide_delta:
                                reached = True
                            elif ch.ton_slide_step >= 0 and ch.current_ton_sliding >= ch.ton_slide_delta:
                                reached = True
                            if reached:
                                ch.note = ch.slide_to_note
                                ch.ton_slide_count = 0
                                ch.current_ton_sliding = 0
                
                # Vibrato on/off (effect 6). Port of VTII lines 1060-1071:
                #   if Current_OnOff > 0 then begin
                #     Dec(Current_OnOff);
                #     if Current_OnOff = 0 then begin
                #       SoundEnabled := not SoundEnabled;
                #       Current_OnOff := SoundEnabled ? OnOff_Delay : OffOn_Delay;
                #     end;
                #   end;
                if ch.current_onoff > 0:
                    ch.current_onoff -= 1
                    if ch.current_onoff == 0:
                        ch.sound_enabled = not ch.sound_enabled
                        ch.current_onoff = ch.onoff_delay if ch.sound_enabled else ch.offon_delay
                
                # Combine master channel volume with sample volume via VT_ lookup
                # (bit-exact port of PT3 algorithm).
                # VT_[(ch.volume << 4) | sample_volume] = final amplitude 0..15
                combined_vol = mod.volume_table[((ch.volume & 0xF) << 4) | (effective_sample_vol & 0xF)]
                
                # Volume in envelope mode: ref PSG keeps the combined volume in lower 
                # nibble even though AY chip ignores it when bit 4 is set. This matches
                # what Vortex Tracker II / AY_Emul do.
                if ch.envelope_enabled and sample_env_on:
                    amp_reg = 0x10 | combined_vol
                else:
                    amp_reg = combined_vol
                
                # Mixer bits
                if not sample_tone_on:
                    mixer |= (1 << ci)   # disable tone
                if not sample_noise_on:
                    mixer |= (1 << (ci + 3))  # disable noise
            
            # Write tone period to AY regs (unless released -> keep previous value)
            if tone_period is not None:
                reg_lo = ci * 2
                ay_regs[reg_lo] = tone_period & 0xFF
                ay_regs[reg_lo + 1] = (tone_period >> 8) & 0x0F
            ay_regs[8 + ci] = amp_reg
            
            # Advance sample/ornament position - VTII quirk (trfuncs.pas lines 1042-1054):
            # these Inc's are INSIDE the `if SoundEnabled` block, not outside. When vibrato
            # (effect 6) toggles SoundEnabled=False, sample position FREEZES for that tick.
            # Without this guard, sample envelope advances too fast during vibrato and
            # amplitude values get misaligned by 1 tick. Note: also skip when released.
            if ch.sound_enabled and not ch.note_released and ch.note is not None:
                # Advance sample position
                if ch.sample_num != 0 and ch.sample_num in mod.samples:
                    samp = mod.samples[ch.sample_num]
                    ch.pos_in_sample += 1
                    if ch.pos_in_sample >= samp.length:
                        ch.pos_in_sample = samp.loop_pos
                
                # Advance ornament position
                if ch.ornament_num != 0 and ch.ornament_num in mod.ornaments:
                    orn = mod.ornaments[ch.ornament_num]
                    ch.pos_in_ornament += 1
                    if ch.pos_in_ornament >= orn['length']:
                        ch.pos_in_ornament = orn['loop_pos']
        
        # Port of VTII trfuncs.pas lines 1117-1119:
        #   RegisterAY.Noise := (Noise_Base + SamNoise) and 31;
        #   RegisterAY.Envelope := EnvP_Base + Cur_Env_Slide + SamEnvP;
        # Here noise_period = Noise_Base (from pattern opcode 0x20-0x3F).
        ay_regs[6] = (noise_period + sam_noise) & 0x1F
        ay_regs[7] = mixer
        # Envelope period: combine env_period (EnvP_Base) with cur_env_slide (effect 9/10)
        # and sam_env_p (accumulated signed 8-bit across channels, from sample byte 1 bit 7).
        # VTII declares SamEnvP as shortint (signed 8-bit) — when the accumulated value
        # ends up >= 0x80, it must be treated as negative (e.g. 0xF0 = -16), otherwise
        # the addition carries into the high byte of the envelope period incorrectly.
        # Bug discovered via EA-xiaomi f1281: ref R12=$00, my R12=$01 when sam_env_p=0xF0
        # caused $0053 + 240 = $0143 instead of $0053 + (-16) = $0043.
        sam_env_p_signed = sam_env_p if sam_env_p < 0x80 else sam_env_p - 0x100
        env_final = (env_period + cur_env_slide + sam_env_p_signed) & 0xFFFF
        ay_regs[11] = env_final & 0xFF
        ay_regs[12] = (env_final >> 8) & 0xFF
        # R13: emit shape only when retriggered this frame; otherwise sentinel.
        # Real PT3 player skips R13 write to AY when this is 0xFF.
        # In the bit-exact reference, 0xFF tells the 6502 player "do not write".
        if env_retrigger_this_frame:
            ay_regs[13] = env_shape
        else:
            ay_regs[13] = 0xFF
        
        # Envelope slide countdown (effects 9, 10). VTII lines 1122-1132:
        #   if Cur_Env_Delay > 0 then begin
        #     Dec(Cur_Env_Delay);
        #     if Cur_Env_Delay = 0 then begin
        #       Cur_Env_Delay := Env_Delay;
        #       Inc(Cur_Env_Slide, Env_Slide_Add);
        #     end;
        #   end;
        if cur_env_delay > 0:
            cur_env_delay -= 1
            if cur_env_delay == 0:
                cur_env_delay = env_delay
                cur_env_slide = (cur_env_slide + env_slide_add) & 0xFFFF
                # Keep signed interpretation for subtraction semantics later
                if cur_env_slide >= 0x8000:
                    cur_env_slide -= 0x10000
        
        psg.write_frame(ay_regs)
        
        # Advance tick
        tick_in_row += 1
        if tick_in_row >= speed:
            tick_in_row = 0
    
    return psg


def apply_row_to_channel(ch: Channel, row: RowState, mod: PT3Module):
    """Apply a decoded row state to the channel's playback state."""
    # Capture pre-trigger Current_Ton_Sliding for PORTM effect 3 with FL>=1
    # (VTII trfuncs.pas line 1146: TS := Chans[Ch].Current_Ton_Sliding).
    # This must happen BEFORE reset_sample_ornament() clears it.
    ch.saved_ton_sliding = ch.current_ton_sliding
    
    if row.note is not None:
        if row.note == 'release':
            # PT3 release: mark channel as released. Tone register keeps its previous
            # value (NOT reset), sample playback continues (natural decay via sample
            # volume envelope), channel master volume is NOT set to 0 (release 
            # semantics rely on the sample itself fading out).
            ch.note_released = True
            ch.sound_enabled = False  # VTII line 1150
        else:
            # Save previous note before overwriting, for portamento (VTII: PrNote)
            ch.prev_note = ch.note
            ch.note = row.note
            ch.note_released = False
            ch.sound_enabled = True   # VTII line 1163
            ch.enabled = True
            # Note triggers sample/ornament reset
            ch.reset_sample_ornament()
    
    if row.sample is not None:
        ch.sample_num = row.sample
    
    # Ornament change reset semantics (VTII trfuncs.pas lines 1177-1197):
    # - If Envelope is in [1..14] (set this row, non-disable): Ornament := row.Ornament,
    #   OrnamentPosition := 0 (line 1182-1183)
    # - Else if Envelope = 15 (explicit disable): same (line 1190-1191)
    # - Else if Ornament != 0: Ornament := row.Ornament, OrnamentPosition := 0 (line 1195-1196)
    # Critically, this applies EVEN WITHOUT a new note. The note trigger reset above
    # (reset_sample_ornament) handles the case with a new note; this handles the case
    # of ornament change while holding the same note.
    # Without this, e.g. CatMan pattern 10 row 1 (--- ..99 = ORN=9, VOL=9, no note) fails
    # because ornament 9's first value (-12) gets skipped: ornament position carries over
    # from previous row, reading Items[pos>0] which is already past the transient.
    if row.ornament is not None:
        ch.ornament_num = row.ornament
        # Reset position (VTII lines 1183, 1191, 1196 — all three branches do this).
        # Only skip reset if note was already triggered this row (reset_sample_ornament
        # already did it) — but that already set pos to 0 anyway, so safe to reset again.
        ch.pos_in_ornament = 0
    elif getattr(row, 'ornament_explicit_zero', False):
        # Explicit ORN=0 opcode (0x40 or 0xF0) -> disable ornament
        ch.ornament_num = 0
        ch.pos_in_ornament = 0
    
    if row.volume is not None:
        ch.volume = row.volume
    
    if row.env_type is not None:
        if row.env_type == 0xF:
            ch.envelope_enabled = False
        else:
            ch.envelope_enabled = True


# -------- Diff PSG files --------
def parse_psg(path: str) -> List[dict]:
    """Parse PSG file and return list of frames (each a dict {reg: val} of changes).
    
    PSG format (bit-exact port of VTII trfuncs.pas Psg_Save_Ostatok / PSG_Save_Registers):
      - Register writes: `reg_index(0-13) value(1 byte)` - change accumulates in current frame
      - $FF: end of current frame (frame appended with accumulated changes, new frame starts)
      - $FE N: equivalent to `N*4` $FF bytes (run-length compression of silent frames)
    
    Common bug to avoid: treating $FE N as "close current + N*4 empty frames" — that adds
    an extra frame boundary that isn't in the VTII encoding. $FE is purely RLE for $FF.
    """
    data = Path(path).read_bytes()
    ptr = 16
    frames = []
    current = {}
    while ptr < len(data):
        b = data[ptr]; ptr += 1
        if b == 0xFF:
            frames.append(current)
            current = {}
        elif b == 0xFE:
            if ptr >= len(data): break
            n = data[ptr]; ptr += 1
            # $FE N = N*4 consecutive $FFs. First one closes current frame,
            # remaining N*4-1 produce empty frames.
            for _ in range(n * 4):
                frames.append(current)
                current = {}
        elif b <= 13:
            if ptr >= len(data): break
            val = data[ptr]; ptr += 1
            current[b] = val
    if current: frames.append(current)
    return frames


def frames_to_cumulative(frames: List[dict]) -> List[List[int]]:
    """Convert PSG frame list to list of [R0..R13] full state per frame."""
    state = [0] * 14
    out = []
    for f in frames:
        for r, v in f.items():
            state[r] = v
        out.append(list(state))
    return out


def compare_psgs(ref_frames: List[List[int]], our_frames: List[List[int]], max_show: int = 15):
    """Compare two cumulative-state frame lists."""
    n = min(len(ref_frames), len(our_frames))
    mismatches = 0
    shown = 0
    for i in range(n):
        r = ref_frames[i]
        o = our_frames[i]
        if r != o:
            mismatches += 1
            if shown < max_show:
                diffs = [(j, r[j], o[j]) for j in range(14) if r[j] != o[j]]
                diff_strs = [f"R{j}={rv:02x}vs{ov:02x}" for j, rv, ov in diffs]
                print(f"  Frame {i:4d}: {', '.join(diff_strs)}")
                shown += 1
    print(f"\nTotal frames compared: {n}")
    print(f"Matching: {n - mismatches}")
    print(f"Mismatched: {mismatches}")
    print(f"Match rate: {(n - mismatches)*100/max(n,1):.1f}%")


if __name__ == '__main__':
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else 'yerzmyey.pt3'
    ref_psg_path = sys.argv[2] if len(sys.argv) > 2 else 'yerzmyey_ref.psg'
    
    mod = PT3Module(path)
    print(f"Loaded {path}: version 3.{mod.version}, {mod.num_pos} positions, speed={mod.initial_speed}")
    print(f"  Samples: {sorted(mod.samples.keys())}")
    print(f"  Ornaments: {sorted(mod.ornaments.keys())}")
    
    ref_frames_raw = parse_psg(ref_psg_path)
    ref_frames = frames_to_cumulative(ref_frames_raw)
    print(f"\nRef PSG: {len(ref_frames)} frames")
    
    # Simulate same number of frames as ref
    psg = simulate(mod, max_frames=len(ref_frames) - 1)
    our_frames = frames_to_cumulative(psg.frames)
    
    print(f"Our sim: {len(our_frames)} frames")
    
    compare_psgs(ref_frames, our_frames, max_show=15)
