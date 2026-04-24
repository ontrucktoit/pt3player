; =============================================================================
; player.s - PT3 Player M2 "Note Table Generator"
; =============================================================================

        .include "pt3_player.inc"

        .segment "CODE"

; Jump table at $3000 (9 entries × 3 bytes)
jump_table:
        jmp player_init                  ; $3000
        jmp player_load_pt3              ; $3003
        jmp player_play                  ; $3006
        jmp player_stop                  ; $3009
        jmp player_rewind                ; $300C
        jmp player_is_playing            ; $300F
        jmp player_is_song_ended         ; $3012
        jmp player_set_flags             ; $3015
        jmp player_build_note_table      ; $3018 — NEW in M2

; -----------------------------------------------------------------------------
player_init:
        ldx     #13
@clr:
        lda     #0
        sta     shadow_ay,x
        dex
        bpl     @clr

        lda     #$00
        sta     shadow_ay + AY_R0_TONE_A_LO
        lda     #$01
        sta     shadow_ay + AY_R1_TONE_A_HI
        lda     #$3E
        sta     shadow_ay + AY_R7_MIXER
        lda     #$0F
        sta     shadow_ay + AY_R8_AMP_A

        lda     #1
        sta     playing_flag
        rts

player_load_pt3:
        rts

player_play:
        lda     playing_flag
        beq     @done
        ldx     #13
@wloop:
        stx     DIGIMUZ_REG_SEL
        lda     shadow_ay,x
        sta     DIGIMUZ_DATA_W
        dex
        bpl     @wloop
@done:
        rts

player_stop:
        lda     #0
        sta     shadow_ay + AY_R8_AMP_A
        sta     shadow_ay + AY_R9_AMP_B
        sta     shadow_ay + AY_R10_AMP_C
        sta     playing_flag
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

player_rewind:
        jsr     player_stop
        rts

player_is_playing:
        lda     playing_flag
        rts

player_is_song_ended:
        lda     #0
        rts

player_set_flags:
        pha
        and     #FLAG_LOOP_TRACK
        beq     @track_off
        lda     #FLAG_LOOP_TRACK
        sta     flags_byte
        pla
        rts
@track_off:
        pla
        and     #FLAG_LOOP_TRACK | FLAG_LOOP_PLAYLIST
        sta     flags_byte
        rts

; =============================================================================
; player_build_note_table(A = table_idx, X = version_is_old)
; =============================================================================
player_build_note_table:
        sta     nt_arg_table
        stx     nt_arg_version

        jsr     depack_t_pack

        lda     nt_arg_table
        asl     a
        ora     nt_arg_version
        sta     nt_sel_tmp
        asl     a
        clc
        adc     nt_sel_tmp
        tay

        lda     NT_SELECTOR_RAW,y
        sta     nt_raw_byte
        lda     NT_SELECTOR_RAW+1,y
        sta     nt_corr_ptr_lo
        lda     NT_SELECTOR_RAW+2,y
        sta     nt_corr_ptr_hi

        lda     nt_raw_byte
        and     #1
        sta     nt_truncate

        lda     nt_raw_byte
        lsr     a
        sta     nt_t1_byte_off

        jsr     generate_notes

        lda     nt_raw_byte
        cmp     #1
        bne     @no_special
        lda     #$FD
        sta     note_table + 46
@no_special:

        jsr     apply_corrections
        rts

depack_t_pack:
        ldx     #97
        lda     #0
@clr:
        sta     t1_buf,x
        dex
        bpl     @clr

        lda     #0
        sta     dp_hl_lo
        sta     dp_hl_hi

        ldy     #0

        lda     #96
        sta     dp_write_idx

@loop:
        cpy     #T_PACK_LEN
        bcs     @done

        lda     T_PACK_DATA,y
        iny

        cmp     #30
        bcc     @abs

        asl     a
        pha
        lda     #0
        adc     #0
        sta     dp_temp
        pla
        clc
        adc     dp_hl_lo
        sta     dp_hl_lo
        lda     dp_hl_hi
        adc     dp_temp
        sta     dp_hl_hi
        jmp     @store

@abs:
        sta     dp_hl_hi
        cpy     #T_PACK_LEN
        bcs     @done
        lda     T_PACK_DATA,y
        iny
        sta     dp_hl_lo

@store:
        ldx     dp_write_idx
        lda     dp_hl_lo
        sta     t1_buf,x
        inx
        lda     dp_hl_hi
        sta     t1_buf,x

        lda     dp_write_idx
        sec
        sbc     #2
        sta     dp_write_idx

        lda     dp_hl_lo
        cmp     #$F0
        beq     @done

        lda     dp_write_idx
        bmi     @done

        jmp     @loop

@done:
        rts

generate_notes:
        lda     #0
        sta     gn_note_i

@note_loop:
        lda     gn_note_i
        asl     a
        clc
        adc     nt_t1_byte_off
        tax
        lda     t1_buf,x
        sta     gn_bc_lo
        inx
        lda     t1_buf,x
        sta     gn_bc_hi

        lda     #0
        sta     gn_octave

