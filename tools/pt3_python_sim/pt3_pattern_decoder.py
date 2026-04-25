#!/usr/bin/env python3
"""
PT3 Pattern Decoder - faithful Python specification.

This is NOT a port of the French Touch player. It is a from-scratch decoder
that reads PT3 pattern streams and produces Vortex Tracker II compatible TXT
output. The goal is to serve as the reference specification for implementing
a new native 6502 player.

Mechanics of PT3 pattern playback (verified against luchibobra.pt3 + yerzmyey.pt3):

  Each pattern has 3 channels (A, B, C). Each channel is an independent byte
  stream of opcodes and parameters. The three channels play IN PARALLEL at
  50/60 Hz.
  
  Each channel has its own state machine. For each pattern ROW (1/Speed of
  a Hz tick), the channel decrements its own NtSkCn counter:
  
    * If NtSkCn > 0 after decrement: channel SKIPS this row decode.
      The per-tick engine (CHREGS) keeps advancing sample and ornament
      positions independently, so audio continues with evolving
      sample/ornament/envelope modulation. No new opcodes are read.
    
    * If NtSkCn == 0 after decrement: channel DECODES the next row from
      its stream. It reads opcodes until a row-terminator (PD_NOTE /
      PD_REL / PD_FIN). After decode, NtSkCn is reset to NNtSkp.
  
  The SKIP opcode (0xB1 + 1 parameter byte) sets NNtSkp = param. This
  means "skip `param-1` rows after the current one, i.e. decode next row
  every `param` rows from here on".
  
  An NNtSkp of 1 means: decode every row (the default "no skip").
  An NNtSkp of 32 means: decode row 0, then skip 31 rows, then decode row 32,
                          then skip 31 rows, etc.
  
  The total number of rows per pattern is typically 64, but the actual length
  is determined by whatever pattern engine drives the main tick loop.
  Vortex Tracker II patterns are 64 rows by convention.

Pattern stream opcode dispatch (verified via reverse-engineering of PTDECOD):

  0x00        : END_OF_PATTERN (likely; see discussion)
  0x01-0x0F   : SPC_CMD (special command index 1..15; see spec_cmd_params below)
  0x10-0x1F   : PD_ESAM (envelope type + sample; 2-byte opcode)
                byte0 = 0x10+env_type, byte1 = sample flags
  0x20-0x3F   : NOISE (set noise period base; 1-byte)
  0x40-0x4F   : ORN (select ornament 0..15; 1-byte)
  0x50-0xAF   : NOTE (note 0..95, i.e. C-1 to B-8; row terminator)
  0xB0        : ENV_OFF
  0xB1        : SKIP (sets NNtSkp; 2-byte)
  0xB2-0xBF   : SETENV (set envelope shape 2..15; 3-byte, includes envelope period)
  0xC0        : RELEASE (row terminator)
  0xC1-0xCF   : VOL (set volume 1..15; 1-byte)
  0xD0        : END_OF_ROW (explicit row terminator)
  0xD1-0xEF   : SAMPLE (select sample 1..31; 1-byte)
  0xF0-0xFF   : ORN+SAM (select ornament 0..15 + sample; 2-byte)

Special command parameters (consumed AFTER row terminator, in stream order):

  0x00 : NOP (0 bytes) - but this is also "end of pattern" in practice?
  0x01 : GLISS (tone slide down) - 1 byte delay + 2 bytes slide amount
  0x02 : PORTM (portamento) - 1 byte delay + 4 bytes (target note info)
  0x03 : SMPOS (sample position offset) - 1 byte position
  0x04 : ORPOS (ornament position offset) - 1 byte position
  0x05 : VIBRT (vibrato) - 2 bytes (on period, off period)
  0x06 : (reserved / may differ per player) 
  0x07 : (reserved)
  0x08 : ENGLS (envelope glissando) - 3 bytes
  0x09 : DELAY (speed change) - 1 byte new delay
  0x0A-0x0F : (reserved)

This Python decoder is the specification for what the new 6502 player
should do. Bugs should be fixed HERE first, then ported.
"""

