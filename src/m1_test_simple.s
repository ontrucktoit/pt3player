; =============================================================================
; m1_test_simple.s - Minimalist YAPE test: hook raster IRQ, no Timer 1
; =============================================================================
; Alternative to m1_test.s that avoids programming TED Timer 1 entirely.
; Instead, we hook the existing KERNAL raster IRQ (which fires every 1/60s
; NTSC or 1/50s PAL automatically) and piggyback on it.
;
; This is the most compatible approach — works identically to how classic
; SID players on C64 operate (they hook $0314/$0315 and chain to $EA31).
; =============================================================================

        .include "pt3_player.inc"

KERNAL_IRQ_VEC_LO = $0314
KERNAL_IRQ_VEC_HI = $0315

        .segment "BASIC_STUB"
        .word   $1009           ; next line ptr
        .word   10              ; line number
        .byte   $9E             ; SYS token
        .byte   "4109"          ; decimal address
        .byte   0               ; end of line
        .word   0               ; end of program

        .segment "CODE"

main:
        sei

        ; Copy player.bin from embedded storage to $3000
        ldx     #$00
@copy_page:
        lda     player_data + $000, x
        sta     $3000 + $000, x
        lda     player_data + $100, x
        sta     $3000 + $100, x
        lda     player_data + $200, x
        sta     $3000 + $200, x
        lda     player_data + $300, x
        sta     $3000 + $300, x
        lda     player_data + $400, x
        sta     $3000 + $400, x
        lda     player_data + $500, x
        sta     $3000 + $500, x
        lda     player_data + $600, x
        sta     $3000 + $600, x
        lda     player_data + $700, x
        sta     $3000 + $700, x
        lda     player_data + $800, x
        sta     $3000 + $800, x
        lda     player_data + $900, x
        sta     $3000 + $900, x
        lda     player_data + $A00, x
        sta     $3000 + $A00, x
        lda     player_data + $B00, x
        sta     $3000 + $B00, x
        lda     player_data + $C00, x
        sta     $3000 + $C00, x
        lda     player_data + $D00, x
        sta     $3000 + $D00, x
        lda     player_data + $E00, x
        sta     $3000 + $E00, x
        lda     player_data + $F00, x
        sta     $3000 + $F00, x
        inx
        bne     @copy_page

        ; Call player_init
        jsr     PLAYER_INIT

        ; Save original IRQ vector, install ours
        lda     KERNAL_IRQ_VEC_LO
        sta     saved_irq_lo
        lda     KERNAL_IRQ_VEC_HI
        sta     saved_irq_hi

        lda     #<my_irq
        sta     KERNAL_IRQ_VEC_LO
        lda     #>my_irq
        sta     KERNAL_IRQ_VEC_HI

        cli

        ; Infinite idle loop; everything happens in IRQ
@loop:  jmp     @loop

my_irq:
        jsr     PLAYER_PLAY           ; do our music tick
        jmp     (saved_irq_lo)        ; chain to KERNAL's regular handler

saved_irq_lo:
        .byte   0
saved_irq_hi:
        .byte   0

player_data:
        .incbin "../build/player.bin"
