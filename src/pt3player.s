; =============================================================================
; pt3player.s — standalone Plus/4 PT3 music player (.prg)
; =============================================================================
;
; This is the public-facing standalone player. Unlike play_template.s (which
; bundles a specific PT3 file via .incbin), pt3player.prg expects the user
; to load a PT3 manually via the machine monitor.
;
; USER WORKFLOW
; -------------
;   1. LOAD"PT3PLAYER",8,1     ← load this player into RAM
;   2. (enter machine monitor — TEDMON via SYS 1024 or hardware key)
;   3. L "TUNE.PT3" 08 6000    ← load any PT3 file at $6000 (default)
;   4. G 100D                  ← jump to player start
;      → player auto-detects PAL/NTSC, sets up 50 Hz IRQ, plays from $6000.
;   5. To stop: hit RESET on Plus/4.
;
; CHANGING THE DEFAULT PT3 LOAD ADDRESS
; -------------------------------------
; By default the player expects PT3 at $6000 (8 KB of free RAM, no ROM
; conflict). If you want to load PT3 elsewhere, edit PT3_BASE below and
; rebuild with:
;     python3 tools/build_pt3player.py
;
; AVOID these areas:
;   $0000-$0FFF   zero page + stack + system vectors
;   $1001-$10FF   our BASIC stub + startup code
;   $3000-$47FF   player engine code + BSS
;   $C000-$FCFF   KERNAL ROM (read-only after RESET; ROM gets disabled at
;                 startup but the user may have already loaded into RAM here
;                 expecting ROM to shadow it — confusing, avoid)
;   $FD00-$FDFF   I/O area (DigiMuz card at $FD21-$FD23, PIO etc.)
;   $FF00-$FFFF   TED registers
;
; Recommended PT3 load addresses (pick one and stay consistent):
;   $5000-$5FFF   4 KB  (small files only)
;   $6000-$7FFF   8 KB  (DEFAULT — most PT3 files fit here)
;   $4800-$BFFF   ~30 KB  (large files; works because we disable ROM at startup)
;
; MEMORY MAP
; ----------
;   $1001-$100C   BASIC stub "10 SYS 4109"
;   $100D-$10FF   Startup code + IRQ handler (~250 bytes)
;   $3000-$47FF   player.bin (engine + BSS)
;   $4800-$5FFF   FREE
;   $PT3_BASE...  PT3 file (loaded by user via monitor)
;
; PAL/NTSC AUTO-DETECT
; --------------------
; Plus/4 has different CPU clock rates depending on TV system:
;   PAL  CPU = 886.724 kHz  (17.734475 MHz / 20)
;   NTSC CPU = 894.886 kHz  (14.318181 MHz / 16)
; PT3 modules always assume 50 Hz playback. To get 50 Hz in both regions,
; we need different timer reload values:
;   PAL:  886724 / 50 = 17734.48  → $4546 = 17734  (gives 50.0030 Hz)
;   NTSC: 894886 / 50 = 17897.72  → $45E9 = 17897  (gives 50.0011 Hz)
; The TED bit $FF07 bit 6 reflects PAL (1) or NTSC (0); we read it once at
; startup and pick the right value.
;
; HARDWARE
; --------
; - Auto-detects PAL/NTSC via $FF07 bit 6, picks correct timer for 50 Hz.
; - Requires DigiMuz AY-3-8910 expansion card at $FD21-$FD23.
; - Disables BASIC + KERNAL ROMs during playback (RAM mode at $FF3F).
; - Disables display (uniform border-color screen, no raster-bar artifacts).
;
; =============================================================================

; =============================================================================
; CONFIG — edit and rebuild to change PT3 load address
; =============================================================================
PT3_BASE         = $6000

; -----------------------------------------------------------------------------
; Public player API entry points
; -----------------------------------------------------------------------------
PLAYER_INIT      = $3000
PLAYER_INIT_SONG = $302A
PLAYER_TICK      = $302D

; -----------------------------------------------------------------------------
; TED registers (Plus/4 video/sound/timer chip)
; -----------------------------------------------------------------------------
TED_VIDEO_MODE   = $FF06        ; bit 4 = DEN (Display Enable)
TED_VIDEO_REG    = $FF07        ; bit 6: 1 = PAL, 0 = NTSC
TED_SOUND_VOL    = $FF11        ; bits 0-3 = volume
TIMER1_LO        = $FF00
TIMER1_HI        = $FF01
TED_IRQ_FLAG     = $FF09
TED_IRQ_ENABLE   = $FF0A
RAM_ENABLE       = $FF3F        ; write to enable full-RAM mode (ROM off)
ROM_ENABLE       = $FF3E        ; write to re-enable ROMs

IRQ_VECTOR_LO    = $FFFE
IRQ_VECTOR_HI    = $FFFF

; Timer reload values for 50 Hz PT3 playback.
PAL_TIMER_VAL    = 17734        ; 886724 / 50
NTSC_TIMER_VAL   = 17897        ; 894886 / 50

; =============================================================================
; .prg structure: load address header + BASIC stub + startup code
; =============================================================================
        ; 2-byte PRG load-addr header at file offset 0,1
        .segment "LOADADDRHDR"
        .word   $1001

        ; BASIC stub: "10 SYS 4109" — auto-runs the SYS to start address.
        ; (Works even though user is expected to use monitor + G; the BASIC
        ; stub is just a polite default in case someone types RUN.)
        .segment "BASIC"
        .word   next_line
        .word   10
        .byte   $9E              ; SYS token
        .byte   "4109"           ; target $100D
        .byte   $00
