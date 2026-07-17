    .section .text.init
    .option norvc
    .globl _prog_start
    .extern _dtblob

_prog_start:
    csrw    mstatus,    x0
    csrw    mie,        x0
    csrw    mip,        x0

    la      t0,         _trap_handle
    csrw    mtvec,      t0

    li      ra,         0xB0000000
    csrr    a0,         mhartid
    la      a1,         _dtblob
    jr      ra

_trap_handle:
    wfi
    j       _trap_handle
