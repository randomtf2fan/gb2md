"""Physical ROM address lines shared by reference tracing and native builds.

Only complete, standard-size MBC1/MBC5 images are resolved here. A truncated
dump must not silently become a smaller mirrored cartridge. Other mapper
wiring, including non-power-of-two ROM sizes, retains its existing behavior.
"""


def mbc5_rom_bank_mask(rom):
    if len(rom) < 0x150 or not 0x19 <= rom[0x147] <= 0x1e:
        return None
    size_code = rom[0x148]
    if size_code > 8 or len(rom) != 0x8000 << size_code:
        return None
    return len(rom) // 0x4000 - 1


def physical_rom_bank(rom, selected):
    mask = mbc5_rom_bank_mask(rom)
    if mask is None:mask = mbc1_rom_bank_mask(rom)
    return selected if mask is None else selected & mask


def mbc1_rom_bank_mask(rom):
    """Connected ROM lines for a complete, standard MBC1 cartridge.

    Multicart wiring is intentionally not inferred from the ROM size.
    """
    if len(rom) < 0x150 or rom[0x147] not in (1, 2, 3):
        return None
    size_code = rom[0x148]
    if size_code > 6 or len(rom) != 0x8000 << size_code:
        return None
    return len(rom) // 0x4000 - 1
