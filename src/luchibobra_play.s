; =============================================================================
; luchibobra_play.s — standalone Plus/4 .prg that plays luchibobra.pt3
;                     bit-exact via M6 player engine + TED Timer 1 IRQ
; =============================================================================
; Layout:
;   $1001-$100C   BASIC stub "10 SYS 4109"
;   $100D-$10FF   Startup code + IRQ handler (~256 bytes max)
;   $3000-$4FFF   player.bin (M6 jump table + engine + BSS + tables)
;   $8000-$88BB   luchibobra.pt3 (2236 bytes, embedded via .incbin)
;
; Runtime:
;   1. Silence TED sound ($FF11/$FF12).
;   2. SEI.
;   3. Call player_init ($3000) and player_init_song with A=$80 X=$00 ($302A).
;   4. Switch vectors to RAM via STA $FF3F.
;   5. Install IRQ vector $FFFE/$FFFF -> our_irq.
;   6. Setup TED Timer 1 ($FF00/$FF01) for PAL 50 Hz: 17734 cycles
;      (CPU clock 886.7 kHz / 50 Hz / 1 = 17734).
;   7. Enable Timer 1 IRQ ($FF0A bit 3).
;   8. CLI; infinite loop (HALT - jmp *).
;
; IRQ handler:
;   - Save A/X/Y on stack.
;   - JSR player_tick ($302D).
;   - Ack T1 IRQ by writing $08 to $FF09 (set bit to clear flag).
;   - Reload Timer 1 ($FF00/$FF01).
;   - Restore A/X/Y, RTI.
;
; Note: Plus/4 single-clock cycles run at ~886.7 kHz on PAL, ~894.9 kHz on NTSC.
; For PAL: 886724 / 50 = 17734.48. We use $4546 = 17734.
; (NTSC would use 14916; we ship a PAL-only build for YAPE testing.)
; =============================================================================

DIGIMUZ_REG_SEL = $FD23
DIGIMUZ_DATA_W  = $FD22

PLAYER_INIT      = $3000
PLAYER_INIT_SONG = $302A
PLAYER_TICK      = $302D

PT3_BASE         = $8000

TIMER1_LO        = $FF00
TIMER1_HI        = $FF01
TED_IRQ_FLAG     = $FF09
TED_IRQ_ENABLE   = $FF0A
RAM_ENABLE       = $FF3F
ROM_ENABLE       = $FF3E

IRQ_VECTOR_LO    = $FFFE
IRQ_VECTOR_HI    = $FFFF

PAL_TIMER_VAL    = 17734        ; 886724 / 50

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

        ; Silence TED sound (in case BASIC left voice running)
        lda     #0
        sta     $FF11
        sta     $FF12

        ; Establish clean player state (zeros all 14 AY regs via DigiMuz)
        jsr     PLAYER_INIT

        ; Load PT3 + initialise per-song state.
        ; Args: A = hi byte of pt3 base, X = lo byte.
        lda     #>PT3_BASE
        ldx     #<PT3_BASE
        jsr     PLAYER_INIT_SONG

        ; Switch vectors to RAM so we can override $FFFE/$FFFF.
        sta     RAM_ENABLE       ; any write -> RAM mode for $8000+

        ; Install our IRQ handler at $FFFE/$FFFF.
        lda     #<our_irq
        sta     IRQ_VECTOR_LO
        lda     #>our_irq
        sta     IRQ_VECTOR_HI

        ; Setup TED Timer 1 for ~50 Hz PAL.
        ; Plus/4 timers count down to 0, then trigger IRQ and reload from
        ; the same value (auto-reload). Period = (PAL_TIMER_VAL+1) cycles.
        lda     #<PAL_TIMER_VAL
        sta     TIMER1_LO
        lda     #>PAL_TIMER_VAL
        sta     TIMER1_HI

        ; Disable raster IRQ (which the BASIC ROM had enabled), enable Timer 1.
        ; $FF0A bit 3 = T1, bit 1 = raster.
        lda     #$08             ; only T1 enabled
        sta     TED_IRQ_ENABLE

        ; Acknowledge any pending IRQ flags before re-enabling
        lda     #$FF
        sta     TED_IRQ_FLAG

        cli

        ; Halt loop. IRQ-driven playback continues forever.
@halt:
        jmp     @halt

; -----------------------------------------------------------------------------
; our_irq - TED Timer 1 IRQ handler. Fires ~50 times per second on PAL.
; -----------------------------------------------------------------------------
our_irq:
        pha
        txa
        pha
        tya
        pha

        ; Verify it's a Timer 1 IRQ (bit 3 of $FF09).
        ; If not T1, fall through (we don't have anything else enabled, but
        ; safety check costs ~6 cycles).
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