import struct
from pathlib import Path
from typing import List, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class SpecCmd:
    """A special command attached to a row."""
    cmd: int              # 0x01..0x0F
    delay: int = 0        # for cmd 1-3, 9: tick delay (a.k.a. autostep)
    param_hi: int = 0     # for cmd 1-5, 9-B: hi nibble of amount
    param_lo: int = 0     # for cmd 1-5, 9-B: lo nibble of amount
    # For some commands the params have different meaning; we keep raw bytes too
    raw_bytes: bytes = b""


@dataclass
class RowState:
    """State captured for a single row of a single channel.
    
    Only fields explicitly set during THIS row's decode are non-None.
    This represents the opcodes the decoder consumed from the stream,
    not the cumulative channel state.
    """
    note: Optional[object] = None    # int (0..95) or 'release' or None
    sample: Optional[int] = None     # 1..31 or None
    env_type: Optional[int] = None   # 1..14, 15=off, or None
    ornament: Optional[int] = None   # 1..15 or None
    # Distinguishes "no opcode this row" (both False) from "explicit ORN=0 / OrSm orn=0" (True).
    # Needed by simulator because ORN=0 means "disable ornament" (different from "keep current").
    ornament_explicit_zero: bool = False
    volume: Optional[int] = None     # 1..15 or None
    spec_cmd: Optional[SpecCmd] = None
    env_period: Optional[int] = None  # 16-bit when SETENV (0xB2-0xBF) used
    noise_period: Optional[int] = None  # 5-bit when NOISE (0x20-0x3F) used


@dataclass
class ChannelStreamState:
    """State of the decoder for one channel."""
    ptr: int = 0                      # current byte offset in file
    nn_skip: int = 1                  # NNtSkp: rows per decode cycle (default 1 = every row)
    skip_counter: int = 1             # NtSkCn: counts down; when 0, decode next row
    end_of_pattern: bool = False
    # Buffer for pending special commands between row terminator and
    # next row's param consumption
    pending_spec: List[int] = field(default_factory=list)


# Bytes consumed by each SPC_CMD after the row terminator
# (determined from PTDECOD analysis; TBD/refinable)
SPC_CMD_PARAM_BYTES = {
    0x01: 3,   # GLISS: delay + 2-byte slide
    0x02: 5,   # PORTM: delay + 4 bytes (target calculations)
    0x03: 1,   # SMPOS: 1-byte position
    0x04: 1,   # ORPOS: 1-byte position
    0x05: 2,   # VIBRT: on_period + off_period
    0x06: 0,
    0x07: 0,
    0x08: 3,   # ENGLS: delay + 2-byte slide
    0x09: 1,   # DELAY (speed): 1 byte
    0x0A: 0, 0x0B: 0, 0x0C: 0, 0x0D: 0, 0x0E: 0, 0x0F: 0,
}


NOTE_NAMES = ['C-', 'C#', 'D-', 'D#', 'E-', 'F-', 'F#', 'G-', 'G#', 'A-', 'A#', 'B-']


def note_to_str(note) -> str:
    """Vortex Tracker II note string: 'C-4', '---' for release, '...' for empty."""
    if note is None:
        return '---'
    if note == 'release':
        return 'R--'
    # PT3 notes: 0 = C-1, 95 = B-8 (96 notes, 8 octaves)
    octave = 1 + note // 12
    return f"{NOTE_NAMES[note % 12]}{octave}"


def sample_to_str(s) -> str:
    if s is None:
        return '.'
    if 1 <= s <= 9:
        return str(s)
    if 10 <= s <= 31:
        return chr(ord('A') + s - 10)
    return '?'


def hex_or_dot(v) -> str:
    return '.' if v is None else f"{v:X}"


def format_env_period(val) -> str:
    """Format envelope period as 4 hex chars with leading zeros as dots (Vortex style)."""
    if val is None:
        return "...."
    s = f"{val:04X}"
    out = ""
    leading = True
    for ch in s:
        if leading and ch == '0':
            out += '.'
        else:
            leading = False
            out += ch
    return out


