; =============================================================================
; player.s - PT3 Player M2+M3+M4+M5a+M5b+M6: +Full playback engine
; =============================================================================

        .include "pt3_player.inc"

        .segment "CODE"

; Jump table at $3000 (16 entries × 3 bytes)
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
        jmp player_decode_row            ; $301E — M5a
        jmp player_init_pattern          ; $3021 — M5b
        jmp player_decode_row_all        ; $3024 — M5b
        jmp player_play_test_tone        ; $3027 — M6-p1
        jmp player_init_song             ; $302A — M6
        jmp player_tick                  ; $302D — M6

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

; =============================================================================
; player_load_pt3(A = base_hi, X = base_lo)
; =============================================================================
; Parse PT3 header. Fills pt3_* BSS struct with absolute pointers.
; Sets pt3_parse_error = 1 on bad file, 0 on success.
;
; Header layout (verified against real files):
;   0x00..0x0C : signature "ProTracker 3." or "Vortex Tracker II"
;   0x0D       : version char ('3'..'9' or other for Vortex)
;   0x63       : tone_table (0..3)
;   0x64       : initial_speed (delay)
;   0x65       : num_positions
;   0x66       : loop_position
;   0x67..0x68 : patterns_ptr (LE, file-relative)
;   0x69..0xA8 : sample_ptrs[32] (each 2 bytes LE, file-relative)
;   0xA9..0xC8 : ornament_ptrs[16] (each 2 bytes LE, file-relative)
;   0xC9..     : position list (num_positions bytes, each = pattern_num*3)
; -----------------------------------------------------------------------------
player_load_pt3:
        ; Store base address: A=hi, X=lo
        sta     pt3_base_hi
        stx     pt3_base_lo

        ; Copy base to ZP for (ZP),y indirect addressing
        stx     ZP_TEMP_LO
        sta     ZP_TEMP_HI

        ; Assume error until proven otherwise
        lda     #1
        sta     pt3_parse_error

        ; --- Sanity check: first 3 bytes = "Pro" or "Vor" ---
        ldy     #0
        lda     (ZP_TEMP_LO),y                  ; byte 0
        cmp     #'P'
        beq     @check_pro
        cmp     #'V'
        beq     @check_vor
        rts                                      ; unknown signature, stay error=1

@check_pro:
        ; Expect "Pro" at 0,1,2
        iny
        lda     (ZP_TEMP_LO),y
        cmp     #'r'
        bne     @bad_sig
        iny
        lda     (ZP_TEMP_LO),y
        cmp     #'o'
        bne     @bad_sig
        ; It's "Pro..." — compute features_level from char at 0x0D
        ldy     #$0D
        lda     (ZP_TEMP_LO),y
        sta     pt3_version_char
        ; '0'..'5' (0x30..0x35) -> level 0
        ; '7'..'9' (0x37..0x39) -> level 2
        ; else ('6' or any other) -> level 1
        cmp     #'6'
        beq     @fl_1
        bcc     @fl_0                            ; < '6' means '0'..'5'
        ; >= '7' ...
        cmp     #':'                             ; ':' = '9'+1 = 0x3A
        bcc     @fl_2                            ; '7','8','9'
        ; fall through: >= ':', treat as level 1
@fl_1:
        lda     #1
        sta     pt3_features_level
        jmp     @parse_body
@fl_0:
        lda     #0
        sta     pt3_features_level
        jmp     @parse_body
@fl_2:
        lda     #2
        sta     pt3_features_level
        jmp     @parse_body

@check_vor:
        ; Expect "Vor" at 0,1,2
        iny
        lda     (ZP_TEMP_LO),y
        cmp     #'o'
        bne     @bad_sig
        iny
        lda     (ZP_TEMP_LO),y
        cmp     #'r'
        bne     @bad_sig
        ; Vortex: version_char = raw byte at 0x0D, features_level = 1
        ldy     #$0D
        lda     (ZP_TEMP_LO),y
        sta     pt3_version_char
        lda     #1
        sta     pt3_features_level
        jmp     @parse_body

@bad_sig:
        rts                                      ; parse_error stays 1

@parse_body:
        ; --- Copy 4 bytes from 0x63..0x66 ---
        ldy     #$63
        lda     (ZP_TEMP_LO),y
        sta     pt3_tone_table
        iny
        lda     (ZP_TEMP_LO),y
        sta     pt3_delay
        iny
        lda     (ZP_TEMP_LO),y
        sta     pt3_num_positions
        iny                                      ; Y = $66
        lda     (ZP_TEMP_LO),y
        sta     pt3_loop_position

        ; --- patterns_ptr: base + file[0x67:0x69] ---
        ldy     #$67
        lda     (ZP_TEMP_LO),y
        clc
        adc     pt3_base_lo
        sta     pt3_patterns_ptr_lo
        iny                                      ; Y = $68
        lda     (ZP_TEMP_LO),y
        adc     pt3_base_hi
        sta     pt3_patterns_ptr_hi

        ; --- sample_table = base + 0x69 ---
        lda     pt3_base_lo
        clc
        adc     #$69
        sta     pt3_sample_table_lo
        lda     pt3_base_hi
        adc     #0
        sta     pt3_sample_table_hi

        ; --- ornament_table = base + 0xA9 ---
        lda     pt3_base_lo
        clc
        adc     #$A9
        sta     pt3_ornament_table_lo
        lda     pt3_base_hi
        adc     #0
        sta     pt3_ornament_table_hi

        ; --- position_list = base + 0xC9 ---
        lda     pt3_base_lo
        clc
        adc     #$C9
        sta     pt3_position_list_lo
        lda     pt3_base_hi
        adc     #0
        sta     pt3_position_list_hi

        ; --- Sanity: num_positions > 0 ---
        lda     pt3_num_positions
        beq     @leave_err                       ; 0 positions -> error stays 1

        ; All good
        lda     #0
        sta     pt3_parse_error
@leave_err:
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
; player_decode_row(A = channel_idx)
; =============================================================================
; Decode next row for given channel from stream in ZP_STREAM_<ch>_LO/HI.
; Fills row_out_ch_<ch> BSS struct with opcodes consumed this row.
; Advances ZP pointer past all consumed bytes (including SPC_CMD params).
;
; Returns A:
;   0   = row decoded successfully
;   1   = end-of-pattern (0x00 at row start, nothing decoded)
;   $FF = truncation (ran out of file data mid-row)
; -----------------------------------------------------------------------------
player_decode_row:
        sta     dec_current_ch

        ; Select ZP stream pointer based on channel_idx.
        ; We use dec_zp_ptr_lo as a VARIABLE holding the ZP base (value $D8/$DA/$DC)
        ; which we then use to address ZP_STREAM via (zp_addr_lo_var),y.
        ; Trick: store the ZP stream pointer address (low byte in ZP is ZP_STREAM_?_LO).
        ; We'll load/store directly using two LDA/STA chains per channel for simplicity.
        ;
        ; The common code reads ZP stream ptr LO/HI via a 2-byte ZP slot at
        ; M5_PTR_LO/hi which we keep synced with the per-channel ZP_STREAM_?_LO/HI.
        ; On entry: copy ZP_STREAM to dec_ptr. On exit: copy dec_ptr back to ZP_STREAM.

        lda     dec_current_ch
        beq     @use_a
        cmp     #1
        beq     @use_b
        ; channel C
        lda     ZP_STREAM_C_LO
        sta     M5_PTR_LO
        lda     ZP_STREAM_C_HI
        sta     M5_PTR_HI
        ; Set up pointer to row_out_ch_c
        lda     #<row_out_ch_c
        sta     M5_OUT_LO
        lda     #>row_out_ch_c
        sta     M5_OUT_HI
        jmp     @have_ptrs
@use_a:
        lda     ZP_STREAM_A_LO
        sta     M5_PTR_LO
        lda     ZP_STREAM_A_HI
        sta     M5_PTR_HI
        lda     #<row_out_ch_a
        sta     M5_OUT_LO
        lda     #>row_out_ch_a
        sta     M5_OUT_HI
        jmp     @have_ptrs
@use_b:
        lda     ZP_STREAM_B_LO
        sta     M5_PTR_LO
        lda     ZP_STREAM_B_HI
        sta     M5_PTR_HI
        lda     #<row_out_ch_b
        sta     M5_OUT_LO
        lda     #>row_out_ch_b
        sta     M5_OUT_HI

@have_ptrs:
        ; Fill row_out with sentinels ($FF for most, 0 for orn_expl_zero, spec_cmd)
        ldy     #0
        lda     #$FF
        sta     (M5_OUT_LO),y       ; +0 row_note
        iny
        sta     (M5_OUT_LO),y       ; +1 row_sample
        iny
        sta     (M5_OUT_LO),y       ; +2 row_env_type
        iny
        sta     (M5_OUT_LO),y       ; +3 row_ornament
        iny
        lda     #0
        sta     (M5_OUT_LO),y       ; +4 row_orn_expl_zero
        iny
        lda     #$FF
        sta     (M5_OUT_LO),y       ; +5 row_volume
        iny
        sta     (M5_OUT_LO),y       ; +6 row_env_period_lo
        iny
        sta     (M5_OUT_LO),y       ; +7 row_env_period_hi
        iny
        sta     (M5_OUT_LO),y       ; +8 row_noise_period
        iny
        lda     #0
        sta     (M5_OUT_LO),y       ; +9 row_spec_cmd
        iny
        sta     (M5_OUT_LO),y       ; +10 row_spec_param0
        iny
        sta     (M5_OUT_LO),y       ; +11 row_spec_param1

        lda     #0
        sta     dec_pending_count

; ---------- Main decode loop: read opcodes until row terminator or $00 ----------
@decode_loop:
        ; Fetch next byte via (dec_ptr),y with y=0
        ldy     #0
        lda     (M5_PTR_LO),y
        ; Advance dec_ptr (16-bit increment)
        inc     M5_PTR_LO
        bne     @no_hi_bump
        inc     M5_PTR_HI
@no_hi_bump:
        ; A = opcode, dispatch by range
        ; Dispatch: $00, $01-$0F, $10, $11-$1F, $20-$3F, $40-$4F,
        ;           $50-$AF (NOTE, row term),
        ;           $B0, $B1, $B2-$BF, $C0, $C1-$CF, $D0, $D1-$EF, $F0-$FF

        cmp     #$50
        bcc     @below_50                ; $00..$4F
        cmp     #$B0
        bcs     @ge_b0
        ; $50..$AF: NOTE
        sec
        sbc     #$50                     ; note = b - $50
        ldy     #0
        sta     (M5_OUT_LO),y       ; row_note = note
        jmp     @row_terminator_reached

@ge_b0:
        cmp     #$C0
        bcs     @ge_c0
        jmp     @range_b0_bf
@ge_c0:
        cmp     #$D0
        bcs     @ge_d0
        jmp     @range_c0_cf
@ge_d0:
        cmp     #$F0
        bcs     @ge_f0
        jmp     @range_d0_ef
@ge_f0:
        jmp     @range_f0_ff

; ---- $00..$4F ----
@below_50:
        cmp     #$10
        bcc     @below_10
        cmp     #$20
        bcc     @range_10_1f
        cmp     #$40
        bcc     @range_20_3f
        jmp     @range_40_4f

@below_10:
        ; A = $00..$0F
        cmp     #$01
        bcs     @range_01_0f
        ; A == $00: END_OF_PATTERN
        jmp     @end_of_pattern

@range_01_0f:
        ; SPC_CMD: queue for post-terminator consumption
        ; We only save first 2 (pending_count capped at 2). Extra silently dropped.
        ldx     dec_pending_count
        cpx     #2
        bcs     @spc_full
        sta     dec_pending_spec0,x
        inx
        stx     dec_pending_count
@spc_full:
        jmp     @decode_loop

@range_10_1f:
        ; PD_ESAM: $10 = env off + 1 sample byte. $11-$1F = env + 2-byte env_period + 1 sample byte.
        cmp     #$10
        bne     @esam_with_period

        ; $10: env explicit OFF, no env_period; sample byte follows
        lda     #$0F
        ldy     #2
        sta     (M5_OUT_LO),y       ; row_env_type = $0F
        jmp     @esam_read_sample

@esam_with_period:
        ; A = $11..$1F; row_env_type = A - $10
        sec
        sbc     #$10
        ldy     #2
        sta     (M5_OUT_LO),y       ; row_env_type

        ; Read env_period (2 bytes BIG-endian: hi first, lo second)
        ldy     #0
        lda     (M5_PTR_LO),y           ; hi byte
        ldy     #7
        sta     (M5_OUT_LO),y       ; row_env_period_hi
        inc     M5_PTR_LO
        bne     @esam_no_bump1
        inc     M5_PTR_HI
@esam_no_bump1:
        ldy     #0
        lda     (M5_PTR_LO),y           ; lo byte
        ldy     #6
        sta     (M5_OUT_LO),y       ; row_env_period_lo
        inc     M5_PTR_LO
        bne     @esam_read_sample
        inc     M5_PTR_HI

