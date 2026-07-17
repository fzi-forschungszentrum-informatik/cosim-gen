OUTPUT_ARCH("riscv")
ENTRY(_prog_start)

MEMORY
{
  maskrom_mem (rx) : ORIGIN = 0x10000, LENGTH = 0x2000
}

PHDRS
{
  text PT_LOAD;
}

SECTIONS
{
  .text ALIGN(ORIGIN(maskrom_mem), 8) : {
    *(.text.init)
    *(.text .text.*)
  } >maskrom_mem :text

  .devicetree ALIGN(8) : {
    PROVIDE(_dtblob = .);
    devicetree.dts.o
  } >maskrom_mem :text

  .rodata ALIGN(8) : {
    *(.rodata .rodata.*)
  } >maskrom_mem :text

  ASSERT(. <= ORIGIN(maskrom_mem) + LENGTH(maskrom_mem), "bootrom image overflows maskrom_mem")
}
