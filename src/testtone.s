; testtone.s - Standalone Plus/4 test tone program.
;
; Load address: $1001 (Plus/4 BASIC start).
; Layout:
;   $1001-$100C  BASIC stub "10 SYS 4109"
;                ($1001-$1002 link ptr, $1003-$1004 line#, $1005 SYS token,
;                 $1006-$1009 "4109", $100A $00, $100B-$100C $00 $00)
;   $100D        assembly entry point (=4109 decimal, SYS target)
;   ...          startup: silence TED, call player_init + test_tone, loop
;   $3000-$3FFF  Player binary
;
; v2 fix: SYS target was $100D but CODE was at $1010 in v1 — three $00 BRK
; bytes at $100D crashed immediately. Fixed by putting CODE at $100D directly
; (HEADER size = $000C in cfg).
;
; v2 fix: no SEI — leaving IRQ active so Plus/4 DRAM refresh + keyboard scan
; continue to work. DigiMuz tone gets set once and latches; no IRQ-driven
; update needed for a constant tone smoke test.

        .segment "BASIC"
        .word   next_line                ; next-line link = $100B
        .word   10                       ; line number 10
        .byte   $9E                      ; SYS token
        .byte   "4109"                   ; target address $100D
        .byte   $00                      ; end of line
next_line:
        .word   $0000                    ; end of program

        .segment "CODE"

; Startup code at $100D (= 4109 decimal).
start:
        ; Silence TED sound (FF11 low volume bits, FF12 sound enable bits)
        ; so Plus/4 internal square wave doesn't overlap DigiMuz output.
        lda     #0
        sta     $FF11
        sta     $FF12

        ; Establish clean player state.
        jsr     $3000                    ; PLAYER_INIT

        ; Fire the smoke test tone — sets all 14 AY registers for a
        ; pure tone on ch A, period $0200, volume 15.
        jsr     $3027                    ; PLAYER_PLAY_TEST_TONE

        ; Return to BASIC. AY latches stay set — tone continues playing
        ; until reset. User hears steady tone, can press RUN/STOP or do
        ; anything else; tone continues until power off or explicit reset.
        rts
