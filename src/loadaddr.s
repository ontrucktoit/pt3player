; Emit .prg load-address header ($01 $10 = $1001 little-endian)
        .segment "LOADADDRHDR"
        .word   $1001