@octave_loop:
        lsr     gn_bc_hi
        ror     gn_bc_lo

        lda     nt_truncate
        beq     @no_trunc
        clc
@no_trunc:
        lda     gn_bc_lo
        adc     #0
        sta     gn_tmp_lo
        lda     gn_bc_hi
        adc     #0
        sta     gn_tmp_hi

        lda     gn_octave
        asl     a
        asl     a
        asl     a
        sta     gn_dest_tmp
        asl     a
        clc
        adc     gn_dest_tmp
        sta     gn_dest_tmp
        lda     gn_note_i
        asl     a
        clc
        adc     gn_dest_tmp
        tax

        lda     gn_tmp_lo
        sta     note_table,x
        inx
        lda     gn_tmp_hi
        sta     note_table,x

        inc     gn_octave
        lda     gn_octave
        cmp     #8
        bcc     @octave_loop

        inc     gn_note_i
        lda     gn_note_i
        cmp     #12
        bcc     @note_loop

        rts

apply_corrections:
        lda     nt_corr_ptr_lo
        sta     ZP_TEMP_LO
        lda     nt_corr_ptr_hi
        sta     ZP_TEMP_HI

        ldy     #0
@loop:
        lda     (ZP_TEMP_LO),y
        beq     @done

        pha
        lsr     a
        asl     a
        tax
        pla
        and     #1
        beq     @add

        lda     note_table,x
        sec
        sbc     #1
        sta     note_table,x
        jmp     @next
@add:
        lda     note_table,x
        clc
        adc     #1
        sta     note_table,x
@next:
        iny
        bne     @loop
@done:
        rts

        .segment "RODATA"

T_PACK_DATA:
        .byte   $0D, $D8
        .byte   $69, $70, $76, $7D, $85, $8D, $95, $9D, $A8, $B1, $BB
        .byte   $0C, $DA
        .byte   $62, $68, $6D, $75, $7B, $83, $8A, $92, $9C, $A4, $AF, $B8
        .byte   $0E, $08
        .byte   $6A, $72, $78, $7E, $86, $90, $96, $A0, $AA, $B4, $BE
        .byte   $0F, $C0
        .byte   $78, $88, $80, $90, $98, $A0, $B0, $A8, $E0, $B0, $E8

T_PACK_LEN = * - T_PACK_DATA

TCOLD_0_LIST:
        .byte   $01, $05, $09, $0B, $0D, $0F, $13, $15, $19, $25, $3D, 0
TCOLD_1_LIST:
        .byte   $5D, 0
TCOLD_2_LIST:
        .byte   $31, $37, $4D, $53, $5F, $71, $82, $8C, $9C, $9E, $A0
        .byte   $A6, $A8, $AA, $AC, $AE, $AE, 0
TCOLD_3_LIST:
        .byte   $1F, $23, $25, $29, $2D, $2F, $33, $BF, 0
TCNEW_0_LIST:
        .byte   $1D, $21, $23, $27, $2B, $2D, $31, $55, $BD, $BF, 0
TCNEW_2_LIST:
        .byte   $1B, $21, $25, $29, $2B, $3B, $4D, $5F, $BB, $BD, $BF, 0
TCNEW_3_CHAIN:
        .byte   $57
TCOLD_3_CHAINED:
        .byte   $1F, $23, $25, $29, $2D, $2F, $33, $BF, 0

NT_SELECTOR_RAW:
        .byte   100
        .word   TCNEW_0_LIST
        .byte   101
        .word   TCOLD_0_LIST
        .byte   1
        .word   TCOLD_1_LIST
        .byte   1
        .word   TCOLD_1_LIST
        .byte   148
        .word   TCNEW_2_LIST
        .byte   48
        .word   TCOLD_2_LIST
        .byte   96
        .word   TCNEW_3_CHAIN
        .byte   96
        .word   TCOLD_3_LIST

        .segment "BSS"

shadow_ay:              .res 14
playing_flag:           .res 1
flags_byte:             .res 1

nt_arg_table:           .res 1
nt_arg_version:         .res 1
nt_raw_byte:            .res 1
nt_corr_ptr_lo:         .res 1
nt_corr_ptr_hi:         .res 1
nt_truncate:            .res 1
nt_t1_byte_off:         .res 1
nt_sel_tmp:             .res 1

dp_hl_lo:               .res 1
dp_hl_hi:               .res 1
dp_write_idx:           .res 1
dp_temp:                .res 1

gn_note_i:              .res 1
gn_octave:              .res 1
gn_bc_lo:               .res 1
gn_bc_hi:               .res 1
gn_tmp_lo:              .res 1
gn_tmp_hi:              .res 1
gn_dest_tmp:            .res 1

t1_buf:                 .res 98
note_table:             .res 192

.exportzp note_table_addr_hint := $FF
.export note_table