@esam_read_sample:
        ; sample byte: row_sample = byte >> 1
        ldy     #0
        lda     (M5_PTR_LO),y
        lsr     a
        ldy     #1
        sta     (M5_OUT_LO),y       ; row_sample
        inc     M5_PTR_LO
        bne     @esam_done
        inc     M5_PTR_HI
@esam_done:
        jmp     @decode_loop

@range_20_3f:
        ; NOISE: row_noise_period = A - $20
        sec
        sbc     #$20
        ldy     #8
        sta     (M5_OUT_LO),y
        jmp     @decode_loop

@range_40_4f:
        ; ORN: $40 = disable ornament (env off + orn_expl_zero). $41-$4F = orn 1..15.
        cmp     #$40
        bne     @orn_nonzero

        ; $40: disable ornament
        ldy     #2
        lda     (M5_OUT_LO),y       ; current row_env_type
        cmp     #$FF                     ; was "no env" ?
        bne     @orn0_no_env_override
        lda     #$0F
        sta     (M5_OUT_LO),y       ; set env off
@orn0_no_env_override:
        lda     #1
        ldy     #4
        sta     (M5_OUT_LO),y       ; row_orn_expl_zero = 1
        jmp     @decode_loop

@orn_nonzero:
        sec
        sbc     #$40
        ldy     #3
        sta     (M5_OUT_LO),y       ; row_ornament
        jmp     @decode_loop

; ---- $B0..$BF ----
@range_b0_bf:
        ; $B0: env off. $B1: SKIP (+1 byte). $B2-$BF: SETENV (+2 bytes env_period).
        cmp     #$B0
        bne     @b0_not
        lda     #$0F
        ldy     #2
        sta     (M5_OUT_LO),y       ; row_env_type
        jmp     @decode_loop
@b0_not:
        cmp     #$B1
        bne     @setenv
        ; SKIP: next byte -> ch_nn_skip_<ch>. M5a stores but doesn't act on it.
        ldy     #0
        lda     (M5_PTR_LO),y
        ldx     dec_current_ch
        sta     ch_nn_skip_a,x
        inc     M5_PTR_LO
        bne     @skip_done
        inc     M5_PTR_HI
@skip_done:
        jmp     @decode_loop

@setenv:
        ; $B2..$BF: row_env_type = (A & $0F) - 1
        and     #$0F
        sec
        sbc     #1
        ldy     #2
        sta     (M5_OUT_LO),y
        ; Read env_period 2-byte BE (hi then lo)
        ldy     #0
        lda     (M5_PTR_LO),y
        ldy     #7
        sta     (M5_OUT_LO),y       ; env_period_hi
        inc     M5_PTR_LO
        bne     @se_bump1_done
        inc     M5_PTR_HI
@se_bump1_done:
        ldy     #0
        lda     (M5_PTR_LO),y
        ldy     #6
        sta     (M5_OUT_LO),y       ; env_period_lo
        inc     M5_PTR_LO
        bne     @se_bump2_done
        inc     M5_PTR_HI
@se_bump2_done:
        jmp     @decode_loop

; ---- $C0..$CF ----
@range_c0_cf:
        cmp     #$C0
        bne     @vol
        ; $C0: RELEASE — row terminator, row_note = $C0
        lda     #$C0
        ldy     #0
        sta     (M5_OUT_LO),y
        jmp     @row_terminator_reached
@vol:
        ; $C1..$CF: row_volume = A - $C0
        sec
        sbc     #$C0
        ldy     #5
        sta     (M5_OUT_LO),y
        jmp     @decode_loop

; ---- $D0..$EF ----
@range_d0_ef:
        cmp     #$D0
        bne     @sample_only
        ; $D0: END_OF_ROW explicit
        jmp     @row_terminator_reached
@sample_only:
        ; $D1..$EF: row_sample = A - $D0
        sec
        sbc     #$D0
        ldy     #1
        sta     (M5_OUT_LO),y
        jmp     @decode_loop

; ---- $F0..$FF ----
@range_f0_ff:
        ; ORN+SAM: orn = A - $F0. env off always. If orn=0: orn_expl_zero=1. Else row_ornament=orn.
        ; Then 1 sample byte: row_sample = byte >> 1.
        and     #$0F
        tax                              ; X = orn
        lda     #$0F
        ldy     #2
        sta     (M5_OUT_LO),y       ; row_env_type = $0F
        cpx     #0
        bne     @orsm_nonzero
        lda     #1
        ldy     #4
        sta     (M5_OUT_LO),y       ; row_orn_expl_zero = 1
        jmp     @orsm_read_sample
@orsm_nonzero:
        txa
        ldy     #3
        sta     (M5_OUT_LO),y       ; row_ornament
@orsm_read_sample:
        ldy     #0
        lda     (M5_PTR_LO),y
        lsr     a
        ldy     #1
        sta     (M5_OUT_LO),y       ; row_sample
        inc     M5_PTR_LO
        bne     @orsm_done
        inc     M5_PTR_HI
@orsm_done:
        jmp     @decode_loop

; ---- Row terminator reached: consume SPC_CMD params ----
@row_terminator_reached:
        ; For each queued SPC_CMD (in dec_pending_spec0..1), consume N params
        ; where N = SPC_CMD_PARAM_BYTES[cmd]. For cmds with >=1 param, store
        ; the first two bytes into row_spec_param0/1; row_spec_cmd = cmd.
        ; Last queued cmd wins (overwrites earlier ones) — matches Python.

        lda     dec_pending_count
        beq     @done_ok

        ; Process first pending spec
        lda     dec_pending_spec0
        jsr     consume_spec_params

        lda     dec_pending_count
        cmp     #2
        bcc     @done_ok

        ; Process second pending spec
        lda     dec_pending_spec1
        jsr     consume_spec_params

@done_ok:
        ; Copy dec_ptr back to ZP_STREAM_<ch>_LO/HI
        lda     dec_current_ch
        beq     @save_a
        cmp     #1
        beq     @save_b
        lda     M5_PTR_LO
        sta     ZP_STREAM_C_LO
        lda     M5_PTR_HI
        sta     ZP_STREAM_C_HI
        lda     #0
        rts
@save_a:
        lda     M5_PTR_LO
        sta     ZP_STREAM_A_LO
        lda     M5_PTR_HI
        sta     ZP_STREAM_A_HI
        lda     #0
        rts
@save_b:
        lda     M5_PTR_LO
        sta     ZP_STREAM_B_LO
        lda     M5_PTR_HI
        sta     ZP_STREAM_B_HI
        lda     #0
        rts

@end_of_pattern:
        ; Save ptr back and return 1
        lda     dec_current_ch
        beq     @eop_save_a
        cmp     #1
        beq     @eop_save_b
        lda     M5_PTR_LO
        sta     ZP_STREAM_C_LO
        lda     M5_PTR_HI
        sta     ZP_STREAM_C_HI
        lda     #1
        rts
@eop_save_a:
        lda     M5_PTR_LO
        sta     ZP_STREAM_A_LO
        lda     M5_PTR_HI
        sta     ZP_STREAM_A_HI
        lda     #1
        rts
@eop_save_b:
        lda     M5_PTR_LO
        sta     ZP_STREAM_B_LO
        lda     M5_PTR_HI
        sta     ZP_STREAM_B_HI
        lda     #1
        rts

; -----------------------------------------------------------------------------
; consume_spec_params(A = cmd)
; Consumes SPC_CMD_PARAM_BYTES[cmd] bytes from dec_ptr.
; Stores first 2 param bytes in row_spec_param0/1. Sets row_spec_cmd = cmd.
; Clobbers A, X, Y.
; -----------------------------------------------------------------------------
consume_spec_params:
        ; Save cmd for writing row_spec_cmd
        sta     dec_spc_cmd_save

        ; Look up param count: SPC_CMD_PARAM_TABLE[cmd]
        tax
        lda     SPC_CMD_PARAM_TABLE,x
        sta     dec_spc_nparam
        beq     @spc_done_write_cmd      ; 0 params, just record cmd

        ; Read up to 2 params, skip any extra
        ; 1st param:
        ldy     #0
        lda     (M5_PTR_LO),y
        ldy     #10
        sta     (M5_OUT_LO),y       ; row_spec_param0
        inc     M5_PTR_LO
        bne     @sp1_no_bump
        inc     M5_PTR_HI
@sp1_no_bump:
        dec     dec_spc_nparam
        beq     @spc_done_write_cmd

        ; 2nd param:
        ldy     #0
        lda     (M5_PTR_LO),y
        ldy     #11
        sta     (M5_OUT_LO),y       ; row_spec_param1
        inc     M5_PTR_LO
        bne     @sp2_no_bump
        inc     M5_PTR_HI
@sp2_no_bump:
        dec     dec_spc_nparam
        beq     @spc_done_write_cmd

        ; Skip remaining params
@skip_extra:
        inc     M5_PTR_LO
        bne     @skip_no_bump
        inc     M5_PTR_HI
@skip_no_bump:
        dec     dec_spc_nparam
        bne     @skip_extra

@spc_done_write_cmd:
        lda     dec_spc_cmd_save
        ldy     #9
        sta     (M5_OUT_LO),y       ; row_spec_cmd
        rts

; =============================================================================
; player_init_pattern(A = pattern_number)
; =============================================================================
; Initialize channel state for playback of the given pattern number.
; Must be called before first player_decode_row_all() of each pattern.
;
; Reads the patterns table at pt3_patterns_ptr_lo/hi to get the 3 file-relative
; stream offsets for channels A/B/C, converts each to absolute by adding
; pt3_base_lo/hi (high byte only; base is always $XX00), and stores them
; in ZP_STREAM_<ch>_LO/HI.
;
; Also resets per-channel state:
;   ch_nn_skip_<ch>        = 1  (default: decode every row)
;   ch_skip_counter_<ch>   = 1  (decode on first tick)
;   ch_end_flag_<ch>       = 0  (not ended)
;
; Clobbers A, X, Y.
; -----------------------------------------------------------------------------
player_init_pattern:
        ; A = pattern_number. We need pat_ptr + pattern_number * 6.
        ; pt3_patterns_ptr_lo/hi is already absolute (M4 converts).

        ; Compute pattern_number * 6 into dec_pat_mul_lo/hi (16-bit).
        sta     dec_pat_mul_lo          ; lo = pattern_number (X6 is small, 16-bit mult)
        lda     #0
        sta     dec_pat_mul_hi

        ; * 6: (*2 + *4) = *6. Or simpler: accumulate 6 times.
        ; For pattern_number up to 85 (max unique patterns per Deater),
        ; 85*6 = 510 = $1FE, fits in 16-bit. Use shift/add: X*6 = X*4 + X*2.
        ; First X*2:
        asl     dec_pat_mul_lo
        rol     dec_pat_mul_hi
        ; Save X*2 in temp
        lda     dec_pat_mul_lo
        sta     dec_pat_x2_lo
        lda     dec_pat_mul_hi
        sta     dec_pat_x2_hi
        ; X*4 = (X*2)*2:
        asl     dec_pat_mul_lo
        rol     dec_pat_mul_hi
        ; X*6 = X*4 + X*2:
        clc
        lda     dec_pat_mul_lo
        adc     dec_pat_x2_lo
        sta     dec_pat_mul_lo
        lda     dec_pat_mul_hi
        adc     dec_pat_x2_hi
        sta     dec_pat_mul_hi

        ; Now pat_entry_addr = pt3_patterns_ptr + pattern_number * 6
        ; Store into M5_PTR_LO/HI as scratch (reused from M5a; safe).
        clc
        lda     pt3_patterns_ptr_lo
        adc     dec_pat_mul_lo
        sta     M5_PTR_LO
        lda     pt3_patterns_ptr_hi
        adc     dec_pat_mul_hi
        sta     M5_PTR_HI

        ; Read 6 bytes: ch_A_lo, ch_A_hi, ch_B_lo, ch_B_hi, ch_C_lo, ch_C_hi.
        ; Each is FILE-RELATIVE; convert to absolute with full 16-bit add of pt3_base.

        ; Channel A:
        ldy     #0
        clc
        lda     (M5_PTR_LO),y           ; ch_A_lo (file-relative)
        adc     pt3_base_lo
        sta     ZP_STREAM_A_LO
        iny
        lda     (M5_PTR_LO),y           ; ch_A_hi (file-relative)
        adc     pt3_base_hi
        sta     ZP_STREAM_A_HI

        ; Channel B:
        iny
        clc
        lda     (M5_PTR_LO),y           ; ch_B_lo
        adc     pt3_base_lo
        sta     ZP_STREAM_B_LO
        iny
        lda     (M5_PTR_LO),y           ; ch_B_hi
        adc     pt3_base_hi
        sta     ZP_STREAM_B_HI

        ; Channel C:
        iny
        clc
        lda     (M5_PTR_LO),y           ; ch_C_lo
        adc     pt3_base_lo
        sta     ZP_STREAM_C_LO
        iny
        lda     (M5_PTR_LO),y           ; ch_C_hi
        adc     pt3_base_hi
        sta     ZP_STREAM_C_HI

        ; Reset per-channel state for all 3 channels.
        lda     #1
        sta     ch_nn_skip_a
        sta     ch_nn_skip_b
        sta     ch_nn_skip_c
        sta     ch_skip_counter_a
        sta     ch_skip_counter_b
        sta     ch_skip_counter_c
        lda     #0
        sta     ch_end_flag_a
        sta     ch_end_flag_b
        sta     ch_end_flag_c
        rts

