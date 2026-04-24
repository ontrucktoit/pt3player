; testtone.s - Standalone Plus/4 test tone program.
;
; Load address: $1001 (standard Plus/4 BASIC start).
; Plus/4 file format: first 2 bytes = load address (little-endian), then data.
; ca65/ld65 emits the load address automatically via .segment linked to $1001,
; but we need the BASIC stub format correctly.
;
; Layout:
;   $1001-$1002  link to next line ($1010 or any end-of-prog marker)
;   $1003-$1004  line number 10 = $000A
;   $1005        BASIC token $9E = SYS
;   $1006-$1009  "4109" ASCII ($34 $31 $30 $39 — address $100D rounded up? No, $100D in decimal is 4109)
;   $100A        $00 end of line
;   $100B-$100C  $00 $00 = end of program
;   $100D        assembly entry point
;
; Our startup: call player_init at $3000, then player_play_test_tone at $3027,
; then infinite loop.

        .segment "BASIC"
        ; Link to next line = $1010 (doesn't really matter; basic doesn't chain here)
        .word   next_line
        .word   10                       ; line number
        .byte   $9E                      ; SYS token
        .byte   "4109"                   ; ASCII address = $100D
        .byte   $00                      ; end of line
next_line:
        .word   $0000                    ; end of program (null link)

        ; BASIC stub is 13 bytes ($1001..$100D-1). Assembly starts at $1010.
        ; ld65 will auto-pad the HEADER segment to fill 15 bytes since we said
        ; size = $000F, so gap $100E-$100F is filled with $00.

        .segment "CODE"

; Startup code at $1010
start:
        sei                              ; disable IRQ during setup

        ; Silence TED sound before we drive DigiMuz, to keep Plus/4's
        ; internal sound from fighting with the AY output.
        lda     #0
        sta     $FF11                    ; TED sound control (volume + mute)
        sta     $FF12

        ; Player doesn't strictly need init for test tone, but call it
        ; to establish a clean state. player_init = $3000.
        jsr     $3000                    ; PLAYER_INIT

        ; Fire the smoke test tone.
        jsr     $3027                    ; PLAYER_PLAY_TEST_TONE

        ; Hang forever — AY keeps playing the latched tone.
        ; Infinite loop with NOPs so CPU doesn't hammer the bus too hard.
@loop:
        nop
        nop
        nop
        jmp     @loop
