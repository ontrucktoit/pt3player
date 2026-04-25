#!/usr/bin/env python3
"""
PT3 sample decoder.

The sample-byte layout decoded here matches what Bulba documents in his
PT3 player source and what Vortex Tracker II's `trfuncs.pas` reads from
sample data. This implementation is independent (no line-by-line port);
it just reads the same bit fields, because there is only one wire format.

Released under MIT — see LICENSE at the repository root, and
docs/THIRD_PARTY_NOTICES.md for the broader attribution context.

Sample format in binary:
  [loop_pos : 1B]
  [length   : 1B]
  [tick_0   : 4B]
  [tick_1   : 4B]
  ...
  [tick_N-1 : 4B]

Where each tick is 4 bytes:
  byte[0]:
    bit 0        : 1 = Envelope OFF for this tick
    bits 1-5     : signed 5-bit noise offset (sign-extend from bit 5)
    bits 6-7     : accumulator flags (TBD - see Bulba spec)
  
  byte[1]:
    bit 7        : 1 = Tone ACCUMULATE mode  (the "_" in TXT after tone offset)
                   OR
                   Part of the tone flags
    bits 4-6     : TBD
    bit 3        : 1 = Tone OFF
    bit 2        : ??? 
    bit 1        : ???
    bit 0        : 1 = Noise OFF
    
    Actually looking at high nibble only:
      0x0 = TN on       (T=on, N=on)
      0x1 = tN off+on   (T=off, N=on)  -- hmm contradicts bit 3 interpretation
      0x8 = Tn on+off   (T=on, N=off)
      0x9 = tn off+off  (T=off, N=off)
    
    So high nibble bits:
      bit 3 of nibble (0x8): set when T is OFF (tone disabled)
      bit 0 of nibble (0x1): set when N is OFF (noise disabled)
      bits 1,2 of nibble: not used in this song
    
    And low nibble of byte[1] = volume (4-bit, 0-F)
  
  byte[2-3]: signed 16-bit tone offset (little-endian)
             (PT3 spec says 12-bit, but here it's stored as 16-bit signed)

TBD items (need more data or code analysis):
  - The accumulator "_" in TXT: when does it appear vs "+" ?
    In all ticks we've examined, the TXT shows "_" at end. Need to find 
    a sample with "+" (fixed mode, no accumulation) to identify the bit.
  - byte[0] bits 6-7 usage
"""

import struct
from pathlib import Path
from typing import List, NamedTuple


class SampleTick(NamedTuple):
    tone_on: bool
    noise_on: bool
    envelope_on: bool
    tone_offset: int      # signed 16-bit
    noise_offset: int     # signed 5-bit (-16..+15)  [kept for TXT output compatibility]
    volume: int           # 0-15
    # Raw binary bytes from the sample tick - needed by simulator for exact AY reg writes
    raw_byte0: int = 0    # encodes noise period (bits 1-5), envelope slide, amp slide
    raw_byte1: int = 0    # encodes T/N mixer enables, accumulate flags, envelope slide enable
    # Accumulator flags (decoded from byte 1)
    tone_accumulate: bool = False
    noise_accumulate: bool = False
    envelope_accumulate: bool = False


class Sample:
    def __init__(self, loop_pos: int, length: int, ticks: List[SampleTick]):
        self.loop_pos = loop_pos
        self.length = length
        self.ticks = ticks


def decode_sample(data: bytes, offset: int, size: int) -> Sample:
    """Decode a sample starting at file offset. `size` is total bytes (header + ticks)."""
    loop_pos = data[offset]
    length = data[offset + 1]
    expected_size = 2 + length * 4
    if size != expected_size:
        raise ValueError(f"Sample at {offset:#x}: size mismatch, got {size}, expected {expected_size}")
    
    ticks = []
    for i in range(length):
        ts = offset + 2 + i * 4
        b0, b1, b2, b3 = data[ts], data[ts+1], data[ts+2], data[ts+3]
        
        # byte[0]
        envelope_off = bool(b0 & 0x01)
        noise_offset_5 = (b0 >> 1) & 0x1F
        # Sign-extend from bit 4 of the 5-bit value
        if noise_offset_5 >= 0x10:
            noise_offset = noise_offset_5 - 0x20
        else:
            noise_offset = noise_offset_5
        
        # byte[1]
        hi_nibble = (b1 >> 4) & 0xF
        # Verified against yerzmyey.txt:
        #   hi=0x0 -> TN on; hi=0x1 -> tN (T off); hi=0x8 -> Tn (N off); hi=0x9 -> tn (both off)
        tone_off = bool(hi_nibble & 0x1)
        noise_off = bool(hi_nibble & 0x8)
        volume = b1 & 0x0F
        
        # bytes[2:4] - signed 16-bit tone offset
        tone_u16 = b2 | (b3 << 8)
        if tone_u16 >= 0x8000:
            tone_offset = tone_u16 - 0x10000
        else:
            tone_offset = tone_u16
        
        ticks.append(SampleTick(
            tone_on = not tone_off,
            noise_on = not noise_off,
            envelope_on = not envelope_off,
            tone_offset = tone_offset,
            noise_offset = noise_offset,
            volume = volume,
            raw_byte0 = b0,
            raw_byte1 = b1,
            # Accumulator flags per VTII trfuncs.pas lines 2404,2414:
            #   Ton_Accumulation := byte[1] and $40 <> 0
            #   Envelope_or_Noise_Accumulation := byte[1] and $20 <> 0
            tone_accumulate = bool(b1 & 0x40),
            envelope_accumulate = bool(b1 & 0x20),
            noise_accumulate = bool(b1 & 0x20),  # same bit, semantics depends on Mixer_Noise
        ))
    
    return Sample(loop_pos, length, ticks)