; =============================================================================
; player_decode_row_all()
; =============================================================================
; Decode one row tick across all 3 channels.
;
; For each channel:
;   1. If ch_end_flag_<ch> set: fill row_out with sentinels, continue.
;   2. Decrement ch_skip_counter_<ch>.
;   3. If skip_counter > 0: fill row_out with sentinels (skipped row), continue.
;   4. Else: call player_decode_row(<ch>).
;      - If A=1 on return: set ch_end_flag_<ch>, fill row_out with sentinels.
;      - If A=0: decode succeeded. Reset ch_skip_counter = ch_nn_skip.
;
; Returns A = number of active channels (not in end_of_pattern state).
; When A=0, pattern is fully exhausted — pattern engine should advance.
;
; Clobbers A, X, Y.
; -----------------------------------------------------------------------------
player_decode_row_all:
        lda     #0
        sta     dec_active_count

        ; --- Channel A ---
        lda     ch_end_flag_a
        beq     @a_live
        ; Ended: fill sentinels and skip
        ldx     #0
        jsr     fill_sentinels_ch
        jmp     @after_a
@a_live:
        dec     ch_skip_counter_a
        beq     @a_decode
        ; Skip counter > 0: this tick is a skip row.
        ldx     #0
        jsr     fill_sentinels_ch
        inc     dec_active_count        ; active but skipping still counts as active
        jmp     @after_a
@a_decode:
        lda     #0
        jsr     player_decode_row       ; returns A=0 ok, A=1 end_of_pattern
        cmp     #1
        beq     @a_eop
        ; decoded OK: reset skip_counter
        lda     ch_nn_skip_a
        sta     ch_skip_counter_a
        inc     dec_active_count
        jmp     @after_a
@a_eop:
        lda     #1
        sta     ch_end_flag_a
        ldx     #0
        jsr     fill_sentinels_ch
@after_a:

        ; --- Channel B ---
        lda     ch_end_flag_b
        beq     @b_live
        ldx     #1
        jsr     fill_sentinels_ch
        jmp     @after_b
@b_live:
        dec     ch_skip_counter_b
        beq     @b_decode
        ldx     #1
        jsr     fill_sentinels_ch
        inc     dec_active_count
        jmp     @after_b
@b_decode:
        lda     #1
        jsr     player_decode_row
        cmp     #1
        beq     @b_eop
        lda     ch_nn_skip_b
        sta     ch_skip_counter_b
        inc     dec_active_count
        jmp     @after_b
@b_eop:
        lda     #1
        sta     ch_end_flag_b
        ldx     #1
        jsr     fill_sentinels_ch
@after_b:

        ; --- Channel C ---
        lda     ch_end_flag_c
        beq     @c_live
        ldx     #2
        jsr     fill_sentinels_ch
        jmp     @after_c
@c_live:
        dec     ch_skip_counter_c
        beq     @c_decode
        ldx     #2
        jsr     fill_sentinels_ch
        inc     dec_active_count
        jmp     @after_c
@c_decode:
        lda     #2
        jsr     player_decode_row
        cmp     #1
        beq     @c_eop
        lda     ch_nn_skip_c
        sta     ch_skip_counter_c
        inc     dec_active_count
        jmp     @after_c
@c_eop:
        lda     #1
        sta     ch_end_flag_c
        ldx     #2
        jsr     fill_sentinels_ch
@after_c:

        lda     dec_active_count
        rts

; -----------------------------------------------------------------------------
; fill_sentinels_ch(X = channel_idx)
; Fill row_out_ch_<X> with sentinels ($FF/0) for a skipped or ended row.
; Clobbers A, Y. Preserves X.
; -----------------------------------------------------------------------------
fill_sentinels_ch:
        ; Select row_out address by channel.
        cpx     #0
        bne     @fs_not_a
        lda     #<row_out_ch_a
        sta     M5_OUT_LO
        lda     #>row_out_ch_a
        sta     M5_OUT_HI
        jmp     @fs_do
@fs_not_a:
        cpx     #1
        bne     @fs_c
        lda     #<row_out_ch_b
        sta     M5_OUT_LO
        lda     #>row_out_ch_b
        sta     M5_OUT_HI
        jmp     @fs_do
@fs_c:
        lda     #<row_out_ch_c
        sta     M5_OUT_LO
        lda     #>row_out_ch_c
        sta     M5_OUT_HI
@fs_do:
        ; 12 bytes: $FF at 0,1,2,3,5,6,7,8 and 0 at 4,9,10,11
        ldy     #0
        lda     #$FF
        sta     (M5_OUT_LO),y       ; +0 note
        iny
        sta     (M5_OUT_LO),y       ; +1 sample
        iny
        sta     (M5_OUT_LO),y       ; +2 env_type
        iny
        sta     (M5_OUT_LO),y       ; +3 ornament
        iny
        lda     #0
        sta     (M5_OUT_LO),y       ; +4 orn_expl_zero
        iny
        lda     #$FF
        sta     (M5_OUT_LO),y       ; +5 volume
        iny
        sta     (M5_OUT_LO),y       ; +6 env_period_lo
        iny
        sta     (M5_OUT_LO),y       ; +7 env_period_hi
        iny
        sta     (M5_OUT_LO),y       ; +8 noise_period
        iny
        lda     #0
        sta     (M5_OUT_LO),y       ; +9 spec_cmd
        iny
        sta     (M5_OUT_LO),y       ; +10 spec_param0
        iny
        sta     (M5_OUT_LO),y       ; +11 spec_param1
        rts

; =============================================================================
; player_play_test_tone()
; =============================================================================
; M6-p1 smoke test: sets AY to generate a pure tone on channel A.
; Writes directly to DigiMuz registers ($FD21/$FD22/$FD23).
;
; AY setup:
;   R0 = $00, R1 = $02   tone period ch A = $0200 (~mid-range C-ish)
;   R2-R5 = 0            tone period ch B/C = 0 (silent if enabled, but masked)
;   R6 = 0               noise period
;   R7 = $3E             mixer: ch A tone enabled, B/C muted
;                        (bit pattern: NC NB NA TC TB TA, 0=enable)
;                        Actually: bit 0 = TA (0 enables ch A tone)
;                                   bit 1 = TB   bit 2 = TC
;                                   bit 3 = NA   bit 4 = NB   bit 5 = NC
;                        $3E = %00111110 = TA enabled, TB/TC/NA/NB/NC disabled
;   R8 = $0F             ch A amplitude = 15 (max), envelope off
;   R9 = 0, R10 = 0      ch B/C amplitudes = 0
;   R11-R13 = 0          envelope period and shape unused
;
; Does NOT require pt3 loaded or player_init. Pure hardware check.
; Clobbers A, X.
; -----------------------------------------------------------------------------
player_play_test_tone:
        ldx     #0
        lda     #$00
        stx     $FD23
        sta     $FD22                    ; R0 = tone A lo
        inx                              ; R1
        lda     #$02
        stx     $FD23
        sta     $FD22                    ; R1 = tone A hi ($0200 period)

        lda     #$00
        ; R2..R6 = 0 (silence B/C tone, noise period 0)
@zero_loop:
        inx                              ; X = 2, 3, 4, 5, 6
        stx     $FD23
        sta     $FD22
        cpx     #6
        bne     @zero_loop

        ; R7 mixer: $3E = enable A tone only
        lda     #7
        sta     $FD23
        lda     #$3E
        sta     $FD22

        ; R8 = $0F max amplitude ch A
        lda     #8
        sta     $FD23
        lda     #$0F
        sta     $FD22

        ; R9, R10 = 0 (ch B, C silent)
        lda     #9
        sta     $FD23
        lda     #0
        sta     $FD22
        lda     #10
        sta     $FD23
        lda     #0
        sta     $FD22

        ; R11, R12, R13 = 0 (no envelope activity)
        lda     #11
        sta     $FD23
        lda     #0
        sta     $FD22
        lda     #12
        sta     $FD23
        lda     #0
        sta     $FD22
        lda     #13
        sta     $FD23
        lda     #0
        sta     $FD22
        rts

; =============================================================================
; M6 — Full playback engine
; =============================================================================
; Entry points:
;   player_init_song(A=hi, X=lo)  — A/X point to PT3 file in RAM
;   player_tick()                  — called once per frame (50/60 Hz)
;
; Must be called after player_init (which builds note/volume tables and
; clears all state). player_init_song performs:
;   1. player_load_pt3   — parse header, populate pt3_* fields
;   2. player_build_note_table / volume_table (if not yet)
;   3. Clear all ch_* and pb_* fields
;   4. Initialize default sample_num=1 per channel
;   5. Load first pattern via player_init_pattern(positions[0]/3)
;   6. Reset pb_tick_in_row, pb_position_idx, pb_current_line, pb_speed
;
; Clobbers A, X, Y.
; -----------------------------------------------------------------------------
player_init_song:
        ; Save A/X for load_pt3 call (A=hi, X=lo per convention).
        pha
        txa
        pha
        ; Clear all M6 state from ch_note_a through pb_cur_env_slide_hi
        jsr     m6_clear_state
        pla
        tax
        pla
        jsr     player_load_pt3
        lda     pt3_parse_error
        beq     @load_ok
        rts                              ; header invalid; caller detects via pt3_parse_error
@load_ok:
        ; Build note table: A = pt3_tone_table, X = version_is_old
        ; Python L194: version_is_old = 1 if pt_version < 4 else 0.
        ; pt3_version_char is ASCII '0'..'9' = $30..$39. version_is_old=1 iff char in '0'..'3'.
        lda     pt3_version_char
        cmp     #$34                    ; '4'
        bcs     @nt_new
        ldx     #1                      ; version_is_old=1 (chars '0'..'3')
        jmp     @nt_call
@nt_new:
        ldx     #0                      ; version_is_old=0 (chars '4'..'9' and others)
