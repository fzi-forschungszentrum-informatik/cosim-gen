OUTPUT_ARCH("riscv")
ENTRY(_prog_start)

MEMORY
{
  memory (rwx) : ORIGIN = 0xb0000000, LENGTH = 0x200000
}

PHDRS
{
  ram_text PT_LOAD FLAGS(5);   /* R | X */
  ram_data PT_LOAD FLAGS(6);   /* R | W */
  ram_noload PT_NULL;
}

SECTIONS
{
  .text : {
    *(.text.startup .text.startup.*)
    *(.text .text.*)
  } >memory :ram_text

  .rodata : {
    *(.rodata .rodata.*)
  } >memory :ram_data

  . = ALIGN(8);
  PROVIDE(_data_lma = .);

  .data : {
    . = ALIGN(8);
    PROVIDE(_data = .);
    *(.data .data.*)
    . = ALIGN(8);
    PROVIDE(__global_pointer$ = . + 0x800);
    *(.sdata .sdata.*)
    *(.srodata .srodata.*)
  } >memory :ram_data

  . = ALIGN(8);
  PROVIDE(_edata = .);
  PROVIDE(__bss_start = .);

  .bss : {
    *(.sbss .sbss.*)
    *(.bss .bss.*)
    *(COMMON)
    . = ALIGN(8);
  } >memory :ram_noload

  PROVIDE(_end = .);

  PROVIDE(_sp = ORIGIN(memory) + LENGTH(memory));

  ASSERT(_end <= _sp - 0x1000, "test image leaves less than 4KB for the stack")
}
