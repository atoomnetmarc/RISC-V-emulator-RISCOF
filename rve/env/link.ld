OUTPUT_ARCH( "riscv" )
ENTRY(rvtest_entry_point)

MEMORY
{
  ROM : ORIGIN = 0x20000000, LENGTH = 16M
  RAM : ORIGIN = 0x80000000, LENGTH = 16M
}

SECTIONS
{
  .text.init : { *(.text.init) } > ROM
  .tohost : { *(.tohost) }
  .text : { *(.text) }

  .data : { *(.data) } > RAM
  .data.string : { *(.data.string)}
  .bss : { *(.bss) }
  _end = .;
}

