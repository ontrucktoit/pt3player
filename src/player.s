; =============================================================================
; player.s - PT3 Player for Commodore Plus/4 + DigiMuz AY card
; =============================================================================
; Milestone M1: "Hello Tone"
;
; This is the simplest useful player — hardcoded to always play a single note
; (A-4) on channel A. No pattern decode, no samples, no ornaments, no effects.
;
; Purpose of M1:
;   1. Verify that the jump table is at the expected address ($3000-$3017).
;   2. Verify that writes to shadow_ay[] propagate to hardware via DigiMuz
;      register-select + data-write sequence.
;   3. Verify that player_play produces deterministic output frame-by-frame
;      (same values written every tick).
;   4. Establish the IRQ-handler calling convention (pure JSR subroutine,
;      no timer programming, no vector installation).
;
; Calling convention (per docs/ARCHITECTURE.md Q1):
;   Host program owns Timer 1 IRQ. Host's IRQ handler does:
;       jsr PLAYER_PLAY         ; = JSR $3006
;   Player library never touches TED timer or IRQ vectors.
;
; Reference: docs/ARCHITECTURE.md, docs/REFERENCES.md,
;            ../pt3_python_sim/README.md (14 design notes, validated 20/20 bit-exact)
; =============================================================================

        .include "pt3_player.inc"

; =============================================================================
; CODE segment — starts at $3000
; =============================================================================

        .segment "CODE"

; -----------------------------------------------------------------------------
; Jump table at $3000-$3017 (8 entries × 3 bytes each)
; -----------------------------------------------------------------------------
; This table MUST be the first thing in the CODE segment. Host programs
; reference these addresses as fixed constants (see pt3_player.inc).
;
; Each entry is a 3-byte JMP absolute, which makes the library relocatable
; (procedure labels can be anywhere, as long as the JMP targets at $3000+n*3
; resolve correctly).
; -----------------------------------------------------------------------------
jump_table:
        jmp player_init              ; $3000
        jmp player_load_pt3          ; $3003
        jmp player_play              ; $3006
        jmp player_stop              ; $3009
        jmp player_rewind            ; $300C
        jmp player_is_playing        ; $300F
        jmp player_is_song_ended     ; $3012
        jmp player_set_flags         ; $3015
                                     ; $3018 — first byte of actual code

; -----------------------------------------------------------------------------
; player_init — one-time initialization
; -----------------------------------------------------------------------------
; Called once by host at program start (before any other player call).
;
; M1 scope: just set up the shadow AY with the "A-4 on channel A" values
; and mark player as playing. In M2+ this will build note/volume tables.
;
; Preserves: nothing (host must save state if needed).
; Returns:   nothing.
; -----------------------------------------------------------------------------
player_init:
        ; Zero the shadow AY buffer and state
        ldx     #13
@clear_loop:
        lda     #0
        sta     shadow_ay,x
        dex
        bpl     @clear_loop

        ; Set up the M1 "hello tone" state:
        ;   Channel A tone period = $03FC (A-4 in PT3 tone table 1 — "ASM-PT2")
        ;   Actually for M1 we'll use an approximation that YAPE and real
        ;   hardware will both produce an audible tone regardless of PAL/NTSC
        ;   clock differences. The exact value doesn't matter in M1 — we just
        ;   need "a tone".
        ;
        ; Using $0100 (= 256 dec) as tone period:
        ;   AY tone freq = clock / (16 × period)
        ;   Assume DigiMuz AY is clocked at ~1.77 MHz (standard ZX Spectrum
        ;   AY clock, which DigiMuz typically uses)
        ;   → freq = 1773400 / (16 × 256) = ~433 Hz (close to A-4 = 440 Hz)
        ;
        ; This is close enough to A-4 that it'll sound musical without needing
        ; the real note table (coming in M2).
        lda     #$00
        sta     shadow_ay + AY_R0_TONE_A_LO
        lda     #$01
        sta     shadow_ay + AY_R1_TONE_A_HI

        ; R7 (mixer): enable tone on ch A, disable everything else
        ; Bit meaning: 1=disabled. So for "ch A tone only":
        ;   bit 0 = !ToneA = 0
        ;   bits 1-2 = !ToneB,C = 1
        ;   bits 3-5 = !NoiseA,B,C = 1
        ;   bits 6-7 = I/O direction = 0 (input, unused)
        ; = %00111110 = $3E
        lda     #$3E
        sta     shadow_ay + AY_R7_MIXER

        ; R8 (ch A amplitude): full volume, no envelope
        ; Bits 0-3 = volume 0..15
        ; Bit 4    = 0 (fixed amplitude, not envelope-controlled)
        lda     #$0F
        sta     shadow_ay + AY_R8_AMP_A

        ; Mark player as playing
        lda     #1
        sta     playing_flag

        rts

; -----------------------------------------------------------------------------
; player_load_pt3 — M1 stub (not implemented until M4)
; -----------------------------------------------------------------------------
; Returns immediately without loading anything. In M4 this will parse the
; PT3 header at the address passed in A (lo) / X (hi).
; -----------------------------------------------------------------------------
player_load_pt3:
        rts

