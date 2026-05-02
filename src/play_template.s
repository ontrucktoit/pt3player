; =============================================================================
; play_template.s — Plus/4 .prg template for "self-contained PT3 player"
; =============================================================================
;
; This file is a TEMPLATE used by tools/build_play_prg.py to assemble standalone
; .prg files that bundle a specific PT3 module + the player engine into one
; loadable program. The output of `python3 tools/build_play_prg.py FOO.pt3`
; is `build/FOO_play.prg` — a self-contained executable that, when LOADed
; and RUN, plays FOO.pt3 with no further user interaction.
;
; The PT3 file itself is placed at $4000 by the build script — immediately
; past the player's BSS region and on a clean 16-bit boundary. Up to
; ~16 KB of PT3 fits before colliding with the BASIC ROM area at $8000.
;
;
; LAYOUT
; ------
;   $1001-$100C   BASIC stub "10 SYS 4109"
;   $100D-$10FF   Startup code + IRQ handler (~256 bytes max)
;   $1100-$2565   player engine code + RODATA (~5.2 KB)
;   $2566-$28D1   player BSS (allocated at runtime, not in file)
;   $4000-...     PT3 file (embedded by build_play_prg.py)
;
; RUNTIME SEQUENCE
; ----------------
;   1. SEI (mask CPU IRQs while we set everything up)
;   2. Disable display ($FF06 bit 4 = 0) — uniform border-color screen,
;      avoids the black-and-white raster bar artifact that appears when ROM
;      is disabled while text mode tries to read uninitialized RAM as character
;      data.
;   3. Mute TED sound (mask volume bits in $FF11, do not touch other bits).
;   4. Switch vectors to RAM via STA $FF3F (ROM off).
;   5. Call player_init ($1100) — clears 14 AY regs, zeros internal state.
;   6. Call player_init_song with A=hi(PT3_BASE), X=lo(PT3_BASE) ($112A).
;   7. Install IRQ vector $FFFE/$FFFF -> our_irq.
;   8. Auto-detect PAL/NTSC via $FF07 bit 6, set TED Timer 1 reload value
;      so the IRQ fires at exactly 50 Hz on either system.
;   9. Enable Timer 1 IRQ ($FF0A bit 3).
;  10. CLI; halt loop (jmp *).
;
; PAL/NTSC AUTO-DETECT
; --------------------
; Plus/4 has different CPU clock rates depending on TV system:
;   PAL  CPU = 886.724 kHz  (17.734475 MHz / 20)
;   NTSC CPU = 894.886 kHz  (14.318181 MHz / 16)
; PT3 modules always assume 50 Hz playback. To get 50 Hz in both regions,
; we need different timer reload values:
;   PAL:  886724 / 50 = 17734.48  -> $4546 = 17734  (gives 50.0030 Hz, perfect)
;   NTSC: 894886 / 50 = 17897.72  -> $45E9 = 17897  (gives 50.0011 Hz, perfect)
; The TED bit $FF07 bit 6 reflects PAL (1) or NTSC (0); we read it once at
; startup and pick the right value. Cost: ~12 instructions, one-time.
;
; IRQ HANDLER
; -----------
;   - Save A/X/Y on stack.
;   - Verify it's a Timer 1 IRQ (bit 3 of $FF09); skip if not.
;   - Ack T1 IRQ by writing $08 to $FF09 (set bit 3 to clear flag).
;   - JSR player_tick ($112D) to advance the song one frame.
;   - Restore A/X/Y, RTI.
;   - The TED Timer 1 auto-reloads from its initial value, so we don't need
;     to rewrite TIMER1_LO/HI in the handler.
; =============================================================================

DIGIMUZ_REG_SEL = $FD23
DIGIMUZ_DATA_W  = $FD22

PLAYER_INIT      = $1100
PLAYER_INIT_SONG = $112A
PLAYER_TICK      = $112D

PT3_BASE         = $4000

; TED registers
TED_VIDEO_MODE   = $FF06        ; bit 4 = DEN (Display Enable)
TED_VIDEO_REG    = $FF07        ; bit 6 = 1 PAL, 0 NTSC
TED_SOUND_VOL    = $FF11        ; bits 0-3 = volume (0 = mute)
TIMER1_LO        = $FF00
TIMER1_HI        = $FF01
TED_IRQ_FLAG     = $FF09
TED_IRQ_ENABLE   = $FF0A
RAM_ENABLE       = $FF3F
ROM_ENABLE       = $FF3E

IRQ_VECTOR_LO    = $FFFE
IRQ_VECTOR_HI    = $FFFF

; Timer reload values for 50 Hz PT3 playback.
PAL_TIMER_VAL    = 17734        ; 886724 / 50
NTSC_TIMER_VAL   = 17897        ; 894886 / 50

        ; 2-byte PRG load-addr header at file offset 0,1
        .segment "LOADADDRHDR"
        .word   $1001

        .segment "BASIC"
        .word   next_line
        .word   10
        .byte   $9E              ; SYS token
        .byte   "4109"           ; target $100D
        .byte   $00
next_line:
        .word   $0000

        .segment "CODE"

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
        ; This is REQUIRED so we have a consistent memory view: with ROM on,
        ; anything in $8000-$FCFF reads as ROM, not the RAM contents we put
        ; there. Writing ANY value to $FF3F enables full RAM mode.
        ; ---------------------------------------------------------------------
        sta     RAM_ENABLE      ; A holds anything; value is irrelevant

        ; Establish clean player state (zeros all 14 AY regs via DigiMuz).
        jsr     PLAYER_INIT

        ; Load PT3 + initialise per-song state.
        lda     #>PT3_BASE
        ldx     #<PT3_BASE
        jsr     PLAYER_INIT_SONG

        ; Install our IRQ handler at $FFFE/$FFFF.
        lda     #<our_irq
        sta     IRQ_VECTOR_LO
        lda     #>our_irq
        sta     IRQ_VECTOR_HI

        ; Auto-detect PAL/NTSC and pick the right Timer 1 reload value.
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

        ; Disable raster IRQ (which BASIC ROM had enabled), enable Timer 1.
        lda     #$08            ; only T1 enabled
        sta     TED_IRQ_ENABLE

        ; Acknowledge any pending IRQ flags before re-enabling.
        lda     #$FF
        sta     TED_IRQ_FLAG

        cli

        ; Halt loop. IRQ-driven playback continues forever (until RESET).
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

        lda     TED_IRQ_FLAG
        and     #$08
        beq     @not_t1

        lda     #$08
        sta     TED_IRQ_FLAG

        jsr     PLAYER_TICK

@not_t1:
        pla
        tay
        pla
        tax
        pla
        rti