def format_row_channel(row: RowState) -> str:
    """Format one channel's row as 'NNN SVEO DPPP' (13 chars)."""
    note = note_to_str(row.note)
    sample = sample_to_str(row.sample)
    env = hex_or_dot(row.env_type)
    orn = hex_or_dot(row.ornament)
    vol = hex_or_dot(row.volume)
    
    if row.spec_cmd:
        cmd = f"{row.spec_cmd.cmd:X}"
        dly = f"{row.spec_cmd.delay:X}" if row.spec_cmd.delay else '.'
        phi = f"{row.spec_cmd.param_hi:X}" if row.spec_cmd.param_hi else '.'
        plo = f"{row.spec_cmd.param_lo:X}" if row.spec_cmd.param_lo else '.'
    else:
        cmd, dly, phi, plo = '.', '.', '.', '.'
    
    return f"{note} {sample}{env}{orn}{vol} {cmd}{dly}{phi}{plo}"


# -------------------------------------------------------------------
# Per-channel decoder
# -------------------------------------------------------------------

def decode_next_row(data: bytes, state: ChannelStreamState) -> Optional[RowState]:
    """Decode the next row for a channel from its stream.
    
    Returns RowState with the opcodes consumed for this row, or None if the
    pattern has ended (end-of-pattern marker 0x00 encountered).
    
    Leaves state.ptr pointing at the byte after the last consumed (including
    special command parameters).
    """
    row = RowState()
    pending_specs: List[int] = []
    safety = 128
    row_done = False
    
    while not row_done and safety > 0:
        safety -= 1
        if state.ptr >= len(data):
            state.end_of_pattern = True
            return None
        
        b = data[state.ptr]
        state.ptr += 1
        
        if b == 0x00:
            # END_OF_PATTERN marker (our working hypothesis from luchibobra analysis)
            state.end_of_pattern = True
            if not pending_specs and row.note is None and row.sample is None \
               and row.env_type is None and row.ornament is None \
               and row.volume is None:
                # Truly empty - this is just the terminator
                return None
            # Rare case: some opcodes read before 0x00 - emit the row, THEN end
            break
        elif 0x01 <= b <= 0x0F:
            # SPC_CMD - record, will consume params after row terminator
            pending_specs.append(b)
        elif 0x10 <= b <= 0x1F:
            # PD_ESAM: envelope type + envelope period + sample
            # 
            # SPEC AMBIGUITY (important for new player implementation):
            # 
            # Vince Weaver's README_pt3.txt says 4 bytes after opcode:
            #     env_period_hi, env_period_lo, env_delay, sample
            # 
            # BUT AY_emul and the French Touch player's PTDECOD both use only 3 bytes:
            #     env_period_hi, env_period_lo, sample     (no env_delay!)
            # 
            # Testing against Vortex Tracker II TXT export of yerzmyey.pt3 (PT3.7):
            #   * 3-byte interpretation = 100% match (1408/1408 rows)
            #   * 4-byte interpretation = breaks (samples decode as garbage)
            # 
            # WORKING THEORY:
            # PTDECOD in the French Touch player skips the envelope delay byte
            # regardless of PT3 version. We use 3 bytes here to match Vortex
            # Tracker II output exactly. When implementing the new 6502 player,
            # remember that Vince's spec claims 4 bytes for $11-$1F -- if we
            # ever encounter a PT3 file where decoding breaks, this is the
            # first place to look. For now, trust what AY_emul and Vortex
            # Tracker II do over what Vince's doc says.
            #
            # OPCODE $10 SPECIAL CASE: per VTII trfuncs.pas line 2167-2168,
            #   "if opcode = $10 then Envelope := 15" (envelope explicit OFF),
            # and it does NOT read an env_period — only 1 byte follows for sample.
            # Without this case, a row that says "disable envelope" silently keeps
            # prior envelope state, causing stale envelope enable bits in R8-R10.
            # Discovered via Avatar PT3.4 pattern 3 row 34.
            env_t = b - 0x10
            if env_t == 0:
                # $10: envelope explicit OFF, no env_period, just sample byte
                row.env_type = 0xF
            else:
                row.env_type = env_t
                if state.ptr + 1 >= len(data): break
                # Envelope period: 2 bytes BIG-ENDIAN
                hi = data[state.ptr]; state.ptr += 1
                lo = data[state.ptr]; state.ptr += 1
                row.env_period = (hi << 8) | lo
            # Sample byte (divided by 2 to get sample index)
            if state.ptr >= len(data): break
            samp_byte = data[state.ptr]
            state.ptr += 1
            row.sample = samp_byte >> 1
        elif 0x20 <= b <= 0x3F:
            row.noise_period = b - 0x20
        elif 0x40 <= b <= 0x4F:
            orn = b - 0x40
            if orn == 0:
                # Special: ORN=0 means "disable ornament" + envelope off
                # (Vortex rule: "0th ornament can be set only with envtype or off")
                if row.env_type is None:
                    row.env_type = 0xF
                row.ornament_explicit_zero = True
                # row.ornament stays None so Vortex TXT displays '.'
            else:
                row.ornament = orn
        elif 0x50 <= b <= 0xAF:
            # NOTE - row terminator
            row.note = b - 0x50
            row_done = True
        elif b == 0xB0:
            row.env_type = 0xF  # envelope off -> 'F'
        elif b == 0xB1:
            # SKIP opcode: next byte sets NNtSkp
            if state.ptr >= len(data): break
            state.nn_skip = data[state.ptr]
            state.ptr += 1
            # Note: skip opcode does NOT terminate the row. Continue reading.
        elif 0xB2 <= b <= 0xBF:
            # SETENV: envelope shape (1..E = 14) + 2-byte envelope period
            # Opcode value 0xB2 maps to shape 1, 0xBF to shape E (14).
            # Formula: env_type = (opcode & 0x0F) - 1
            row.env_type = (b & 0x0F) - 1
            if state.ptr + 1 >= len(data): break
            # Envelope period is stored BIG-endian in PT3 (hi byte first)
            hi = data[state.ptr]; state.ptr += 1
            lo = data[state.ptr]; state.ptr += 1
            row.env_period = (hi << 8) | lo
        elif b == 0xC0:
            row.note = 'release'
            row_done = True
        elif 0xC1 <= b <= 0xCF:
            row.volume = b - 0xC0
        elif b == 0xD0:
            # END_OF_ROW explicit
            row_done = True
        elif 0xD1 <= b <= 0xEF:
            row.sample = b - 0xD0
        elif 0xF0 <= b <= 0xFF:
            # ORN+SAM: orn + next byte is sample
            orn = b - 0xF0
            row.env_type = 0xF  # ORN+SAM implicitly sets envelope off
            if orn != 0:
                row.ornament = orn
            else:
                # orn=0: disable ornament. row.ornament stays None so
                # Vortex TXT displays '.', but simulator needs to know.
                row.ornament_explicit_zero = True
            if state.ptr >= len(data): break
            samp_byte = data[state.ptr]
            state.ptr += 1
            row.sample = samp_byte >> 1
    
    # After the row terminator, consume parameters for any pending SPC_CMDs
    # (Spec commands can chain: multiple commands in one row, each with own params)
    if pending_specs:
        # In PTDECOD, specs are dispatched in REVERSE order (stack LIFO), but
        # parameter consumption is in stream order. We only keep the LAST
        # spec_cmd for now (typical Vortex Tracker II single command per row).
        # TODO: expand to support multiple commands if needed.
        for cmd in pending_specs:
            nparams = SPC_CMD_PARAM_BYTES.get(cmd, 0)
            if state.ptr + nparams > len(data):
                break
            params = data[state.ptr:state.ptr+nparams]
            state.ptr += nparams
            # Record the last (or only) spec cmd for this row
            spec = SpecCmd(cmd=cmd, raw_bytes=bytes(params))
            # Parse param interpretation based on cmd
            if cmd in (0x01, 0x02, 0x08):
                # GLISS/PORTM/ENGLS: delay + multi-byte amount
                # For GLISS/ENGLS: 1-byte delay + 2-byte amount (signed)
                # For PORTM: 1-byte delay + 4 more bytes (we just record delay for TXT)
                if len(params) >= 1:
                    spec.delay = params[0]
                if cmd in (0x01, 0x08) and len(params) >= 3:
                    amount = params[1] | (params[2] << 8)
                    spec.param_hi = (amount >> 4) & 0xF
                    spec.param_lo = amount & 0xF
            elif cmd in (0x03, 0x04):
                # SMPOS/ORPOS: single position byte
                if len(params) >= 1:
                    spec.param_hi = (params[0] >> 4) & 0xF
                    spec.param_lo = params[0] & 0xF
            elif cmd == 0x05:
                # VIBRT: on_period, off_period
                if len(params) >= 1:
                    spec.param_hi = params[0] & 0xF
                if len(params) >= 2:
                    spec.param_lo = params[1] & 0xF
            elif cmd == 0x09:
                # DELAY: 1 byte
                if len(params) >= 1:
                    spec.param_hi = (params[0] >> 4) & 0xF
                    spec.param_lo = params[0] & 0xF
            row.spec_cmd = spec  # keep last one
    
    # After row decode, reset skip_counter from nn_skip
    state.skip_counter = state.nn_skip
    return row


