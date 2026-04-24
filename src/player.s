; =============================================================================
; player.s - PT3 Player M2+M3: Note Table + Volume Table Generators
; =============================================================================

        .include "pt3_player.inc"

        .segment "CODE"

; Jump table at $3000 (10 entries × 3 bytes)
jump_table:
        jmp player_init                  ; $3000
        jmp player_load_pt3              ; $3003
        jmp player_play                  ; $3006
        jmp player_stop                  ; $3009
        jmp player_rewind                ; $300C
        jmp player_is_playing            ; $300F
        jmp player_is_song_ended         ; $3012
        jmp player_set_flags             ; $3015
        jmp player_build_note_table      ; $3018 — M2
        jmp player_build_volume_table    ; $301B — M3

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

        ; NT_SELECTOR lookup: entry index = table*2 + version, offset = idx * 3
        lda     nt_arg_table
        asl     a
        ora     nt_arg_version           ; A = entry idx 0..7
        sta     nt_sel_tmp
        asl     a                         ; *2
        clc
        adc     nt_sel_tmp                ; +*1 = *3
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

        ; Special case: if raw_byte == 1 (table 1), set note_table[46] = 0xFD
        lda     nt_raw_byte
        cmp     #1
        bne     @no_special
        lda     #$FD
        sta     note_table + 46
@no_special:

        jsr     apply_corrections
        rts

; -----------------------------------------------------------------------------
; depack_t_pack — fills t1_buf (98 bytes) from T_PACK_DATA, writing REVERSED
; -----------------------------------------------------------------------------
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

        ; write_idx starts at 96 (last word low byte); decrements by 2
        lda     #96
        sta     dp_write_idx

@loop:
        cpy     #T_PACK_LEN
        bcs     @done

        lda     T_PACK_DATA,y
        iny

        cmp     #30
        bcc     @abs

        ; Delta record: hl += 2*a
        asl     a                         ; A = 2*a, C = hi bit
        pha
        lda     #0
        adc     #0                        ; capture carry
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

; -----------------------------------------------------------------------------
; generate_notes — fill note_table[192] from t1_buf base values
; -----------------------------------------------------------------------------
generate_notes:
        lda     #0
        sta     gn_note_i

@note_loop:
        ; Fetch base value
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
        ; bc >>= 1 (shift_carry goes to C)
        lsr     gn_bc_hi
        ror     gn_bc_lo

        ; If truncate, clear carry
        lda     nt_truncate
        beq     @no_trunc
        clc
@no_trunc:
        ; Add carry to bc_lo, propagate
        lda     gn_bc_lo
        adc     #0
        sta     gn_tmp_lo
        lda     gn_bc_hi
        adc     #0
        sta     gn_tmp_hi

        ; Compute dest byte offset = note_i*2 + octave*24
        lda     gn_octave
        asl     a                         ; *2
        asl     a                         ; *4
        asl     a                         ; *8
        sta     gn_dest_tmp               ; oct*8
        asl     a                         ; *16
        clc
        adc     gn_dest_tmp               ; +*8 = *24
        sta     gn_dest_tmp
        lda     gn_note_i
        asl     a                         ; *2
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

; -----------------------------------------------------------------------------
; apply_corrections — walks (nt_corr_ptr), stops at 0.
; -----------------------------------------------------------------------------
apply_corrections:
        ; Copy corr pointer to zero page (6502 needs ZP for (indirect),Y)
        lda     nt_corr_ptr_lo
        sta     ZP_TEMP_LO
        lda     nt_corr_ptr_hi
        sta     ZP_TEMP_HI

        ldy     #0
@loop:
        lda     (ZP_TEMP_LO),y
        beq     @done

        pha
        lsr     a                         ; A = word_idx (= byte offset)
        asl     a                         ; *2 = byte offset in note_table
        tax
        pla
        and     #1
        beq     @add

        ; sign=1 → decrement low byte
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

