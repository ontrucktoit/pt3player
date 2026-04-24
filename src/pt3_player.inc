; =============================================================================
; pt3_player.inc - Shared equates for PT3 Player library
; =============================================================================
; This file is included by player source code (player.s) and by host programs
; (main.asm) that want to call the player via its jump table.
;
; The library is a pure subroutine library: host owns Timer 1 IRQ, calls
; player_play via JSR each frame (50 Hz PAL or 60 Hz NTSC).
; =============================================================================

; -----------------------------------------------------------------------------
; DigiMuz AY-3-8910 expansion card
; -----------------------------------------------------------------------------
DIGIMUZ_DATA_R      = $FD21         ; AY data read  (we don't use this)
DIGIMUZ_DATA_W      = $FD22         ; AY data write
DIGIMUZ_REG_SEL     = $FD23         ; AY register select (latch)

; AY-3-8910 register indices (for clarity)
AY_R0_TONE_A_LO     = 0             ; Channel A tone period low  (12-bit total)
AY_R1_TONE_A_HI     = 1             ; Channel A tone period high (4 bits)
AY_R2_TONE_B_LO     = 2
AY_R3_TONE_B_HI     = 3
AY_R4_TONE_C_LO     = 4
AY_R5_TONE_C_HI     = 5
AY_R6_NOISE         = 6             ; Noise period (5 bits)
AY_R7_MIXER         = 7             ; Mixer control
                                    ;   bits 0-2 = tone enable !A,!B,!C (0=on)
                                    ;   bits 3-5 = noise enable !A,!B,!C
                                    ;   bits 6-7 = I/O direction (unused)
AY_R8_AMP_A         = 8             ; Ch A amplitude: bit4=env mode, bits0-3=vol
AY_R9_AMP_B         = 9
AY_R10_AMP_C        = 10
AY_R11_ENV_LO       = 11            ; Envelope period low
AY_R12_ENV_HI       = 12            ; Envelope period high
AY_R13_ENV_SHAPE    = 13            ; Envelope shape (writing restarts envelope!)

; -----------------------------------------------------------------------------
; Player library base address and jump table offsets
; -----------------------------------------------------------------------------
PLAYER_BASE         = $3000

; Public entry points (jump table — 3 bytes each, JMP absolute):
PLAYER_INIT         = PLAYER_BASE + $00   ; One-time init (build tables, zero state)
PLAYER_LOAD_PT3     = PLAYER_BASE + $03   ; Load PT3 file; A=addr_lo, X=addr_hi
PLAYER_PLAY         = PLAYER_BASE + $06   ; Tick handler — call from IRQ each frame
PLAYER_STOP         = PLAYER_BASE + $09   ; Mute + halt (preserves position)
PLAYER_REWIND       = PLAYER_BASE + $0C   ; Full reset (position=0, clear state)
PLAYER_IS_PLAYING   = PLAYER_BASE + $0F   ; Returns A=0 (stopped) or A=1 (playing)
PLAYER_IS_SONG_ENDED = PLAYER_BASE + $12  ; Returns A=1 if wrapped this tick
PLAYER_SET_FLAGS    = PLAYER_BASE + $15   ; A=flag bits (bit0=loop_track, bit1=loop_playlist)

; -----------------------------------------------------------------------------
; Zero page allocation ($D8-$E8, 17 bytes safe per SVS Ultimate Map v2.2)
; -----------------------------------------------------------------------------
ZP_STREAM_A_LO      = $D8
ZP_STREAM_A_HI      = $D9
ZP_STREAM_B_LO      = $DA
ZP_STREAM_B_HI      = $DB
ZP_STREAM_C_LO      = $DC
ZP_STREAM_C_HI      = $DD
ZP_SAMPLE_BASE_LO   = $DE
ZP_SAMPLE_BASE_HI   = $DF
ZP_ORN_BASE_LO      = $E0
ZP_ORN_BASE_HI      = $E1
ZP_TEMP_LO          = $E2
ZP_TEMP_HI          = $E3
ZP_TEMP2_LO         = $E4
ZP_TEMP2_HI         = $E5
ZP_SCRATCH1         = $E6
ZP_SCRATCH2         = $E7
ZP_SCRATCH3         = $E8

; -----------------------------------------------------------------------------
; Flag bits (for PLAYER_SET_FLAGS)
; -----------------------------------------------------------------------------
FLAG_LOOP_TRACK     = %00000001   ; Loop current track forever
FLAG_LOOP_PLAYLIST  = %00000010   ; Song_ended fires for jukebox to advance

; =============================================================================
; End of pt3_player.inc
; =============================================================================