@nt_call:
        lda     pt3_tone_table
        jsr     player_build_note_table

        ; Build volume table: A = pt_version. Python L204 hardcodes pt_version=7
        ; (discovered via Foxx-1998 PT3.3 test - VTII uses single new table for all
        ; versions regardless of source file's PT3 version). Match VTII bit-exact.
        lda     #7
        jsr     player_build_volume_table

        ; Set speed from pt3_delay
        lda     pt3_delay
        sta     pb_speed

        ; Default sample = 1 per channel (VTII quirk)
        lda     #1
        sta     ch_sample_num_a
        sta     ch_sample_num_b
        sta     ch_sample_num_c

        ; Default volume = 15 per channel (Python Channel.__init__ L219)
        lda     #15
        sta     ch_volume_a
        sta     ch_volume_b
        sta     ch_volume_c

        ; Note = $FF (no note yet)
        lda     #$FF
        sta     ch_note_a
        sta     ch_note_b
        sta     ch_note_c
        sta     ch_prev_note_a
        sta     ch_prev_note_b
        sta     ch_prev_note_c

        ; pb_env_shape starts at 0 (Python sim line 343: env_shape = 0)
        ; m6_clear_state already zeroed it; this is documentary.

        ; Get first pattern number from position list
        ldy     #0
        sty     pb_position_idx
        sty     pb_current_line
        sty     pb_tick_in_row

        ; Load positions[0] via M5_PTR scratch.
        lda     pt3_position_list_lo
        sta     M5_PTR_LO
        lda     pt3_position_list_hi
        sta     M5_PTR_HI
        ldy     #0
        lda     (M5_PTR_LO),y             ; byte = pattern_num * 3
        ; Divide by 3 — but we don't have /3. M5b expects pattern_num (not *3).
        ; Python: `pat_num = positions[pos_idx] // 3`. We do same.
        jsr     div_by_3
        jsr     player_init_pattern       ; A = pattern_num
        ; Pattern length: default 64 for now (TODO: compute actual)
        lda     #64
        sta     pb_current_pat_len
        rts

; -----------------------------------------------------------------------------
; m6_clear_state: zero all M6 BSS from ch_note_a to pb_cur_env_slide_hi.
; Uses a memset loop based on label arithmetic.
; -----------------------------------------------------------------------------
m6_clear_state:
        ; We'll clear from ch_note_a to pb_cur_env_slide_hi inclusive.
        ; Size = pb_cur_env_slide_hi + 1 - ch_note_a
        lda     #<ch_note_a
        sta     M5_PTR_LO
        lda     #>ch_note_a
        sta     M5_PTR_HI
        ldy     #0
        ldx     #<(pb_cur_env_slide_hi + 1 - ch_note_a)
@loop:
        lda     #0
        sta     (M5_PTR_LO),y
        inc     M5_PTR_LO
        bne     @no_hi
        inc     M5_PTR_HI
@no_hi:
        dex
        bne     @loop
        ; If the range exceeded 256 we'd need a 16-bit count — the range
        ; here is well under 200 bytes, so X suffices.
        rts

; -----------------------------------------------------------------------------
; div_by_3: A /= 3. Uses a lookup table for 0..255 to avoid division loop.
; Returns quotient in A.
; -----------------------------------------------------------------------------
div_by_3:
        ; Position list values are pattern_num*3; pattern_num is 0..85.
        ; So A is in {0, 3, 6, ..., 255}. We can use a small lookup, but
        ; a mul-by-inverse trick works: A * 0x55 / 0x100 ≈ A/3 for small A.
        ; Simpler: repeated subtraction.
        tay                             ; save A
        lda     #0
@sub:
        cpy     #3
        bcc     @done
        tya
        sbc     #3                      ; C=1 from cpy
        tay
        pha
        txa                             ; preserve X? not needed
        pla
        clc
        adc     #1                      ; accumulate quotient
        bne     @sub
@done:
        rts

; -----------------------------------------------------------------------------
; player_tick: called once per 50/60 Hz frame. Does one complete pass of
; the PT3 playback engine and writes 14 AY registers to DigiMuz.
;
; Port of pt3_simulator.simulate() body (one frame iteration).
; -----------------------------------------------------------------------------
player_tick:
        ; Stage 1: sam_env_p = 0
        lda     #0
        sta     pb_sam_env_p

        ; Stage 2: if tick_in_row == 0, decode and apply row for all channels
        lda     pb_tick_in_row
        bne     @no_decode
        jsr     m6_decode_and_apply_row
@no_decode:

        ; Stage 3: per-channel compute (sets shadow_ay R0..R5, R8..R10, accum mixer)
        lda     #0
        sta     m6_tmp_mixer_bits

        lda     #0
        sta     m6_tmp_ch_idx
        jsr     m6_compute_channel
        lda     #1
        sta     m6_tmp_ch_idx
        jsr     m6_compute_channel
        lda     #2
        sta     m6_tmp_ch_idx
        jsr     m6_compute_channel

        ; Stage 4: finalize global registers R6, R7, R11, R12, R13
        ; R6 = (noise_period + sam_noise) & 0x1F
        clc
        lda     pb_noise_period
        adc     pb_sam_noise
        and     #$1F
        sta     shadow_ay + AY_R6_NOISE

        ; R7 = mixer bits
        lda     m6_tmp_mixer_bits
        sta     shadow_ay + AY_R7_MIXER

        ; R11/R12 = (env_period + cur_env_slide + sam_env_p_signed) & 0xFFFF
        ; sam_env_p_signed: if pb_sam_env_p < 0x80 then pb_sam_env_p else pb_sam_env_p - 0x100.
        ; In two's complement, sign-extend pb_sam_env_p as signed 8-bit:
        ;   high byte = 0 if pb_sam_env_p < 0x80, else 0xFF.
        ; Sum: env_period (16-bit) + cur_env_slide (16-bit signed) + sam_env_p_se (16-bit signed).
        ; Build sam_env_p_signed_hi in m6_tmp_amp temporarily.
        lda     pb_sam_env_p
        bpl     @sep_pos
        lda     #$FF
        bne     @sep_done
@sep_pos:
        lda     #0
@sep_done:
        sta     m6_tmp_amp                  ; sam_env_p high byte (sign extension)

        ; env_final = env_period + cur_env_slide + sam_env_p_se
        clc
        lda     pb_env_period_lo
        adc     pb_cur_env_slide_lo
        sta     shadow_ay + AY_R11_ENV_LO
        lda     pb_env_period_hi
        adc     pb_cur_env_slide_hi
        sta     shadow_ay + AY_R12_ENV_HI
        clc
        lda     shadow_ay + AY_R11_ENV_LO
        adc     pb_sam_env_p
        sta     shadow_ay + AY_R11_ENV_LO
        lda     shadow_ay + AY_R12_ENV_HI
        adc     m6_tmp_amp                  ; sign-extension high byte
        sta     shadow_ay + AY_R12_ENV_HI

        ; R13 = env_shape (sentinel $FF = no write).
        ; In Python the write happens unconditionally. We do the same; R13 will be
        ; $FF for frames 0 until any setenv opcode runs. This is fine — VTII output
        ; emits $FF too in those cases. (Actually no: VTII emits 0 initially. We'll
        ; need to ensure pb_env_shape starts at 0 in init_song.)
        lda     pb_env_shape
        sta     shadow_ay + AY_R13_ENV_SHAPE

        ; Stage 5: envslide countdown
        lda     pb_cur_env_delay
        beq     @no_envslide
        dec     pb_cur_env_delay
        bne     @no_envslide
        ; cur_env_delay just hit 0: reload + add slide
        lda     pb_env_delay
        sta     pb_cur_env_delay
        clc
        lda     pb_cur_env_slide_lo
        adc     pb_env_slide_add_lo
        sta     pb_cur_env_slide_lo
        lda     pb_cur_env_slide_hi
        adc     pb_env_slide_add_hi
        sta     pb_cur_env_slide_hi
@no_envslide:

        ; Stage 6: write 14 AY registers to DigiMuz ($FD22/$FD23)
        jsr     m6_write_ay_regs

        ; Stage 7: advance tick_in_row
        inc     pb_tick_in_row
        lda     pb_tick_in_row
        cmp     pb_speed
        bcc     @tick_done
        lda     #0
        sta     pb_tick_in_row
@tick_done:
        rts

; =============================================================================
; m6_write_ay_regs — write all 14 shadow_ay bytes to DigiMuz
; =============================================================================
; Sequence: STX $FD23 (select reg) then STA $FD22 (write data) per register.
; Uses X as register index 0..13.
; -----------------------------------------------------------------------------
m6_write_ay_regs:
        ldx     #0
@loop:
        stx     DIGIMUZ_REG_SEL
        lda     shadow_ay,x
        sta     DIGIMUZ_DATA_W
        inx
        cpx     #14
        bne     @loop
        rts

; =============================================================================
; m6_decode_and_apply_row — Stage 2 of player_tick
; =============================================================================
; Port of simulate() lines 386-490 (the `if tick_in_row == 0` block).
;
; Logic:
;   if current_line >= current_pat_len: mark all channels end_of_pattern
;   for attempt = 0..1:
;       all_decoded = True
;       for ci = 0..2:
;           if channel decoded already this row: continue
;           if channel end_of_pattern: continue (and all_decoded keeps False indirectly)
;           skip_counter--
;           if skip_counter > 0: mark decoded; continue
;           call player_decode_row (M5a, returns A=0 ok / A=1 eop)
;           if eop: continue (will trigger pattern advance)
;           else: apply_row_to_channel; consume row spec_cmd / env_period / noise_period
;       if all decoded: current_line++; break
;       if all end_of_pattern: position_idx++; load next pattern; retry
;       else: break (some channels stuck; rare)
; -----------------------------------------------------------------------------
m6_decode_and_apply_row:
        ; Reset attempt counter (used by pattern-advance retry)
        lda     #0
        sta     ZP_SCRATCH3
        ; current_line >= current_pat_len ?
        lda     pb_current_line
        cmp     pb_current_pat_len
        bcc     @inrange
        ; Out of range: mark all channels end_of_pattern
        lda     #1
        sta     ch_end_flag_a
        sta     ch_end_flag_b
        sta     ch_end_flag_c
@inrange:
        ; decoded_this_tick[3] = {0,0,0}
        lda     #0
        sta     m6_decoded
        sta     m6_decoded+1
        sta     m6_decoded+2

        ldx     #0                          ; attempt counter
@attempt_loop:
        ; Try each channel in turn
        lda     #0
        sta     m6_tmp_ch_idx
@ch_loop:
        ; Already decoded?
        ldx     m6_tmp_ch_idx
        lda     m6_decoded,x
        bne     @next_ch
        ; End of pattern?
        lda     ch_end_flag_a,x
        bne     @next_ch
        ; Decrement skip counter
        dec     ch_skip_counter_a,x
        lda     ch_skip_counter_a,x
        beq     @do_decode
        ; skip_counter > 0: mark decoded, no actual decode needed
        lda     #1
        sta     m6_decoded,x
        jmp     @next_ch
@do_decode:
        ; Call player_decode_row(A=ch_idx). Returns A=0 ok, A=1 eop.
        txa
        jsr     player_decode_row
        cmp     #1
        beq     @next_ch                    ; eop: don't mark decoded, retry next attempt
        ; Decoded row OK. Apply row to channel state.
        ldx     m6_tmp_ch_idx
        lda     #1
        sta     m6_decoded,x                ; mark decoded
        ; Reset skip_counter to nn_skip
        lda     ch_nn_skip_a,x
        sta     ch_skip_counter_a,x
        ; apply_row_to_channel(ch, row, mod): consume row_out_ch_<x>
        jsr     m6_apply_row_to_channel
        ; Apply env_period / env_shape / noise_period from row
        jsr     m6_apply_row_globals
        ; Apply spec_cmd
        jsr     m6_apply_row_spec_cmd
@next_ch:
        ldx     m6_tmp_ch_idx
        inx
        stx     m6_tmp_ch_idx
        cpx     #3
        bne     @ch_loop

        ; All channels decoded?
        lda     m6_decoded
        and     m6_decoded+1
        and     m6_decoded+2
        beq     @not_all_decoded
        ; All decoded: current_line++; done
        inc     pb_current_line
        rts
@not_all_decoded:
        ; If all channels at end_of_pattern, advance position
        lda     ch_end_flag_a
        and     ch_end_flag_b
        and     ch_end_flag_c
        beq     @some_stuck
        ; All ended: load next pattern
        jsr     m6_advance_position
        ; After advance, retry decode (one more attempt)
        inc     m6_tmp_ch_idx               ; placeholder - reuse as attempt counter
        ; Actually we need a real attempt counter. Use scratch.
        ; Bail out: re-zero decoded[] and re-loop (limit 2 attempts)
        cpx     #1                          ; X holds attempt counter? lost above.
        ; We'll use ZP_SCRATCH3 for the attempt counter.
        lda     ZP_SCRATCH3
        cmp     #1
        bcs     @bail
        inc     ZP_SCRATCH3
        ; reset decoded[] and re-loop
        lda     #0
        sta     m6_decoded
        sta     m6_decoded+1
        sta     m6_decoded+2
        jmp     @attempt_loop
@some_stuck:
@bail:
        ; Some channels stuck (rare malformed). Force current_line++ to make progress.
        inc     pb_current_line
        rts

; =============================================================================
; m6_advance_position — advance position_idx, wrap to loop_pos, load pattern
; =============================================================================
; Sets pb_end_of_song flag if wrapped. Loads new pattern via player_init_pattern.
; Resets current_line to 0, pb_noise_period to 0 (per VTII semantics).
; -----------------------------------------------------------------------------
m6_advance_position:
        inc     pb_position_idx
        lda     pb_position_idx
        cmp     pt3_num_positions
        bcc     @no_wrap
        ; Wrap to loop_pos
        lda     pt3_loop_position
        sta     pb_position_idx
        lda     #1
        sta     pb_end_of_song
@no_wrap:
        ; Read positions[position_idx] via M5_PTR
        lda     pt3_position_list_lo
        sta     M5_PTR_LO
        lda     pt3_position_list_hi
        sta     M5_PTR_HI
        ldy     pb_position_idx
        lda     (M5_PTR_LO),y               ; pat_num * 3
        jsr     div_by_3
        jsr     player_init_pattern
        ; Reset state
        lda     #0
        sta     pb_current_line
        sta     pb_noise_period
        ; player_init_pattern already cleared end_flag_* and reset skip_counter_*
        rts

; =============================================================================
; m6_apply_row_to_channel — port of apply_row_to_channel (Python L867-924)
; =============================================================================
; Reads row_out_ch_<X> at m6_tmp_ch_idx, applies fields to ch_*_<x>.
;
; Row layout (12 bytes per channel, set by M5a player_decode_row):
;   0: note ($FF=none, $C0=release, else 0..95)
;   1: sample ($FF=none, else 1..31)
;   2: env_type ($FF=none, 0..15)
;   3: ornament ($FF=none, else 0..15)
;   4: orn_explicit_zero (0/1)
;   5: volume ($FF=none, else 0..15)
;   6,7: env_period (LE; $FFFF=none)
;   8: noise_period ($FF=none)
;   9,10,11: spec_cmd
; -----------------------------------------------------------------------------
m6_apply_row_to_channel:
        ; Set up M5_PTR to row_out_ch_<X>
        ldx     m6_tmp_ch_idx
        cpx     #0
        bne     @rb
        lda     #<row_out_ch_a
        sta     M5_PTR_LO
        lda     #>row_out_ch_a
        sta     M5_PTR_HI
        jmp     @rdone
@rb:
        cpx     #1
        bne     @rc
        lda     #<row_out_ch_b
        sta     M5_PTR_LO
        lda     #>row_out_ch_b
        sta     M5_PTR_HI
        jmp     @rdone
@rc:
        lda     #<row_out_ch_c
        sta     M5_PTR_LO
        lda     #>row_out_ch_c
        sta     M5_PTR_HI
@rdone:

        ; --- note ---
        ldy     #0
        lda     (M5_PTR_LO),y
        cmp     #$FF
        beq     @no_note
        cmp     #$C0
        bne     @real_note
        ; release: set note_released flag, keep ch.note value
        ldx     m6_tmp_ch_idx
        lda     ch_flags_a,x
        ora     #%00000010                  ; bit1 = note_released
        sta     ch_flags_a,x
        jmp     @after_note
@real_note:
        ; New note triggered. Save prev_note, set note. Reset sample/orn position.
        ; Save Current_Ton_Sliding before reset (for FeaturesLevel >= 1 portamento).
        ldx     m6_tmp_ch_idx
        lda     ch_cur_ton_slide_a_lo,x
        sta     ch_saved_ton_slide_a_lo,x
        lda     ch_cur_ton_slide_a_hi,x
        sta     ch_saved_ton_slide_a_hi,x

        lda     ch_note_a,x
        sta     ch_prev_note_a,x
        ldy     #0
        lda     (M5_PTR_LO),y
        sta     ch_note_a,x
        ; Clear release/sound_enabled flags; set enabled.
        lda     ch_flags_a,x
        and     #%11110100                  ; clear bits 0,1 (released)? actually:
                                            ; bit0=enabled, bit1=released, bit2=env_enabled, bit3=sound_enabled
                                            ; mask &= ~bit1 (clear released), set bit0 (enabled), set bit3 (sound_enabled)
        ora     #%00001001                  ; set bits 0 and 3
        sta     ch_flags_a,x
        ; Reset sample/ornament position
        lda     #0
        sta     ch_pos_in_sample_a,x
        sta     ch_pos_in_ornament_a,x
        sta     ch_amp_slide_a,x
        sta     ch_ton_accum_a_lo,x
        sta     ch_ton_accum_a_hi,x
        sta     ch_env_sliding_a_lo,x
        sta     ch_env_sliding_a_hi,x
        sta     ch_noise_sliding_a,x
        sta     ch_cur_ton_slide_a_lo,x
        sta     ch_cur_ton_slide_a_hi,x
        sta     ch_ton_sld_count_a,x      ; <-- typo in BSS? check
        ; Clear ton slide as well? Python reset_sample_ornament zeroes pos_in_sample/ornament
        ; and amp_slide_accum/ton_accumulator/current_envelope_sliding/current_noise_sliding.
        ; ton_slide_* are NOT reset here (they belong to effect setup, not note trigger).
@no_note:
@after_note:

        ; --- sample ---
        ldy     #1
        lda     (M5_PTR_LO),y
        cmp     #$FF
        beq     @no_sample
        ldx     m6_tmp_ch_idx
        sta     ch_sample_num_a,x
@no_sample:

        ; --- ornament ---
        ldy     #3
        lda     (M5_PTR_LO),y
        cmp     #$FF
        beq     @no_orn
        ldx     m6_tmp_ch_idx
        sta     ch_ornament_num_a,x
        lda     #0
        sta     ch_pos_in_ornament_a,x
        jmp     @after_orn
@no_orn:
        ; orn_expl_zero?
        ldy     #4
        lda     (M5_PTR_LO),y
        beq     @after_orn
        ldx     m6_tmp_ch_idx
        lda     #0
        sta     ch_ornament_num_a,x
        sta     ch_pos_in_ornament_a,x
@after_orn:

        ; --- volume ---
        ldy     #5
        lda     (M5_PTR_LO),y
        cmp     #$FF
        beq     @no_vol
        ldx     m6_tmp_ch_idx
        sta     ch_volume_a,x
@no_vol:

        ; --- env_type ---
        ; Python: if row.env_type == 0xF: envelope_enabled=False; else: envelope_enabled=True
        ldy     #2
        lda     (M5_PTR_LO),y
        cmp     #$FF
        beq     @no_env_type
        cmp     #$0F
        beq     @env_off
        ; envelope_enabled = True (set bit2 of flags)
        ldx     m6_tmp_ch_idx
        lda     ch_flags_a,x
        ora     #%00000100
        sta     ch_flags_a,x
        jmp     @no_env_type
@env_off:
        ldx     m6_tmp_ch_idx
        lda     ch_flags_a,x
        and     #%11111011
        sta     ch_flags_a,x
@no_env_type:
        rts

; -----------------------------------------------------------------------------
; m6_apply_row_globals — apply row.env_period, row.env_type→pb_env_shape,
; row.noise_period to global state (NOT per-channel).
; Also resets cur_env_slide/cur_env_delay if env_type in 1..14 (Python L412-417).
; -----------------------------------------------------------------------------
m6_apply_row_globals:
        ; Set M5_PTR to row_out_ch_<X> (already set by apply_row? Could reuse, but
        ; to be safe re-set it).
        ldx     m6_tmp_ch_idx
        cpx     #0
        bne     @rgb
        lda     #<row_out_ch_a
        sta     M5_PTR_LO
        lda     #>row_out_ch_a
        sta     M5_PTR_HI
        jmp     @rgdone
@rgb:
        cpx     #1
        bne     @rgc
        lda     #<row_out_ch_b
        sta     M5_PTR_LO
        lda     #>row_out_ch_b
        sta     M5_PTR_HI
        jmp     @rgdone
@rgc:
        lda     #<row_out_ch_c
        sta     M5_PTR_LO
        lda     #>row_out_ch_c
        sta     M5_PTR_HI
@rgdone:

        ; env_period (offsets 6,7) — $FFFF = none
        ldy     #6
        lda     (M5_PTR_LO),y
        sta     m6_tmp_amp                  ; tmp lo
        iny
        lda     (M5_PTR_LO),y
        sta     m6_tmp_note                 ; tmp hi
        cmp     #$FF
        bne     @ep_set
        lda     m6_tmp_amp
        cmp     #$FF
        beq     @no_envp
@ep_set:
        lda     m6_tmp_amp
        sta     pb_env_period_lo
        lda     m6_tmp_note
        sta     pb_env_period_hi
@no_envp:

        ; env_type 1..14 → pb_env_shape, reset cur_env_slide / cur_env_delay
        ldy     #2
        lda     (M5_PTR_LO),y
        cmp     #$FF
        beq     @no_es
        cmp     #1
        bcc     @no_es
        cmp     #15
        bcs     @no_es
        sta     pb_env_shape
        lda     #0
        sta     pb_cur_env_slide_lo
        sta     pb_cur_env_slide_hi
        sta     pb_cur_env_delay
@no_es:

        ; noise_period (offset 8)
        ldy     #8
        lda     (M5_PTR_LO),y
        cmp     #$FF
        beq     @no_np
        sta     pb_noise_period
@no_np:
        rts

; -----------------------------------------------------------------------------
; m6_apply_row_spec_cmd — port of Python spec_cmd dispatch (L440-555).
; Reads row_out_ch_<X> offsets 9,10,11 (cmd, param0, param1).
;
; M6 implements: cmd 0x09 (speed), 0x03 (smpos), 0x04 (orpos), 0x05 (vibrato),
; 0x08 (envslide). cmd 0x01 (gliss) and 0x02 (portm) need 3 and 5 raw bytes
; respectively but row_out only has 2 param bytes — must read directly from
; ZP_STREAM minus offset (M5a stored only first 2 bytes). For now, defer:
; gliss/portamento not yet supported until row_out is extended.
; -----------------------------------------------------------------------------
m6_apply_row_spec_cmd:
        ; M5_PTR already points to row_out
        ldy     #9
        lda     (M5_PTR_LO),y
        bne     @have_cmd
        rts
@have_cmd:
        sta     m6_tmp_amp                  ; cmd
        iny
        lda     (M5_PTR_LO),y
        sta     m6_tmp_note                 ; param0
        iny
        lda     (M5_PTR_LO),y
        sta     m6_tmp_tone_lo              ; param1

        lda     m6_tmp_amp
        cmp     #$09
        bne     @not_spd
        ; Speed change: param0 must be non-zero
        lda     m6_tmp_note
        beq     @no_cmd
        sta     pb_speed
        rts
@not_spd:
        cmp     #$03
        bne     @not_smpos
        ; Sample position: pos_in_sample = param0
        lda     m6_tmp_note
        ldx     m6_tmp_ch_idx
        sta     ch_pos_in_sample_a,x
        rts
@not_smpos:
        cmp     #$04
        bne     @not_orpos
        ; Ornament position: pos_in_ornament = param0
        lda     m6_tmp_note
        ldx     m6_tmp_ch_idx
        sta     ch_pos_in_ornament_a,x
        rts
@not_orpos:
        cmp     #$05
        bne     @not_vib
        ; Vibrato: parameter = (param0 << 4) | param1
        ; offon_delay = param & 0x0F = param1 (low nibble of combined)
        ; onoff_delay = (param >> 4) & 0x0F = param0 low nibble
        ; current_onoff = onoff_delay
        lda     m6_tmp_tone_lo              ; param1 (low nibble target)
        and     #$0F
        ldx     m6_tmp_ch_idx
        sta     ch_offon_delay_a,x
        lda     m6_tmp_note                 ; param0
        and     #$0F
        sta     ch_onoff_delay_a,x
        sta     ch_current_onoff_a,x
        lda     #0
        sta     ch_ton_sld_count_a,x
        sta     ch_cur_ton_slide_a_lo,x
        sta     ch_cur_ton_slide_a_hi,x
        rts
@not_vib:
        cmp     #$08
        bne     @no_cmd
        ; Envslide: cur_env_delay = param0; env_slide_add = signed16(param1, ...)
        ; row_out only has 2 params; M5a stored param0=delay, param1=amount_lo. amount_hi
        ; was lost. For sign-extend we approximate from sign of param1 — incorrect for
        ; magnitude > 127. TODO: extend row_out to carry 3rd byte of spec_cmd raw.
        lda     m6_tmp_note                 ; delay
        sta     pb_env_delay
        sta     pb_cur_env_delay
        lda     m6_tmp_tone_lo              ; amount_lo
        sta     pb_env_slide_add_lo
        bpl     @es_pos
        lda     #$FF
        sta     pb_env_slide_add_hi
        rts
@es_pos:
        lda     #0
        sta     pb_env_slide_add_hi
@no_cmd:
        rts

; =============================================================================
; m6_compute_channel — Stage 3 per-channel compute (Python L587-815)
; =============================================================================
; Input: m6_tmp_ch_idx (0/1/2)
; Output: shadow_ay R0..R5 (tone period), R8/R9/R10 (amplitude),
;         m6_tmp_mixer_bits (accumulated)
; Side effects: advances ch_pos_in_sample, ch_pos_in_ornament,
;               runs ton_slide / vibrato countdowns.
;
; STUB FOR NOW — outputs zeros so harness can sanity-check Stage 4 path.
; -----------------------------------------------------------------------------
; -----------------------------------------------------------------------------
; m6_get_sample_tick_ptr — point ZP_SAMPLE_BASE_LO/HI at the current sample
; tick (4 bytes) for channel m6_tmp_ch_idx.
;
; Computes:
;   sample_addr = pt3_base + word_at(pt3_sample_table + sample_num*2)
;   tick_addr = sample_addr + 2 + pos_in_sample * 4
;
; Returns A=0 if no sample (sample_num=0 or table entry is zero).
; Otherwise A=1 and ZP_SAMPLE_BASE_LO/HI points at byte0 of the tick.
; -----------------------------------------------------------------------------
m6_get_sample_tick_ptr:
        ldx     m6_tmp_ch_idx
        lda     ch_sample_num_a,x
        bne     @have_samp
        lda     #0
        rts
@have_samp:
        ; sample_num × 2 → table offset
        asl     a
        tay
        ; Read pt3_sample_table[Y] (file-relative LE)
        lda     pt3_sample_table_lo
        sta     M5_PTR_LO
        lda     pt3_sample_table_hi
        sta     M5_PTR_HI
        lda     (M5_PTR_LO),y                ; lo byte of file-relative ptr
        sta     ZP_SAMPLE_BASE_LO
        iny
        lda     (M5_PTR_LO),y
        sta     ZP_SAMPLE_BASE_HI
        ; Convert file-relative to absolute by adding pt3_base
        clc
        lda     ZP_SAMPLE_BASE_LO
        adc     pt3_base_lo
        sta     ZP_SAMPLE_BASE_LO
        lda     ZP_SAMPLE_BASE_HI
        adc     pt3_base_hi
        sta     ZP_SAMPLE_BASE_HI
        ; Add 2 (skip header loop_pos + length)
        clc
        lda     ZP_SAMPLE_BASE_LO
        adc     #2
        sta     ZP_SAMPLE_BASE_LO
        bcc     @no_carry
        inc     ZP_SAMPLE_BASE_HI
@no_carry:
        ; Add pos_in_sample × 4
        ldx     m6_tmp_ch_idx
        lda     ch_pos_in_sample_a,x
        asl     a
        rol     m6_tmp_amp                   ; high byte of *4 (overflow goes here)
        asl     a
        rol     m6_tmp_amp
        ; Result: A = (pos*4) low, m6_tmp_amp = (pos*4) high
        ; pos_in_sample is 0..63 typically, so pos*4 fits in 8 bits but be safe
        clc
        adc     ZP_SAMPLE_BASE_LO
        sta     ZP_SAMPLE_BASE_LO
        lda     m6_tmp_amp
        adc     ZP_SAMPLE_BASE_HI
        sta     ZP_SAMPLE_BASE_HI
        lda     #1
        rts

; -----------------------------------------------------------------------------
; m6_get_ornament_offset — return signed ornament offset for channel.
; Input: m6_tmp_ch_idx
; Output: A = offset (signed 8-bit), or 0 if no ornament active.
; Sets m6_tmp_orn_ptr_lo/hi to ornament header for use by position advance.
; -----------------------------------------------------------------------------
m6_get_ornament_offset:
        ldx     m6_tmp_ch_idx
        lda     ch_ornament_num_a,x
        bne     @have_orn
        lda     #0
        rts
@have_orn:
        ; orn_addr = pt3_base + word_at(pt3_ornament_table + orn_num*2)
        asl     a
        tay
        lda     pt3_ornament_table_lo
        sta     M5_PTR_LO
        lda     pt3_ornament_table_hi
        sta     M5_PTR_HI
        lda     (M5_PTR_LO),y
        sta     ZP_ORN_BASE_LO
        iny
        lda     (M5_PTR_LO),y
        sta     ZP_ORN_BASE_HI
        clc
        lda     ZP_ORN_BASE_LO
        adc     pt3_base_lo
        sta     ZP_ORN_BASE_LO
        lda     ZP_ORN_BASE_HI
        adc     pt3_base_hi
        sta     ZP_ORN_BASE_HI
        ; Save header pointer (loop_pos + length at offset 0,1)
        lda     ZP_ORN_BASE_LO
        sta     m6_tmp_orn_ptr_lo
        lda     ZP_ORN_BASE_HI
        sta     m6_tmp_orn_ptr_hi
        ; Skip header (2 bytes), index by pos_in_ornament
        clc
        adc     #0                           ; preserve flags? no, prevous lda was hi byte
        ; Actually load the value:
        ;   value = byte_at(orn_addr + 2 + pos_in_ornament)
        ldx     m6_tmp_ch_idx
        lda     ch_pos_in_ornament_a,x
        clc
        adc     #2
        tay
        lda     (ZP_ORN_BASE_LO),y
        rts

; =============================================================================
; m6_compute_channel — port of Python simulate() L580-815 per-channel block
; =============================================================================
; Input: m6_tmp_ch_idx (0/1/2)
;
; Phases:
;   A. Branch on ch.flags:
;        - bit0 enabled clear OR ch.note == $FF: amp=0 tone=0 (init silence)
;        - bit1 released set: amp=0 tone=skip (keep prev), continue advance
;        - bit3 sound_enabled clear (vibrato muted): amp=0 tone=skip,
;          run ton_slide+vibrato countdowns, advance NOTHING
;        - else: full computation
;   B. Full computation (the "else" branch, ~150 lines):
;        - orn_offset via m6_get_ornament_offset
;        - effective_note = clamp(ch.note + orn_offset, 0..95)
;        - base_period = note_table[effective_note]
;        - sample tick fetch via m6_get_sample_tick_ptr
;        - sample_tone_offset = ton_accum + tick.tone_offset
;          if tone_accumulate: ton_accum = sample_tone_offset
;        - noise/env sliding (sticky pb_sam_noise / pb_sam_env_p)
;        - amp slide (if byte0 bit7)
;        - effective_vol = sample_volume + amp_slide_accum, clamp
;        - combined_vol = volume_table[(ch.volume<<4) | effective_vol]
;        - amp_reg = combined_vol | (env_enabled & sample_env_on ? 0x10 : 0)
;        - mixer bits (T disable bit ci, N disable bit ci+3)
;        - tone_period = (base_period + sample_tone_offset + cur_ton_slide) & 0xFFF
;   C. Write tone_period to AY (R0..R5 by ch).
;   D. Write amp_reg to AY (R8..R10 by ch).
;   E. Run ton_slide countdown + vibrato countdown.
;   F. Advance pos_in_sample / pos_in_ornament (only if sound_enabled & not released).
; -----------------------------------------------------------------------------
m6_compute_channel:
        ; ===== Phase A: branch on flags =====
        ldx     m6_tmp_ch_idx
        lda     ch_flags_a,x
        and     #%00000001                   ; bit0 = enabled
        bne     @maybe_active
        ; Channel never played: amp=0, tone=0
        jmp     @write_silence

@maybe_active:
        ; Check ch.note != $FF (if note still $FF, treat as never played)
        lda     ch_note_a,x
        cmp     #$FF
        bne     @check_released
        jmp     @write_silence

@check_released:
        lda     ch_flags_a,x
        and     #%00000010                   ; bit1 = released
        beq     @check_sound
        ; Released: amp=0, tone=skip (keep prev), still advance sample/orn
        lda     #0
        sta     m6_tmp_amp
        ; Skip tone_period write — handled by branching to @write_amp_only_advance
        jmp     @released_branch

@check_sound:
        lda     ch_flags_a,x
        and     #%00001000                   ; bit3 = sound_enabled
        bne     @full_compute
        ; sound_enabled clear (vibrato muted): amp=0, tone=skip, run countdowns only
        lda     #0
        sta     m6_tmp_amp
        jmp     @vibrato_muted_branch

@write_silence:
        ; Tone period regs ci*2, ci*2+1 = 0
        ldx     m6_tmp_ch_idx
        txa
        asl     a
        tay
        lda     #0
        sta     shadow_ay,y
        iny
        sta     shadow_ay,y
        ; Amp reg 8+ci = 0
        txa
        clc
        adc     #8
        tay
        lda     #0
        sta     shadow_ay,y
        rts

; ===== Phase B: full computation =====
@full_compute:
        ; --- Compute ornament offset ---
        jsr     m6_get_ornament_offset
        sta     m6_tmp_amp                   ; orn_offset (signed)

        ; --- effective_note = clamp(ch.note + orn_offset, 0..95) ---
        ldx     m6_tmp_ch_idx
        clc
        lda     ch_note_a,x
        adc     m6_tmp_amp                   ; signed add
        ; Clamp to 0..95. After signed add, A may be:
        ;   - negative (>=$80): clamp to 0
        ;   - >95: clamp to 95
        bpl     @check_high
        lda     #0
        jmp     @en_done
@check_high:
        cmp     #96
        bcc     @en_done
        lda     #95
@en_done:
        ; A = effective_note. Index into note_table (2 bytes per entry).
        asl     a                            ; *2
        tay
        lda     note_table,y
        sta     m6_tmp_tone_lo               ; base_period lo
        iny
        lda     note_table,y
        sta     m6_tmp_tone_hi               ; base_period hi

        ; --- Initialize defaults: sample_volume=$F, T=on, N=off, env=off ---
        lda     #$0F
        sta     m6_tmp_note                  ; alias: sample_volume
        ; Mixer disable bits stored in X temporarily? Use ZP_SCRATCH1 = sample_t_off (bit set if tone OFF)
        ; ZP_SCRATCH2 = sample_n_off
        ; ZP_SCRATCH3 = sample_env_on
        lda     #0
        sta     ZP_SCRATCH1                  ; tone_off
        lda     #1
        sta     ZP_SCRATCH2                  ; noise_off (default no noise = off)
        lda     #0
        sta     ZP_SCRATCH3                  ; env_on
        sta     m6_tmp_sample_ptr_lo         ; tone_offset lo (signed 16-bit accumulator)
        sta     m6_tmp_sample_ptr_hi         ; tone_offset hi

        ; --- Fetch sample tick ---
        jsr     m6_get_sample_tick_ptr
        bne     @have_sample
        jmp     @no_sample_data
@have_sample:
        ; ZP_SAMPLE_BASE_LO/HI now points at byte0 of the tick (4 bytes).

        ; byte0 → noise/envelope slide path + amp slide
        ldy     #0
        lda     (ZP_SAMPLE_BASE_LO),y
        sta     m6_tmp_row_ptr_lo            ; alias: sample_byte0
        iny
        lda     (ZP_SAMPLE_BASE_LO),y
        sta     m6_tmp_row_ptr_hi            ; alias: sample_byte1

        ; sample_volume = byte1 & 0x0F
        and     #$0F
        sta     m6_tmp_note

        ; Per Python decode_sample (pt3_sample_decoder.py L99-104):
        ;   hi_nibble = (b1 >> 4) & 0xF
        ;   tone_off  = hi_nibble & 0x1   = bit 4 of byte1
        ;   noise_off = hi_nibble & 0x8   = bit 7 of byte1
        ; Note: bit 7 also drives "envelope slide route" later (Python L692).
        lda     m6_tmp_row_ptr_hi
        and     #$10                         ; bit 4 = tone_off
        beq     @t_on
        lda     #1
        sta     ZP_SCRATCH1
@t_on:
        lda     m6_tmp_row_ptr_hi
        and     #$80                         ; bit 7 = noise_off
        beq     @n_on
        lda     #1
        sta     ZP_SCRATCH2
        jmp     @n_done
@n_on:
        lda     #0
        sta     ZP_SCRATCH2
@n_done:
        ; sample_env_on = NOT (byte0 bit0)
        lda     m6_tmp_row_ptr_lo
        and     #$01
        beq     @env_on
        lda     #0
        sta     ZP_SCRATCH3
        jmp     @env_done
@env_on:
        lda     #1
        sta     ZP_SCRATCH3
@env_done:

        ; tone_offset (signed 16-bit) = byte2 | (byte3 << 8)
        ldy     #2
        lda     (ZP_SAMPLE_BASE_LO),y
        sta     m6_tmp_sample_ptr_lo
        iny
        lda     (ZP_SAMPLE_BASE_LO),y
        sta     m6_tmp_sample_ptr_hi

        ; sample_tone_offset = ch.ton_accum + tick.tone_offset
        ldx     m6_tmp_ch_idx
        clc
        lda     ch_ton_accum_a_lo,x
        adc     m6_tmp_sample_ptr_lo
        sta     m6_tmp_sample_ptr_lo
        lda     ch_ton_accum_a_hi,x
        adc     m6_tmp_sample_ptr_hi
        sta     m6_tmp_sample_ptr_hi
        ; if byte1 bit6 (tone_accumulate): ch.ton_accum = sample_tone_offset
        lda     m6_tmp_row_ptr_hi
        and     #$40
        beq     @no_ta
        lda     m6_tmp_sample_ptr_lo
        sta     ch_ton_accum_a_lo,x
        lda     m6_tmp_sample_ptr_hi
        sta     ch_ton_accum_a_hi,x
@no_ta:

        ; --- Noise/envelope sliding (Python L685-720) ---
        ; add_to_eorn = sign-extend((byte0 >> 1) & 0x1F) from bit 4
        lda     m6_tmp_row_ptr_lo
        lsr     a
        and     #$1F
        ; sign-extend from bit 4: if (val & 0x10): val -= 0x20
        cmp     #$10
        bcc     @ae_pos
        ; Negative: subtract 0x20 (i.e. OR with $E0 for 8-bit signed)
        ora     #$E0
@ae_pos:
        sta     m6_tmp_amp                   ; add_to_eorn (signed 8-bit)

        ; if byte1 bit7: env slide path; else: noise slide path
        lda     m6_tmp_row_ptr_hi
        and     #$80
        beq     @noise_path
        ; Env slide: j = ch.env_sliding + add_to_eorn (16-bit signed)
        ; sign-extend add_to_eorn high byte
        lda     m6_tmp_amp
        bmi     @env_neg
        lda     #0
        sta     m6_tmp_orn_ptr_lo
        jmp     @env_signs_done
@env_neg:
        lda     #$FF
        sta     m6_tmp_orn_ptr_lo
@env_signs_done:
        ldx     m6_tmp_ch_idx
        clc
        lda     ch_env_sliding_a_lo,x
        adc     m6_tmp_amp
        sta     m6_tmp_orn_ptr_hi            ; j_lo (temporary)
        lda     ch_env_sliding_a_hi,x
        adc     m6_tmp_orn_ptr_lo
        ; A = j_hi
        pha                                  ; save j_hi
        ; if envelope_accumulate (byte1 bit5): ch.env_sliding = j
        lda     m6_tmp_row_ptr_hi
        and     #$20
        beq     @no_env_acc
        ldx     m6_tmp_ch_idx
        lda     m6_tmp_orn_ptr_hi            ; j_lo
        sta     ch_env_sliding_a_lo,x
        pla
        sta     ch_env_sliding_a_hi,x
        ; pop & re-push to keep balance? No: pla consumed it. Push again for sam_env_p calc.
        ; Easier path: re-load from BSS:
        lda     ch_env_sliding_a_hi,x
        pha
@no_env_acc:
        ; sam_env_p = (sam_env_p + j) & 0xFF (signed 8-bit accum, only LO byte used)
        clc
        lda     pb_sam_env_p
        adc     m6_tmp_orn_ptr_hi            ; j_lo
        sta     pb_sam_env_p
        pla                                  ; discard j_hi
        jmp     @slide_done

@noise_path:
        ; sam_noise = (ch.noise_sliding + add_to_eorn) & 0xFF
        ldx     m6_tmp_ch_idx
        clc
        lda     ch_noise_sliding_a,x
        adc     m6_tmp_amp
        sta     pb_sam_noise
        ; if noise_accumulate (byte1 bit5): ch.noise_sliding = sam_noise
        lda     m6_tmp_row_ptr_hi
        and     #$20
        beq     @slide_done
        lda     pb_sam_noise
        sta     ch_noise_sliding_a,x
@slide_done:

        ; --- Amplitude slide (Python L725-735) ---
        ; if byte0 bit7: bit6=direction. Slide up: clamp at +15. Down: clamp at -15.
        lda     m6_tmp_row_ptr_lo
        and     #$80
        beq     @no_amp_slide
        ldx     m6_tmp_ch_idx
        lda     m6_tmp_row_ptr_lo
        and     #$40
        bne     @amp_up
        ; Down: if amp_slide > -15: amp_slide--
        lda     ch_amp_slide_a,x
        cmp     #$F1                          ; -15 in two's complement
        beq     @no_amp_slide
        dec     ch_amp_slide_a,x
        jmp     @no_amp_slide
@amp_up:
        ; Up: if amp_slide < 15: amp_slide++
        lda     ch_amp_slide_a,x
        cmp     #15
        beq     @no_amp_slide
        inc     ch_amp_slide_a,x
@no_amp_slide:

@no_sample_data:
        ; --- effective_vol = sample_volume + amp_slide_accum, clamp [0,15] ---
        ldx     m6_tmp_ch_idx
        clc
        lda     m6_tmp_note                  ; sample_volume
        adc     ch_amp_slide_a,x             ; signed
        ; Check < 0 (in signed 8-bit): bit 7 set
        bpl     @ev_check_high
        lda     #0
        jmp     @ev_done
@ev_check_high:
        cmp     #16
        bcc     @ev_done
        lda     #15
@ev_done:
        sta     m6_tmp_note                  ; effective_vol

        ; --- combined_vol = volume_table[(ch.volume<<4) | effective_vol] ---
        lda     ch_volume_a,x
        and     #$0F
        asl     a
        asl     a
        asl     a
        asl     a
        ora     m6_tmp_note
        tay
        lda     volume_table,y
        sta     m6_tmp_amp                   ; combined_vol (0..15)

        ; --- amp_reg = combined_vol | (env_enabled & sample_env_on ? 0x10 : 0) ---
        lda     ch_flags_a,x
        and     #%00000100                   ; env_enabled
        beq     @amp_no_env
        lda     ZP_SCRATCH3                  ; sample_env_on
        beq     @amp_no_env
        lda     m6_tmp_amp
        ora     #$10
        sta     m6_tmp_amp
@amp_no_env:

        ; --- Mixer bits ---
        ; If !sample_tone_on (ZP_SCRATCH1==1): mixer |= (1 << ci)
        ; If !sample_noise_on (ZP_SCRATCH2==1): mixer |= (1 << (ci + 3))
        lda     ZP_SCRATCH1
        beq     @mix_n
        ; Build (1 << ch_idx) inline
        ldx     m6_tmp_ch_idx
        lda     #1
@mt_shift:
        cpx     #0
        beq     @mt_done
        asl     a
        dex
        bne     @mt_shift
@mt_done:
        ora     m6_tmp_mixer_bits
        sta     m6_tmp_mixer_bits
@mix_n:
        lda     ZP_SCRATCH2
        beq     @mix_done
        ldx     m6_tmp_ch_idx
        lda     #%00001000                   ; bit 3
@mn_shift:
        cpx     #0
        beq     @mn_done
        asl     a
        dex
        bne     @mn_shift
@mn_done:
        ora     m6_tmp_mixer_bits
        sta     m6_tmp_mixer_bits
@mix_done:

        ; --- tone_period = (base_period + sample_tone_offset + cur_ton_slide) & 0xFFF ---
        ldx     m6_tmp_ch_idx
        clc
        lda     m6_tmp_tone_lo               ; base_period lo
        adc     m6_tmp_sample_ptr_lo         ; sample_tone_offset lo
        sta     m6_tmp_tone_lo
        lda     m6_tmp_tone_hi
        adc     m6_tmp_sample_ptr_hi
        sta     m6_tmp_tone_hi
        clc
        lda     m6_tmp_tone_lo
        adc     ch_cur_ton_slide_a_lo,x
        sta     m6_tmp_tone_lo
        lda     m6_tmp_tone_hi
        adc     ch_cur_ton_slide_a_hi,x
        and     #$0F                          ; clamp to 12 bits
        sta     m6_tmp_tone_hi

        ; --- Write tone period to AY R(2*ci), R(2*ci+1) ---
        txa
        asl     a
        tay
        lda     m6_tmp_tone_lo
        sta     shadow_ay,y
        iny
        lda     m6_tmp_tone_hi
        sta     shadow_ay,y

        ; --- Write amp_reg to AY R(8+ci) ---
        txa
        clc
        adc     #8
        tay
        lda     m6_tmp_amp
        sta     shadow_ay,y

        ; --- Run ton_slide countdown ---
        jsr     m6_run_ton_slide_countdown
        ; --- Run vibrato countdown ---
        jsr     m6_run_vibrato_countdown

        ; --- Advance pos_in_sample / pos_in_ornament ---
        jsr     m6_advance_sample_orn
        rts

; ----- released branch -----
@released_branch:
        ; amp=0, tone unchanged. Continue sample/orn advance.
        ldx     m6_tmp_ch_idx
        txa
        clc
        adc     #8
        tay
        lda     #0
        sta     shadow_ay,y
        ; Run ton_slide / vibrato countdown? Python L596-602 says no (released branch
        ; just keeps prev tone, doesn't run countdowns).
        ; But sample/orn advance: also no (Python L817-825 advance is gated on
        ; "ch.sound_enabled and not ch.note_released and ch.note is not None").
        rts

; ----- vibrato muted branch -----
@vibrato_muted_branch:
        ; amp=0, tone unchanged. Run ton_slide + vibrato countdowns. Don't advance.
        ldx     m6_tmp_ch_idx
        txa
        clc
        adc     #8
        tay
        lda     #0
        sta     shadow_ay,y
        jsr     m6_run_ton_slide_countdown
        jsr     m6_run_vibrato_countdown
        rts

; -----------------------------------------------------------------------------
; m6_run_ton_slide_countdown
; if ch.ton_sld_count > 0:
;   ch.ton_sld_count -= 1
;   if ch.ton_sld_count == 0:
;     ch.cur_ton_slide += ch.ton_sld_step
;     ch.ton_sld_count = ch.ton_sld_delay
;     if ch.ton_sld_type == 1:  # portamento
;       reached = (step<0 and cur<=delta) or (step>=0 and cur>=delta)
;       if reached: ch.note=slide_to_note; cnt=0; cur=0
; -----------------------------------------------------------------------------
m6_run_ton_slide_countdown:
        ldx     m6_tmp_ch_idx
        lda     ch_ton_sld_count_a,x
        beq     @rts1
        dec     ch_ton_sld_count_a,x
        bne     @rts1
        ; cnt just hit 0: apply step
        clc
        lda     ch_cur_ton_slide_a_lo,x
        adc     ch_ton_sld_step_a_lo,x
        sta     ch_cur_ton_slide_a_lo,x
        lda     ch_cur_ton_slide_a_hi,x
        adc     ch_ton_sld_step_a_hi,x
        sta     ch_cur_ton_slide_a_hi,x
        ; reload cnt
        lda     ch_ton_sld_delay_a,x
        sta     ch_ton_sld_count_a,x
        ; portamento target check
        lda     ch_ton_sld_type_a,x
        beq     @rts1                        ; gliss: no target check
        ; step sign?
        lda     ch_ton_sld_step_a_hi,x
        bmi     @neg_step
        ; positive step: reached if cur >= delta
        ; (cur, delta both signed 16-bit)
        ; cmp 16-bit: subtract delta from cur, check carry & sign
        sec
        lda     ch_cur_ton_slide_a_lo,x
        sbc     ch_ton_sld_delta_a_lo,x
        lda     ch_cur_ton_slide_a_hi,x
        sbc     ch_ton_sld_delta_a_hi,x
        ; If result >= 0 (no borrow + positive): cur >= delta
        bvc     @nv1
        eor     #$80
@nv1:
        bmi     @rts1                        ; cur < delta
        jmp     @port_reached
@neg_step:
        ; negative step: reached if cur <= delta
        sec
        lda     ch_ton_sld_delta_a_lo,x
        sbc     ch_cur_ton_slide_a_lo,x
        lda     ch_ton_sld_delta_a_hi,x
        sbc     ch_cur_ton_slide_a_hi,x
        bvc     @nv2
        eor     #$80
@nv2:
        bmi     @rts1                        ; delta < cur, i.e. cur > delta
@port_reached:
        ; ch.note = slide_to_note; ch.ton_sld_count = 0; ch.cur_ton_slide = 0
        lda     ch_slide_to_note_a,x
        sta     ch_note_a,x
        lda     #0
        sta     ch_ton_sld_count_a,x
        sta     ch_cur_ton_slide_a_lo,x
        sta     ch_cur_ton_slide_a_hi,x
@rts1:
        rts

; -----------------------------------------------------------------------------
; m6_run_vibrato_countdown
; if ch.current_onoff > 0:
;   ch.current_onoff -= 1
;   if ch.current_onoff == 0:
;     ch.sound_enabled = !ch.sound_enabled
;     ch.current_onoff = (ch.sound_enabled ? onoff_delay : offon_delay)
; -----------------------------------------------------------------------------
m6_run_vibrato_countdown:
        ldx     m6_tmp_ch_idx
        lda     ch_current_onoff_a,x
        beq     @rts2
        dec     ch_current_onoff_a,x
        bne     @rts2
        ; Toggle sound_enabled (bit3)
        lda     ch_flags_a,x
        eor     #%00001000
        sta     ch_flags_a,x
        and     #%00001000
        beq     @use_offon
        ; sound_enabled=1: use onoff_delay
        lda     ch_onoff_delay_a,x
        sta     ch_current_onoff_a,x
        rts
@use_offon:
        lda     ch_offon_delay_a,x
        sta     ch_current_onoff_a,x
@rts2:
        rts

; -----------------------------------------------------------------------------
; m6_advance_sample_orn
; if sound_enabled and not released and ch.note != $FF:
;   advance pos_in_sample (with loop_pos wrap)
;   advance pos_in_ornament (with loop_pos wrap)
; Sample: header has loop_pos at offset 0, length at offset 1.
; Ornament: header has loop_pos at offset 0, length at offset 1.
; -----------------------------------------------------------------------------
m6_advance_sample_orn:
        ldx     m6_tmp_ch_idx
        lda     ch_flags_a,x
        and     #%00001010                    ; bit1=released, bit3=sound_enabled
        cmp     #%00001000                    ; want sound_enabled=1, released=0
        beq     @ok_advance
        rts
@ok_advance:
        lda     ch_note_a,x
        cmp     #$FF
        bne     @do_advance
        rts

@do_advance:
        ; --- Advance sample ---
        lda     ch_sample_num_a,x
        beq     @adv_orn
        ; Get sample header pointer (loop_pos at +0, length at +1)
        ; ZP_SAMPLE_BASE was set by m6_get_sample_tick_ptr (advanced past header).
        ; Need to re-fetch to get header. Save pos_in_sample to advance:
        inc     ch_pos_in_sample_a,x
        ; Re-fetch sample header
        asl     a                              ; sample_num*2
        tay
        lda     pt3_sample_table_lo
        sta     M5_PTR_LO
        lda     pt3_sample_table_hi
        sta     M5_PTR_HI
        lda     (M5_PTR_LO),y
        sta     ZP_SAMPLE_BASE_LO
        iny
        lda     (M5_PTR_LO),y
        sta     ZP_SAMPLE_BASE_HI
        clc
        lda     ZP_SAMPLE_BASE_LO
        adc     pt3_base_lo
        sta     ZP_SAMPLE_BASE_LO
        lda     ZP_SAMPLE_BASE_HI
        adc     pt3_base_hi
        sta     ZP_SAMPLE_BASE_HI
        ; Compare pos_in_sample >= length
        ldy     #1                             ; length
        lda     (ZP_SAMPLE_BASE_LO),y
        cmp     ch_pos_in_sample_a,x
        bcs     @sample_in_range               ; length > pos: still in range (length BCS pos)
        ; Wrap: pos = loop_pos
        ldy     #0
        lda     (ZP_SAMPLE_BASE_LO),y
        sta     ch_pos_in_sample_a,x
@sample_in_range:

@adv_orn:
        ; --- Advance ornament ---
        lda     ch_ornament_num_a,x
        beq     @adv_done
        inc     ch_pos_in_ornament_a,x
        asl     a                              ; orn_num*2
        tay
        lda     pt3_ornament_table_lo
        sta     M5_PTR_LO
        lda     pt3_ornament_table_hi
        sta     M5_PTR_HI
        lda     (M5_PTR_LO),y
        sta     ZP_ORN_BASE_LO
        iny
        lda     (M5_PTR_LO),y
        sta     ZP_ORN_BASE_HI
        clc
        lda     ZP_ORN_BASE_LO
        adc     pt3_base_lo
        sta     ZP_ORN_BASE_LO
        lda     ZP_ORN_BASE_HI
        adc     pt3_base_hi
        sta     ZP_ORN_BASE_HI
        ldy     #1
        lda     (ZP_ORN_BASE_LO),y
        cmp     ch_pos_in_ornament_a,x
        bcs     @orn_in_range
        ldy     #0
        lda     (ZP_ORN_BASE_LO),y
        sta     ch_pos_in_ornament_a,x
@orn_in_range:
@adv_done:
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

; SPC_CMD parameter byte counts (indexed by cmd 0..15)
; Matches Python SPC_CMD_PARAM_BYTES.
; cmd 0 is N/A (0 is END_OF_PATTERN, not a spec cmd), but kept as 0 for safety.
SPC_CMD_PARAM_TABLE:
        .byte   0       ; cmd 0 — unused
        .byte   3       ; cmd 1 GLISS
        .byte   5       ; cmd 2 PORTM
        .byte   1       ; cmd 3 SMPOS
        .byte   1       ; cmd 4 ORPOS
        .byte   2       ; cmd 5 VIBRT
        .byte   0       ; cmd 6
        .byte   0       ; cmd 7
        .byte   3       ; cmd 8 ENGLS
        .byte   1       ; cmd 9 DELAY
        .byte   0       ; cmd 10
        .byte   0       ; cmd 11
        .byte   0       ; cmd 12
        .byte   0       ; cmd 13
        .byte   0       ; cmd 14
        .byte   0       ; cmd 15

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

; PT3 header parsed fields (M4)
pt3_base_lo:            .res 1
pt3_base_hi:            .res 1
pt3_version_char:       .res 1
pt3_features_level:     .res 1
pt3_tone_table:         .res 1
pt3_delay:              .res 1
pt3_num_positions:      .res 1
pt3_loop_position:      .res 1
pt3_patterns_ptr_lo:    .res 1
pt3_patterns_ptr_hi:    .res 1
pt3_sample_table_lo:    .res 1
pt3_sample_table_hi:    .res 1
pt3_ornament_table_lo:  .res 1
pt3_ornament_table_hi:  .res 1
pt3_position_list_lo:   .res 1
pt3_position_list_hi:   .res 1
pt3_parse_error:        .res 1

; M5a pattern decoder state
row_out_ch_a:           .res 12
row_out_ch_b:           .res 12
row_out_ch_c:           .res 12

ch_nn_skip_a:           .res 1
ch_nn_skip_b:           .res 1
ch_nn_skip_c:           .res 1
ch_end_flag_a:          .res 1
ch_end_flag_b:          .res 1
ch_end_flag_c:          .res 1

dec_current_ch:         .res 1
dec_pending_spec0:      .res 1
dec_pending_spec1:      .res 1
dec_pending_count:      .res 1
dec_spc_cmd_save:       .res 1
dec_spc_nparam:         .res 1

; M5b driver state
ch_skip_counter_a:      .res 1
ch_skip_counter_b:      .res 1
ch_skip_counter_c:      .res 1
dec_active_count:       .res 1
dec_pat_mul_lo:         .res 1
dec_pat_mul_hi:         .res 1
dec_pat_x2_lo:          .res 1
dec_pat_x2_hi:          .res 1

; =============================================================================
; M6 playback engine BSS
; =============================================================================

; Per-channel state (3 channels × N bytes)
; Fields follow Python Channel class (pt3_simulator.py L208-293).
; Channel index convention: 0=A, 1=B, 2=C.

; Note: $FF = no note yet, $C0 = released, else 0..95 (MIDI-ish)
ch_note_a:              .res 1
ch_note_b:              .res 1
ch_note_c:              .res 1

; Previous note (for portamento): $FF = none, else 0..95
ch_prev_note_a:         .res 1
ch_prev_note_b:         .res 1
ch_prev_note_c:         .res 1

; Master volume (0..15)
ch_volume_a:            .res 1
ch_volume_b:            .res 1
ch_volume_c:            .res 1

; Sample number (1..31, default 1 per VTII quirk)
ch_sample_num_a:        .res 1
ch_sample_num_b:        .res 1
ch_sample_num_c:        .res 1

; Position in sample (0..31 typical, wraps to loop_pos)
ch_pos_in_sample_a:     .res 1
ch_pos_in_sample_b:     .res 1
ch_pos_in_sample_c:     .res 1

; Ornament number (0..15)
ch_ornament_num_a:      .res 1
ch_ornament_num_b:      .res 1
ch_ornament_num_c:      .res 1

; Position in ornament
ch_pos_in_ornament_a:   .res 1
ch_pos_in_ornament_b:   .res 1
ch_pos_in_ornament_c:   .res 1

; Channel flags: bit0=enabled bit1=note_released bit2=envelope_enabled bit3=sound_enabled(vibrato)
ch_flags_a:             .res 1
ch_flags_b:             .res 1
ch_flags_c:             .res 1

; Amplitude slide accumulator (signed, from sample byte 0 bit 7)
ch_amp_slide_a:         .res 1
ch_amp_slide_b:         .res 1
ch_amp_slide_c:         .res 1

; Tone accumulator (16-bit, used when sample byte1 bit6 set)
ch_ton_accum_a_lo:      .res 1
ch_ton_accum_a_hi:      .res 1
ch_ton_accum_b_lo:      .res 1
ch_ton_accum_b_hi:      .res 1
ch_ton_accum_c_lo:      .res 1
ch_ton_accum_c_hi:      .res 1

; Current envelope sliding (16-bit signed, per-channel accumulator)
ch_env_sliding_a_lo:    .res 1
ch_env_sliding_a_hi:    .res 1
ch_env_sliding_b_lo:    .res 1
ch_env_sliding_b_hi:    .res 1
ch_env_sliding_c_lo:    .res 1
ch_env_sliding_c_hi:    .res 1

; Current noise sliding (8-bit signed)
ch_noise_sliding_a:     .res 1
ch_noise_sliding_b:     .res 1
ch_noise_sliding_c:     .res 1

; Ton slide effect state (gliss / portamento)
ch_ton_sld_delay_a:     .res 1
ch_ton_sld_delay_b:     .res 1
ch_ton_sld_delay_c:     .res 1
ch_ton_sld_count_a:     .res 1
ch_ton_sld_count_b:     .res 1
ch_ton_sld_count_c:     .res 1
ch_ton_sld_step_a_lo:   .res 1
ch_ton_sld_step_a_hi:   .res 1
ch_ton_sld_step_b_lo:   .res 1
ch_ton_sld_step_b_hi:   .res 1
ch_ton_sld_step_c_lo:   .res 1
ch_ton_sld_step_c_hi:   .res 1
ch_ton_sld_delta_a_lo:  .res 1
ch_ton_sld_delta_a_hi:  .res 1
ch_ton_sld_delta_b_lo:  .res 1
ch_ton_sld_delta_b_hi:  .res 1
ch_ton_sld_delta_c_lo:  .res 1
ch_ton_sld_delta_c_hi:  .res 1
ch_slide_to_note_a:     .res 1
ch_slide_to_note_b:     .res 1
ch_slide_to_note_c:     .res 1
ch_ton_sld_type_a:      .res 1  ; 0=gliss, 1=portamento
ch_ton_sld_type_b:      .res 1
ch_ton_sld_type_c:      .res 1
ch_cur_ton_slide_a_lo:  .res 1  ; accumulated tone slide (16-bit signed)
ch_cur_ton_slide_a_hi:  .res 1
ch_cur_ton_slide_b_lo:  .res 1
ch_cur_ton_slide_b_hi:  .res 1
ch_cur_ton_slide_c_lo:  .res 1
ch_cur_ton_slide_c_hi:  .res 1
ch_saved_ton_slide_a_lo: .res 1
ch_saved_ton_slide_a_hi: .res 1
ch_saved_ton_slide_b_lo: .res 1
ch_saved_ton_slide_b_hi: .res 1
ch_saved_ton_slide_c_lo: .res 1
ch_saved_ton_slide_c_hi: .res 1

; Vibrato state (effect 6)
ch_onoff_delay_a:       .res 1
ch_onoff_delay_b:       .res 1
ch_onoff_delay_c:       .res 1
ch_offon_delay_a:       .res 1
ch_offon_delay_b:       .res 1
ch_offon_delay_c:       .res 1
ch_current_onoff_a:     .res 1
ch_current_onoff_b:     .res 1
ch_current_onoff_c:     .res 1

; -----------------------------------------------------------------------------
; Global playback state
; -----------------------------------------------------------------------------
pb_speed:               .res 1    ; from pt3_delay, modified by effect 9
pb_tick_in_row:         .res 1    ; counts 0..pb_speed-1
pb_position_idx:        .res 1    ; index into position list
pb_current_line:        .res 1    ; row within current pattern
pb_current_pat_len:     .res 1    ; length of current pattern
pb_noise_period:        .res 1    ; R6 base (NsBase)
pb_add_to_noise:        .res 1    ; global, sticky between frames
pb_sam_noise:           .res 1    ; sticky, updated when ch has Mixer_Noise
pb_sam_env_p:           .res 1    ; reset each frame, accumulated per-channel
pb_env_period_lo:       .res 1
pb_env_period_hi:       .res 1
pb_env_shape:           .res 1    ; R13 pending write value, $FF = no write
pb_end_of_song:         .res 1    ; flag when song loop hits end
pb_env_delay:           .res 1    ; effect 9 envslide state (global)
pb_cur_env_delay:       .res 1
pb_env_slide_add_lo:    .res 1
pb_env_slide_add_hi:    .res 1
pb_cur_env_slide_lo:    .res 1
pb_cur_env_slide_hi:    .res 1

; 14 AY registers — shadow values to write to DigiMuz this frame
; NOTE: shadow_ay already exists at the top of BSS (used by M1). We alias it.

; -----------------------------------------------------------------------------
; M6 scratch for compute
; -----------------------------------------------------------------------------
m6_tmp_tone_lo:         .res 1
m6_tmp_tone_hi:         .res 1
m6_tmp_note:            .res 1
m6_tmp_amp:             .res 1
m6_tmp_mixer_bits:      .res 1    ; accumulates per-channel T/N into R7
m6_tmp_ch_idx:          .res 1    ; current channel 0/1/2
m6_tmp_row_ptr_lo:      .res 1    ; pointer into row_out_ch_<n>
m6_tmp_row_ptr_hi:      .res 1
m6_tmp_sample_ptr_lo:   .res 1    ; sample data pointer (header + tick)
m6_tmp_sample_ptr_hi:   .res 1
m6_tmp_orn_ptr_lo:      .res 1
m6_tmp_orn_ptr_hi:      .res 1
m6_decoded:             .res 3   ; per-channel decoded flag (used in decode loop)

.exportzp note_table_addr_hint := $FF
.export note_table
.export volume_table
.export pt3_base_lo
.export pt3_version_char
.export pt3_features_level
.export pt3_tone_table
.export pt3_delay
.export pt3_num_positions
.export pt3_loop_position
.export pt3_patterns_ptr_lo
.export pt3_sample_table_lo
.export pt3_ornament_table_lo
.export pt3_position_list_lo
.export pt3_parse_error
.export row_out_ch_a
.export row_out_ch_b
.export row_out_ch_c
.export ch_nn_skip_a
.export ch_skip_counter_a
.export ch_end_flag_a
.export shadow_ay
.export pb_position_idx
.export pb_current_line
.export pb_tick_in_row
.export pb_speed
.export pb_end_of_song
.export ch_sample_num_a
.export ch_sample_num_b
.export ch_sample_num_c
.export ch_volume_a
.export ch_volume_b
.export ch_volume_c
.export ch_note_a
.export ch_note_b
.export ch_note_c
.export ch_flags_a
.export ch_flags_b
.export ch_flags_c
.export ch_pos_in_sample_a
.export ch_pos_in_sample_b
.export ch_pos_in_sample_c
.export pt3_sample_table_hi
.export pt3_ornament_table_hi
.export pt3_base_hi
.export pt3_position_list_hi
.export pt3_patterns_ptr_hi
.export ch_ornament_num_a
.export ch_pos_in_ornament_a
.export ch_amp_slide_a
.export ch_ton_accum_a_lo
.export ch_ton_accum_a_hi
.export ch_cur_ton_slide_a_lo
.export ch_cur_ton_slide_a_hi
.export note_table
