/*
 * Startup stub for the RAM payload simram.elf: sets up sp/gp, signals
 * "started" to SimTestRegisters (fzi,simtestregs @ 0x78000000), copies
 * .data from its load address, zeroes .bss, calls main(), then signals
 * "done" with main()'s return value before halting.
 */

#define TESTREGS_BASE   0x78000000
#define TESTREGS_MAGIC  0xCAFE
#define TESTREGS_DONE   0xDEAD

    .section .text.startup
    .option norvc
    .globl _prog_start
    .extern main

_prog_start:
    la      t0,         _cpu_halt
    csrw    mtvec,      t0
    .option push
    .option norelax
    la      gp,         __global_pointer$
    .option pop
    la      sp,         _sp

    li      t0,         TESTREGS_BASE
    li      t1,         TESTREGS_MAGIC
    sd   t1,         (t0)

    /* Copy .data from its load address. */
    la      a0,         _data_lma
    la      a1,         _data
    la      a2,         _edata
    bgeu    a1, a2,     _bss_start

_data_loop:
    ld      t0,         (a0)
    sd      t0,         (a1)
    addi    a0, a0,     8
    addi    a1, a1,     8
    bltu    a1, a2,     _data_loop

_bss_start:
    la      a0,         __bss_start
    la      a1,         _end
    bgeu    a0, a1,     _run_main

_bss_loop:
    sd      zero,       (a0)
    addi    a0, a0,     8
    bltu    a0, a1,     _bss_loop

_run_main:
    jal     main

    li      t0,         TESTREGS_BASE
    addi    t1, t0,     8
    sd      a0,         (t1)
    li      t1,         TESTREGS_DONE
    sd      t1,         (t0)

_cpu_halt:
    wfi
    j       _cpu_halt