def format_sample_tick_vortex(tick: SampleTick, is_loop_point: bool) -> str:
    """Format a sample tick in Vortex Tracker II TXT format.
    
    Example: "TnE +200_ +00_ F_  L"
    """
    # Flags: TNE uppercase = on, lowercase = off
    t_flag = 'T' if tick.tone_on else 't'
    n_flag = 'N' if tick.noise_on else 'n'
    e_flag = 'E' if tick.envelope_on else 'e'
    
    # Tone offset: signed 12-bit in hex (Vortex displays 12-bit even though stored as 16-bit)
    # Format: "+NNN_" or "-NNN_"
    t = tick.tone_offset
    if t >= 0:
        tone_str = f"+{t & 0xFFF:03X}"
    else:
        tone_str = f"-{(-t) & 0xFFF:03X}"
    # Accumulator flag trailing (TBD which bit)
    tone_str += "_"
    
    # Noise offset: signed 5-bit in hex 2-digit "+NN" or "-NN"
    n = tick.noise_offset
    if n >= 0:
        noise_str = f"+{n:02X}"
    else:
        noise_str = f"-{(-n):02X}"
    noise_str += "_"
    
    # Volume: 1 hex digit + "_"
    vol_str = f"{tick.volume:X}_"
    
    line = f"{t_flag}{n_flag}{e_flag} {tone_str} {noise_str} {vol_str}"
    if is_loop_point:
        line += " L"
    return line


def format_sample(sample: Sample) -> List[str]:
    """Format full sample as Vortex TXT lines."""
    lines = []
    for i, tick in enumerate(sample.ticks):
        is_loop = (i == sample.loop_pos)
        lines.append(format_sample_tick_vortex(tick, is_loop))
    return lines


def decode_all_samples(data: bytes, sample_ptrs: list) -> dict:
    """Decode all non-zero samples. Returns dict {sample_idx: Sample}."""
    # Each sample is self-describing: byte[0]=loop_pos, byte[1]=length.
    # Total size = 2 + length*4. We trust this over pointer distance because
    # some PT3 files have "gaps" between samples (padding) or non-sorted ptrs.
    samples = {}
    for idx, ptr in enumerate(sample_ptrs):
        if ptr == 0:
            continue
        if ptr + 2 > len(data):
            continue
        length = data[ptr + 1]
        size = 2 + length * 4
        if ptr + size > len(data):
            continue
        samples[idx] = decode_sample(data, ptr, size)
    return samples


if __name__ == '__main__':
    import sys, re
    from pathlib import Path
    
    path = sys.argv[1] if len(sys.argv) > 1 else 'yerzmyey.pt3'
    d = Path(path).read_bytes()
    samp_ptrs = [struct.unpack('<H', d[0x69 + i*2:0x69 + i*2 + 2])[0] for i in range(32)]
    
    samples = decode_all_samples(d, samp_ptrs)
    
    # Verify against Vortex TXT
    if Path(path).with_suffix('.txt').exists():
        txt_path = Path(path).with_suffix('.txt')
    else:
        # Try the uploads version
        txt_path = Path(path).with_suffix('.txt')
    
    if txt_path.exists():
        txt = txt_path.read_text()
        # Parse expected samples from TXT
        expected = {}
        current = None
        for line in txt.splitlines():
            m = re.match(r'\[Sample(\d+)\]', line)
            if m:
                current = int(m.group(1))
                expected[current] = []
            elif current is not None and line.strip() and not line.startswith('['):
                expected[current].append(line.strip())
        
        # Compare
        total_ticks = 0
        mismatches = 0
        for idx, sample in samples.items():
            if idx not in expected:
                continue
            our_lines = format_sample(sample)
            exp_lines = expected[idx]
            for i, (ours, theirs) in enumerate(zip(our_lines, exp_lines)):
                total_ticks += 1
                if ours != theirs:
                    mismatches += 1
                    if mismatches < 10:
                        print(f"S{idx} t{i}: MISMATCH")
                        print(f"  ours:   {ours!r}")
                        print(f"  theirs: {theirs!r}")
        print(f"\nTotal ticks compared: {total_ticks}")
        print(f"Mismatches: {mismatches}")
        if mismatches == 0:
            print("ALL SAMPLES MATCH Vortex TXT exactly.")
    else:
        # Just print
        for idx, sample in sorted(samples.items()):
            print(f"[Sample{idx}]")
            for line in format_sample(sample):
                print(line)
            print()
