; =============================================================================
; m1_test.s - YAPE/real-hardware test host for M1 player
; =============================================================================
; This is a standalone Plus/4 .prg that:
;   1. Loads itself into BASIC area ($1001)
;   2. BASIC stub: "10 SYS 4109" (= $100D, our entry point)
;   3. Copies embedded player.bin into $3000-$3FFF
;   4. Calls player_init ($3000)
;   5. Installs our IRQ handler at $0314/$0315
;   6. Enables Timer 1 at NTSC 60 Hz or PAL 50 Hz (autodetected)
;   7. Enters infinite loop — IRQ will fire every ~16-20ms and JSR $3006
;
; Expected behavior:
;   Continuous A-4 tone (~433 Hz) on ch A of DigiMuz AY card.
;   Infinite — press RUN STOP + RESTORE to kill it.
;
; To build:
;   ca65 -I src -o build/m1_test.o src/m1_test.s
;   ld65 -C src/m1_test.cfg -o build/m1_test.prg build/m1_test.o
;
; To test in YAPE:
;   Load m1_test.prg (with DigiMuz card emulation enabled)
;   RUN
;   → you should hear a continuous tone. SYS 65526 to RESET.
; =============================================================================

        .include "pt3_player.inc"

; -----------------------------------------------------------------------------
; TED registers (Plus/4 / C16)
; -----------------------------------------------------------------------------
TED_TIMER1_LO   = $FF00     ; Timer 1 counter low / reload low (write = both)
TED_TIMER1_HI   = $FF01     ; Timer 1 counter high / reload high
TED_IRQ_STATUS  = $FF09     ; IRQ pending flags (write bit-mask to ack)
TED_IRQ_ENABLE  = $FF0A     ; IRQ mask
TED_VIDEO_MODE  = $FF07     ; bit 6 = PAL (1) / NTSC (0)

; Bits in $FF09/$FF0A
IRQ_BIT_TIMER1  = $10       ; bit 4 = Timer 1

; IRQ vector in KERNAL RAM (OS jumps through this after saving regs)
KERNAL_IRQ_VEC_LO = $0314
KERNAL_IRQ_VEC_HI = $0315

; -----------------------------------------------------------------------------
; BASIC stub at $1001 — "10 SYS 4109"
; -----------------------------------------------------------------------------
; Plus/4 BASIC program layout (same format as C64):
;   [next_line_ptr:2] [line_number:2] [tokens] [00] [00 00]
; $1001 is the Plus/4 BASIC start. "SYS 4109" tokenizes to: $9E "4109" $00 $00
; 4109 = $100D = our main entry below.
; -----------------------------------------------------------------------------
        .segment "BASIC_STUB"

        ; Load address for .prg (2 bytes, NOT part of memory image — consumed
        ; by LOAD). ld65 config handles this.

        ; next line ptr: $1009 (address of 00-terminator after "4109")
        .word   $1009
        ; line number: 10
        .word   10
        ; SYS token
        .byte   $9E
        ; "4109" as ASCII
        .byte   "4109"
        ; null terminator of this BASIC line
        .byte   0
        ; next line ptr = 0 (end of program)
        .word   0

; -----------------------------------------------------------------------------
; Main entry point at $100D
; -----------------------------------------------------------------------------
        .segment "CODE"

main:
        sei                         ; disable IRQs while we set up

        ; -- Copy embedded player.bin into $3000-$3FFF --
        ; Source: player_data label, length 4096 bytes
        ; Destination: $3000
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

        ; -- Call player_init (JSR $3000) --
        jsr     PLAYER_INIT

        ; -- Detect PAL/NTSC and set Timer 1 autoreload --
        lda     TED_VIDEO_MODE
        and     #$40                ; bit 6 = PAL
        beq     @ntsc
        ; PAL 50 Hz: reload = 886724 / 50 = 17734 = $4546
        lda     #$46
        sta     TED_TIMER1_LO
        lda     #$45
        sta     TED_TIMER1_HI
        jmp     @timer_set
@ntsc:
        ; NTSC 60 Hz: reload = 894841 / 60 = 14914 = $3A42
        lda     #$42
        sta     TED_TIMER1_LO
        lda     #$3A
        sta     TED_TIMER1_HI
@timer_set:

        ; -- Save original IRQ vector so we can chain to it --
        lda     KERNAL_IRQ_VEC_LO
        sta     saved_irq_vec_lo
        lda     KERNAL_IRQ_VEC_HI
        sta     saved_irq_vec_hi

        ; -- Install our IRQ handler at $0314/$0315 --
        lda     #<my_irq_handler
        sta     KERNAL_IRQ_VEC_LO
        lda     #>my_irq_handler
        sta     KERNAL_IRQ_VEC_HI

        ; -- Enable Timer 1 IRQ in TED --
        lda     TED_IRQ_ENABLE
        ora     #IRQ_BIT_TIMER1
        sta     TED_IRQ_ENABLE

        cli                         ; let IRQs fire

        ; -- Infinite loop. IRQ does all the work. --
@idle:
        jmp     @idle

; -----------------------------------------------------------------------------
; IRQ handler
; -----------------------------------------------------------------------------
; The KERNAL IRQ entry (at $FFFE vector → ROM) has already saved A/X/Y/P
; and jumped through $0314/$0315 to here. We just need to:
;   1. Check if Timer 1 was the source
;   2. Ack Timer 1 pending bit in $FF09
;   3. Call player_play
;   4. JMP to normal IRQ return ($CE00 on Plus/4, or $EA31 C64-style —
;      we'll let KERNAL handle restore by RTI'ing via normal return chain)
;
; Since we want the KERNAL to do its usual housekeeping (keyboard scan etc.)
; we chain: do our work, then JMP to the original handler that was there
; before we overwrote the vector. Actually, simpler: just JMP to the default
; Plus/4 IRQ handler routine that the OS would have run.
;
; -----------------------------------------------------------------------------

my_irq_handler:
        ; Check Timer 1 pending
        lda     TED_IRQ_STATUS
        and     #IRQ_BIT_TIMER1
        beq     @not_our_irq

        ; Ack Timer 1 (write 1 to bit 4 to clear it)
        lda     #IRQ_BIT_TIMER1
        sta     TED_IRQ_STATUS

        ; Call the music player
        jsr     PLAYER_PLAY

@not_our_irq:
        ; Chain to KERNAL default handler (keyboard scan + cursor + RTI)
        jmp     (saved_irq_vec_lo)

; -----------------------------------------------------------------------------
; Saved original IRQ vector
; -----------------------------------------------------------------------------
saved_irq_vec_lo:
        .byte   0
saved_irq_vec_hi:
        .byte   0

; -----------------------------------------------------------------------------
; Embedded player.bin — 4096 bytes
; -----------------------------------------------------------------------------
player_data:
        .incbin "../build/player.bin"

; =============================================================================