def decode_pattern(data: bytes, ch_ptrs: Tuple[int, int, int], num_rows: int = 64) -> List[List[Optional[RowState]]]:
    """Decode a pattern into a list of rows.
    
    Each row is [ch_a_state, ch_b_state, ch_c_state]. If a channel is
    skipping a row (no new decode), the RowState is an empty (all-None)
    RowState representing 'same as previous opcodes, just a skip row'.
    """
    channels = [ChannelStreamState(ptr=p) for p in ch_ptrs]
    rows: List[List[Optional[RowState]]] = []
    
    for row_idx in range(num_rows):
        row_result: List[Optional[RowState]] = []
        for ch in channels:
            if ch.end_of_pattern:
                row_result.append(RowState())  # empty after pattern ended
                continue
            # Decrement skip counter
            ch.skip_counter -= 1
            if ch.skip_counter > 0:
                # Skip decoding; row shows "no new opcodes"
                row_result.append(RowState())
                continue
            # Decode next row for this channel
            rs = decode_next_row(data, ch)
            if rs is None:
                # End of pattern
                row_result.append(RowState())
                continue
            row_result.append(rs)
        rows.append(row_result)
    
    return rows


# -------------------------------------------------------------------
# Full module decoder
# -------------------------------------------------------------------

def decode_module_patterns(path: str) -> dict:
    """Decode all patterns and return a dict {pattern_num: [rows]}."""
    data = Path(path).read_bytes()
    pat_ptr = struct.unpack('<H', data[0x67:0x69])[0]
    num_pos = data[0x65]
    positions = list(data[0xC9:0xC9+num_pos])
    pat_nums = sorted(set(p//3 for p in positions))
    
    result = {}
    for pn in pat_nums:
        base = pat_ptr + pn * 6
        ch_a = struct.unpack('<H', data[base:base+2])[0]
        ch_b = struct.unpack('<H', data[base+2:base+4])[0]
        ch_c = struct.unpack('<H', data[base+4:base+6])[0]
        result[pn] = decode_pattern(data, (ch_a, ch_b, ch_c))
    return result


def format_pattern_vortex(pattern_num: int, rows: List[List[Optional[RowState]]]) -> List[str]:
    """Format a pattern as Vortex Tracker II TXT lines."""
    lines = [f"[Pattern{pattern_num}]"]
    for row_idx, row in enumerate(rows):
        # Envelope period at start of row (only emitted if env_period was set this row on any channel)
        env_period_this_row = None
        noise_this_row = None
        ch_strs = []
        for ch_state in row:
            if ch_state is None:
                ch_strs.append("--- .... ....")
                continue
            ch_strs.append(format_row_channel(ch_state))
            if ch_state.env_period is not None and env_period_this_row is None:
                env_period_this_row = ch_state.env_period
            if ch_state.noise_period is not None and noise_this_row is None:
                noise_this_row = ch_state.noise_period
        
        env_str = format_env_period(env_period_this_row)
        noise_str = f"{noise_this_row:02X}" if noise_this_row is not None else ".."
        lines.append(f"{env_str}|{noise_str}|" + "|".join(ch_strs))
    return lines


if __name__ == '__main__':
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else 'yerzmyey.pt3'
    patterns = decode_module_patterns(path)
    
    for pn, rows in patterns.items():
        for line in format_pattern_vortex(pn, rows):
            print(line)
        print()