; =============================================================================
; player_build_volume_table(A = pt_version)
; =============================================================================
; Port of pt3_tables.build_volume_table (Ivan Roshin's VolTableCreator).
;
; pt_version < 5  -> OLD variant (PT 3.xx..3.4x)
;                    Initial: HL=$0010, DE=$0010, use_rla=0
; pt_version >= 5 -> NEW variant (PT 3.5+..VTII1.0)
;                    Initial: HL=$0011, DE=$0000, use_rla=1
;
; Algorithm (nested loop, 16 × 16 = 256 iterations):
;   vt[0..15] = 0 (first 16 entries always zero)
;   write_idx = 16, C = 0x10, carry = 0
;   do {
;     save_HL = HL
;     HL = HL + DE; carry = overflow
;     swap HL <-> DE
;     HL = -carry & 0xFFFF  (SBC HL,HL trick)
;     do {
;       A = L
;       if use_rla: A = (A<<1) | carry; carry = old_bit_7
;       A = H  (A loaded, carry preserved)
;       A = A + carry; carry = overflow
;       vt[write_idx] = A; write_idx++
;       HL = HL + DE; carry = overflow
;       C = (C+1) & 0xFF
;     } while (C & 0x0F) != 0
;     HL = save_HL
;     if E == 0x77: E = E + 1
;   } while C != 0
; -----------------------------------------------------------------------------
player_build_volume_table:
        ; Store pt_version, decide variant
        cmp     #5
        bcs     @new_variant

        ; OLD variant: H=0, L=$10, D=0, E=$10, use_rla=0
        lda     #$00
        sta     vt_H
        sta     vt_D
        sta     vt_use_rla
        lda     #$10
        sta     vt_L
        sta     vt_E
        jmp     @start

@new_variant:
        ; NEW variant: H=0, L=$11, D=0, E=$00, use_rla=1
        lda     #$00
        sta     vt_H
        sta     vt_D
        sta     vt_E
        lda     #$11
        sta     vt_L
        lda     #1
        sta     vt_use_rla

@start:
        ; Zero first 16 entries of volume_table (rest gets overwritten)
        ldx     #15
        lda     #0
@clear_vt:
        sta     volume_table,x
        dex
        bpl     @clear_vt

        ; write_idx = 16, C = $10, carry = 0
        lda     #16
        sta     vt_write_idx
        lda     #$10
        sta     vt_C
        lda     #0
        sta     vt_carry

; ---------- Outer loop INITV2 ----------
@outer:
        ; save_HL = HL
        lda     vt_H
        sta     vt_saveH
        lda     vt_L
        sta     vt_saveL

        ; HL = HL + DE, carry = overflow
        clc
        lda     vt_L
        adc     vt_E
        sta     vt_L
        lda     vt_H
        adc     vt_D
        sta     vt_H
        lda     #0
        adc     #0                       ; capture carry out
        sta     vt_carry

        ; Swap HL <-> DE
        lda     vt_H
        ldx     vt_D
        sta     vt_D
        stx     vt_H
        lda     vt_L
        ldx     vt_E
        sta     vt_E
        stx     vt_L

        ; HL = -carry (i.e. 0x0000 if carry=0, 0xFFFF if carry=1)
        ; SBC HL,HL trick: HL = HL - HL - carry
        ; When C=0: 0-0-0 = 0
        ; When C=1: 0-0-1 = -1 = 0xFFFF
        lda     vt_carry
        beq     @hl_zero
        lda     #$FF
        sta     vt_H
        sta     vt_L
        jmp     @inner
@hl_zero:
        lda     #0
        sta     vt_H
        sta     vt_L

; ---------- Inner loop INITV1 ----------
@inner:
        ; A = L
        lda     vt_L

        ; If use_rla: A = (A << 1) | carry; carry = old bit 7
        ldx     vt_use_rla
        beq     @skip_rla

        ; old bit 7 of A -> new carry
        ; Use ASL to shift A and capture carry
        asl     a                        ; A = A << 1, carry = old bit 7
        ; Carry flag now has old bit 7. We need to OR in old vt_carry as bit 0
        ; but ASL already cleared bit 0 to 0.
        ; Bring vt_carry into bit 0 without disturbing C:
        pha                              ; save A (post-shift, without OR)
        lda     vt_carry                 ; 0 or 1
        tax                              ; X has old vt_carry
        lda     #0
        rol     a                        ; A = old hardware carry (bit 7 before ASL)
        sta     vt_carry                 ; save new carry
        pla                              ; restore A (post-shift)
        ; Now add X (which is 0 or 1) to A
        stx     vt_tmp
        ora     vt_tmp                   ; bit 0 = old vt_carry (safe because ASL cleared bit 0)
        ; Note: A is used only for carry extraction in Z80 — the "LD A,H" next
        ; overwrites it. So we don't need to preserve A's value.
@skip_rla:

        ; A = H (overwrites A, carry flag is CPU carry — but we need vt_carry)
        lda     vt_H

        ; A = A + 0 + vt_carry
        clc
        ldx     vt_carry
        beq     @no_carry_in
        sec
@no_carry_in:
        adc     #0                       ; A = A + carry
        ; New carry after add is in hardware C flag; capture
        pha
        lda     #0
        adc     #0                       ; captures carry out
        sta     vt_carry
        pla

        ; volume_table[write_idx] = A
        ldx     vt_write_idx
        sta     volume_table,x

        ; write_idx++
        inc     vt_write_idx

        ; HL = HL + DE, carry = overflow
        clc
        lda     vt_L
        adc     vt_E
        sta     vt_L
        lda     vt_H
        adc     vt_D
        sta     vt_H
        lda     #0
        adc     #0
        sta     vt_carry

        ; C = (C + 1) & 0xFF
        inc     vt_C
        ; Test: (C & 0x0F) == 0 ?
        lda     vt_C
        and     #$0F
        bne     @inner

; ---------- End of inner ----------

        ; Restore HL
        lda     vt_saveH
        sta     vt_H
        lda     vt_saveL
        sta     vt_L

        ; If E == $77: E = E + 1
        lda     vt_E
        cmp     #$77
        bne     @skip_einc
        clc
        adc     #1
        sta     vt_E
@skip_einc:

        ; Test C == 0 ?
        lda     vt_C
        beq     @done
        jmp     @outer
@done:

        ; Done
        rts

; =============================================================================
; RODATA
; =============================================================================

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
; TCNEW_3 chains immediately into TCOLD_3 (no terminator)
TCNEW_3_CHAIN:
        .byte   $57
; Must be contiguous with TCNEW_3_CHAIN
TCOLD_3_CHAINED:
        .byte   $1F, $23, $25, $29, $2D, $2F, $33, $BF, 0

; NT_SELECTOR: 8 entries × 3 bytes
NT_SELECTOR_RAW:
        .byte   100                       ; table=0 NEW: raw=100
        .word   TCNEW_0_LIST
        .byte   101                       ; table=0 OLD: raw=101
        .word   TCOLD_0_LIST
        .byte   1                         ; table=1 NEW: raw=1
        .word   TCOLD_1_LIST
        .byte   1                         ; table=1 OLD: raw=1
        .word   TCOLD_1_LIST
        .byte   148                       ; table=2 NEW: raw=148
        .word   TCNEW_2_LIST
        .byte   48                        ; table=2 OLD: raw=48
        .word   TCOLD_2_LIST
        .byte   96                        ; table=3 NEW: raw=96, chain TCNEW_3
        .word   TCNEW_3_CHAIN
        .byte   96                        ; table=3 OLD: raw=96
        .word   TCOLD_3_LIST

; =============================================================================
; BSS
; =============================================================================

        .segment "BSS"

shadow_ay:              .res 14
playing_flag:           .res 1
flags_byte:             .res 1

; Note table generator scratch
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

; Volume table generator state
vt_H:                   .res 1
vt_L:                   .res 1
vt_D:                   .res 1
vt_E:                   .res 1
vt_saveH:               .res 1
vt_saveL:               .res 1
vt_use_rla:             .res 1
vt_carry:               .res 1
vt_write_idx:           .res 1
vt_C:                   .res 1
vt_tmp:                 .res 1

volume_table:           .res 256

.exportzp note_table_addr_hint := $FF
.export note_table
.export volume_table