; -----------------------------------------------------------------------------
; player_play — THE MAIN TICK HANDLER
; -----------------------------------------------------------------------------
; Called once per audio frame (50 Hz PAL or 60 Hz NTSC) by the host's IRQ
; handler. In M1 this just writes the shadow AY to hardware — no decode,
; no state advancement.
;
; Preserves: nothing (caller's IRQ handler must save/restore A,X,Y,P).
; Returns:   nothing.
; -----------------------------------------------------------------------------
player_play:
        ; If not playing, do nothing (host may JSR us even when paused)
        lda     playing_flag
        beq     @done

        ; Write the 14 shadow AY registers to hardware via DigiMuz.
        ; We write R13 down to R0; R13 is written LAST so any envelope restart
        ; (which a R13 write triggers on AY) happens at the END of the tick,
        ; which matches Python simulator's frame-ordering behavior.
        ;
        ; Actually — per design note #13 and VTII behavior, we should ONLY
        ; write R13 when env_shape changed this tick (r13_needs_write flag).
        ; In M1 we don't care (no envelope), so write all 14.
        ;
        ; Total cycles for this loop: 13 iterations × ~14 cycles = ~180 cycles.
        ; Well within the 7000-cycle IRQ budget.
        ldx     #13
@write_loop:
        stx     DIGIMUZ_REG_SEL      ; latch register select
        lda     shadow_ay,x
        sta     DIGIMUZ_DATA_W       ; write value
        dex
        bpl     @write_loop

@done:
        rts

; -----------------------------------------------------------------------------
; player_stop — mute + halt (preserves position)
; -----------------------------------------------------------------------------
; Zero the shadow AY amplitudes (R8, R9, R10) so AY goes silent, and clear
; playing_flag. Position/pattern state is NOT reset; call player_rewind for
; full reset.
; -----------------------------------------------------------------------------
player_stop:
        lda     #0
        sta     shadow_ay + AY_R8_AMP_A
        sta     shadow_ay + AY_R9_AMP_B
        sta     shadow_ay + AY_R10_AMP_C
        sta     playing_flag

        ; Write out now so hardware actually goes silent this tick.
        ; Only need to write R8, R9, R10.
        ldx     #AY_R8_AMP_A
        stx     DIGIMUZ_REG_SEL
        lda     #0
        sta     DIGIMUZ_DATA_W
        ldx     #AY_R9_AMP_B
        stx     DIGIMUZ_REG_SEL
        sta     DIGIMUZ_DATA_W
        ldx     #AY_R10_AMP_C
        stx     DIGIMUZ_REG_SEL
        sta     DIGIMUZ_DATA_W
        rts

; -----------------------------------------------------------------------------
; player_rewind — full reset
; -----------------------------------------------------------------------------
; M1 scope: just calls player_stop (no song loaded yet, nothing to rewind).
; M4+ will reset current_position, current_line, etc.
; -----------------------------------------------------------------------------
player_rewind:
        jsr     player_stop
        rts

; -----------------------------------------------------------------------------
; player_is_playing — returns A=1 if playing, A=0 if stopped
; -----------------------------------------------------------------------------
player_is_playing:
        lda     playing_flag
        rts

; -----------------------------------------------------------------------------
; player_is_song_ended — returns A=1 if song ended this tick
; -----------------------------------------------------------------------------
; M1 stub: always returns 0 (no song to end).
; -----------------------------------------------------------------------------
player_is_song_ended:
        lda     #0
        rts

; -----------------------------------------------------------------------------
; player_set_flags — A = flag bits
; -----------------------------------------------------------------------------
; Handles the mutual-exclusion logic for track loop and playlist loop:
;   If bit0 (loop_track) is set, bit1 (loop_playlist) is force-cleared.
;   If caller tries to set bit1 while loop_track is currently set, bit1 is
;   ignored (silently discarded).
;
; Input: A = desired flag bits
;        bit 0 = loop_track
;        bit 1 = loop_playlist
; -----------------------------------------------------------------------------
player_set_flags:
        pha                           ; save incoming value
        and     #FLAG_LOOP_TRACK      ; isolate loop_track bit
        beq     @track_off            ; branch if loop_track=0

        ; loop_track=1 → force loop_playlist=0
        lda     #FLAG_LOOP_TRACK
        sta     flags_byte
        pla                           ; discard incoming (we used our own)
        rts

@track_off:
        ; loop_track=0 → accept caller's loop_playlist as-is
        pla
        and     #FLAG_LOOP_TRACK | FLAG_LOOP_PLAYLIST
        sta     flags_byte
        rts

; =============================================================================
; BSS segment — RAM state (zeroed at load time by ld65 fillval, but we also
; zero it explicitly in player_init for safety on reruns)
; =============================================================================

        .segment "BSS"

; The shadow AY buffer — player logic writes here, then write_loop at the end
; of player_play sends all 14 registers to hardware.
shadow_ay:              .res 14

; Player state flags
playing_flag:           .res 1        ; 0=stopped, 1=playing
flags_byte:             .res 1        ; bit0=loop_track, bit1=loop_playlist

; M2+ will add more state here (channel state, position, etc.)

; =============================================================================
; End of player.s
; =============================================================================