next_line:
        .word   $0000

        .segment "CODE"

; =============================================================================
; start: $100D — entry point
; -----------------------------------------------------------------------------
; This is what BASIC's "SYS 4109" jumps to, and what the user types as
; "G 100D" in the monitor.
; =============================================================================
start:
        sei

        ; ---------------------------------------------------------------------
        ; Disable display (clear bit 4 of $FF06).
        ; This makes the entire screen show as uniform border color, avoiding
        ; the black-and-white raster-bar artifact you'd see otherwise: with
        ; ROM disabled, the character generator points at uninitialized RAM,
        ; so text mode renders garbage as alternating-bit "stripes".
        ; ---------------------------------------------------------------------
        lda     TED_VIDEO_MODE
        and     #%11101111      ; clear DEN (Display Enable)
        sta     TED_VIDEO_MODE

        ; ---------------------------------------------------------------------
        ; Mute TED sound (preserve other bits in $FF11).
        ; Bottom 3 bits of $FF11 = volume; clearing them silences TED sound
        ; without affecting bits 4 (ECM) or 7 (test bit). We don't touch
        ; $FF12 because writing to it inadvertently changes display mode bits
        ; (BMM = bitmap mode bit 5), which we don't want.
        ; ---------------------------------------------------------------------
        lda     TED_SOUND_VOL
        and     #%11111000      ; clear volume bits, keep everything else
        sta     TED_SOUND_VOL

        ; ---------------------------------------------------------------------
        ; Switch all ROMs off (full RAM mode).
        ; This is REQUIRED for two reasons:
        ; (1) Many valid PT3_BASE addresses are in the ROM-shadowed region
        ;     ($8000-$FCFF). With ROM on, reads return ROM, parse fails.
        ; (2) Even when PT3_BASE is at $6000 (which is always RAM), we want
        ;     a consistent memory view for our IRQ handler regardless of
        ;     where user happened to load the PT3.
        ; Writing ANY value to $FF3F enables full RAM mode.
        ; ---------------------------------------------------------------------
        sta     RAM_ENABLE      ; A holds anything; value is irrelevant

        ; ---------------------------------------------------------------------
        ; Initialise the player engine.
        ; ---------------------------------------------------------------------
        jsr     PLAYER_INIT

        ; ---------------------------------------------------------------------
        ; Load PT3 + initialise per-song state.
        ; Args: A = hi byte of PT3_BASE, X = lo byte of PT3_BASE.
        ; ---------------------------------------------------------------------
        lda     #>PT3_BASE
        ldx     #<PT3_BASE
        jsr     PLAYER_INIT_SONG

        ; ---------------------------------------------------------------------
        ; Install our IRQ handler.
        ; ---------------------------------------------------------------------
        lda     #<our_irq
        sta     IRQ_VECTOR_LO
        lda     #>our_irq
        sta     IRQ_VECTOR_HI

        ; ---------------------------------------------------------------------
        ; Auto-detect PAL/NTSC and pick the right Timer 1 reload value.
        ; $FF07 bit 6: 1 = PAL, 0 = NTSC. PT3 always wants 50 Hz playback.
        ; ---------------------------------------------------------------------
        lda     TED_VIDEO_REG
        and     #%01000000      ; isolate bit 6
        beq     @is_ntsc        ; bit 6 clear -> NTSC
@is_pal:
        lda     #<PAL_TIMER_VAL
        sta     TIMER1_LO
        lda     #>PAL_TIMER_VAL
        sta     TIMER1_HI
        jmp     @timer_done
@is_ntsc:
        lda     #<NTSC_TIMER_VAL
        sta     TIMER1_LO
        lda     #>NTSC_TIMER_VAL
        sta     TIMER1_HI
@timer_done:

        ; ---------------------------------------------------------------------
        ; Disable raster IRQ (which BASIC ROM had enabled), enable Timer 1.
        ; $FF0A bit 3 = T1 IRQ enable, bit 1 = raster.
        ; ---------------------------------------------------------------------
        lda     #$08
        sta     TED_IRQ_ENABLE

        ; Acknowledge any pending IRQ flags before re-enabling.
        lda     #$FF
        sta     TED_IRQ_FLAG

        cli

        ; ---------------------------------------------------------------------
        ; Halt loop. IRQ-driven playback continues forever (until RESET).
        ; ---------------------------------------------------------------------
@halt:
        jmp     @halt

; -----------------------------------------------------------------------------
; our_irq - TED Timer 1 IRQ handler. Fires 50 Hz on both PAL and NTSC.
; -----------------------------------------------------------------------------
our_irq:
        pha
        txa
        pha
        tya
        pha

        ; Verify it's a Timer 1 IRQ (bit 3 of $FF09).
        lda     TED_IRQ_FLAG
        and     #$08
        beq     @not_t1

        ; Acknowledge T1 (write 1 to bit 3 to clear).
        lda     #$08
        sta     TED_IRQ_FLAG

        ; Run one frame of the player.
        jsr     PLAYER_TICK

@not_t1:
        pla
        tay
        pla
        tax
        pla
        rti
