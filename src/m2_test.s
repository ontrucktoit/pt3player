; =============================================================================
; m2_test.s - YAPE test: note table generator + play A-4 using generated table
; =============================================================================
; Differs from m1_test_simple.s:
;   - After player_init, calls player_build_note_table(1, 0) to build ST table
;   - Copies note_table[47..48] (index that produces ~440 Hz) into shadow_ay R0/R1
;   - Then installs IRQ hook as before
;
; Expected: continuous tone at ~440 Hz (slightly higher than M1's ~433 Hz).
; This proves the note table generator produces values that translate to
; musically correct tones on the real AY chip.
; =============================================================================

        .include "pt3_player.inc"

KERNAL_IRQ_VEC_LO = $0314
KERNAL_IRQ_VEC_HI = $0315

; note_table address — must match the build output (BSS layout).
; Look up $3327 in build/player.sym if this changes.
NOTE_TABLE_ADDR = $3327
SHADOW_AY_ADDR  = $32A2          ; shadow_ay lives at start of BSS
R0_ADDR = SHADOW_AY_ADDR + 0
R1_ADDR = SHADOW_AY_ADDR + 1

        .segment "BASIC_STUB"
        .word   $1009
        .word   10
        .byte   $9E
        .byte   "4109"
        .byte   0
        .word   0

        .segment "CODE"

main:
        sei

        ; Copy embedded player.bin (4096 bytes) to $3000
        ldx     #$00
@copy:
        .repeat 16, pg
        lda     player_data + pg*$100, x
        sta     $3000 + pg*$100, x
        .endrepeat
        inx
        bne     @copy

        ; player_init (sets up M1 hello-tone defaults incl. R0=$00, R1=$01)
        jsr     PLAYER_INIT

        ; Build note table: A=1 (ST, most common in VTII), X=0 (NEW version)
        lda     #1
        ldx     #0
        jsr     PLAYER_BUILD_NOTE_TABLE

        ; note_table[47*2 .. 47*2+1] = $00FC (~440 Hz at 1.77 MHz AY clock)
        lda     NOTE_TABLE_ADDR + 94
        sta     R0_ADDR
        lda     NOTE_TABLE_ADDR + 95
        sta     R1_ADDR

        ; Save and install IRQ vector
        lda     KERNAL_IRQ_VEC_LO
        sta     saved_irq_lo
        lda     KERNAL_IRQ_VEC_HI
        sta     saved_irq_hi

        lda     #<my_irq
        sta     KERNAL_IRQ_VEC_LO
        lda     #>my_irq
        sta     KERNAL_IRQ_VEC_HI

        cli

@loop:  jmp     @loop

my_irq:
        jsr     PLAYER_PLAY
        jmp     (saved_irq_lo)

saved_irq_lo:   .byte 0
saved_irq_hi:   .byte 0

player_data:
        .incbin "../build/player.bin"
