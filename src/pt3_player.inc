; =============================================================================
; pt3_player.inc - Shared equates for PT3 Player library
; =============================================================================
; This file is included by player source code (player.s) and by host programs
; that want to call the player via its jump table.
;
; THE LIBRARY IS A PURE SUBROUTINE LIBRARY: host owns the Timer 1 IRQ, host
; calls player_tick via JSR once per frame (50 Hz). All timing, screen, and
; system state is the host's responsibility — the player only writes to the
; AY chip via DigiMuz registers ($FD22/$FD23).
;
; -----------------------------------------------------------------------------
; MINIMAL EXAMPLE — embed this into your own program
; -----------------------------------------------------------------------------
; The 3 public entry points you need:
;   PLAYER_INIT      ($1100) - One-time init: zero state, build note/vol tables.
;   PLAYER_INIT_SONG ($112A) - Load a PT3 file. In: A=hi, X=lo of file address.
;   PLAYER_TICK      ($112D) - Advance by one frame. Call once per 50 Hz IRQ.
;
; A complete embed looks like this (assumes player.bin loaded at $1100,
; PT3 file loaded at $6000):
;
;     .include "pt3_player.inc"
;
;     start:
;             sei
;             sta     RAM_ENABLE      ; $FF3F: ROM off so PT3 visible at $6000+
;             jsr     PLAYER_INIT
;             lda     #>$6000         ; A = hi byte of PT3 address
;             ldx     #<$6000         ; X = lo byte
;             jsr     PLAYER_INIT_SONG
;             ; ... install IRQ handler that JSRs PLAYER_TICK 50 Hz ...
;             cli
;             jmp     *               ; halt; IRQ does the work
;
; For a complete, ready-to-build reference see src/play_template.s
; (template for embedding a specific PT3 via .incbin).
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
PLAYER_BASE         = $1100

; Public entry points (jump table — 3 bytes each, JMP absolute):
PLAYER_INIT         = PLAYER_BASE + $00   ; One-time init (build tables, zero state)
PLAYER_LOAD_PT3     = PLAYER_BASE + $03   ; Load PT3 file; A=addr_lo, X=addr_hi
PLAYER_PLAY         = PLAYER_BASE + $06   ; Tick handler — call from IRQ each frame
PLAYER_STOP         = PLAYER_BASE + $09   ; Mute + halt (preserves position)
PLAYER_REWIND       = PLAYER_BASE + $0C   ; Full reset (position=0, clear state)
PLAYER_IS_PLAYING   = PLAYER_BASE + $0F   ; Returns A=0 (stopped) or A=1 (playing)
PLAYER_IS_SONG_ENDED = PLAYER_BASE + $12  ; Returns A=1 if wrapped this tick
PLAYER_SET_FLAGS    = PLAYER_BASE + $15   ; A=flag bits (bit0=loop_track, bit1=loop_playlist)
PLAYER_BUILD_NOTE_TABLE = PLAYER_BASE + $18
PLAYER_BUILD_VOLUME_TABLE = PLAYER_BASE + $1B
PLAYER_DECODE_ROW   = PLAYER_BASE + $1E
PLAYER_INIT_PATTERN = PLAYER_BASE + $21
PLAYER_DECODE_ALL   = PLAYER_BASE + $24
PLAYER_PLAY_TEST_TONE = PLAYER_BASE + $27
PLAYER_INIT_SONG    = PLAYER_BASE + $2A
PLAYER_TICK         = PLAYER_BASE + $2D

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
; The pattern row decoder uses these ZP aliases (same physical location as
; ZP_TEMP*). They are shared with apply_corrections, which runs during
; player_init and player_build_note_table — never concurrent with the
; pattern decoder.
M5_PTR_LO           = ZP_TEMP_LO      ; working copy of stream pointer
M5_PTR_HI           = ZP_TEMP_HI
M5_OUT_LO           = ZP_TEMP2_LO     ; pointer to row_out_ch<current>
M5_OUT_HI           = ZP_TEMP2_HI

ZP_SCRATCH3         = $E8

; -----------------------------------------------------------------------------
; Flag bits (for PLAYER_SET_FLAGS)
; -----------------------------------------------------------------------------
FLAG_LOOP_TRACK     = %00000001   ; Loop current track forever
FLAG_LOOP_PLAYLIST  = %00000010   ; Song_ended fires for jukebox to advance

; =============================================================================
; End of pt3_player.inc
; =============================================================================
