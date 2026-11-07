#!/usr/bin/env python3
"""Generate GB2MD's original, post-boot MBC3 RAM diagnostic ROM.

The image deliberately contains no Nintendo boot-logo bytes or third-party
assets. GB2MD and its test harness begin at the documented post-boot cartridge
entry point, so a physical Game Boy boot ROM is outside this diagnostic's
scope. Success uses the Mooneye-compatible Fibonacci register signature.
"""
from __future__ import annotations

import argparse
from pathlib import Path


ENTRY = 0x0150
ROM_SIZE = 4 * 0x4000


def build_mbc3_ram_test() -> bytes:
    program = bytearray()
    failures: list[int] = []

    def emit(*values: int) -> None:
        program.extend(value & 0xFF for value in values)

    def ld_a(value: int) -> None:
        emit(0x3E, value)

    def ld_abs_a(address: int) -> None:
        emit(0xEA, address & 0xFF, address >> 8)

    def require_a(value: int) -> None:
        emit(0xFE, value, 0xC2, 0, 0)  # CP value; JP NZ,fail
        failures.append(len(program) - 2)

    emit(0xF3, 0x31, 0xFE, 0xFF)  # DI; LD SP,$FFFE
    ld_a(0x0A); ld_abs_a(0x0000)  # Enable cartridge RAM.

    ld_a(0); ld_abs_a(0x4000)
    ld_a(0x11); ld_abs_a(0xA000)
    ld_a(1); ld_abs_a(0x4000)
    ld_a(0x22); ld_abs_a(0xA000)

    ld_a(0); ld_abs_a(0x4000)
    emit(0xFA, 0x00, 0xA0); require_a(0x11)
    ld_a(1); ld_abs_a(0x4000)
    emit(0xFA, 0x00, 0xA0); require_a(0x22)

    ld_a(0); ld_abs_a(0x0000)  # Disabled RAM must read as open bus.
    emit(0xFA, 0x00, 0xA0); require_a(0xFF)
    ld_a(0x0A); ld_abs_a(0x0000)
    emit(0xFA, 0x00, 0xA0); require_a(0x22)

    # B/C/D/E/H/L = 3/5/8/13/21/34, then LD B,B; JR -2.
    emit(0x06, 3, 0x0E, 5, 0x16, 8, 0x1E, 13, 0x26, 21, 0x2E, 34)
    emit(0x40, 0x18, 0xFE)

    fail_address = ENTRY + len(program)
    emit(0x06, 0x42, 0x0E, 0x42, 0x16, 0x42,
         0x1E, 0x42, 0x26, 0x42, 0x2E, 0x42)
    emit(0x40, 0x18, 0xFE)
    for offset in failures:
        program[offset] = fail_address & 0xFF
        program[offset + 1] = fail_address >> 8

    rom = bytearray(ROM_SIZE)
    rom[0x100:0x104] = bytes((0xC3, ENTRY & 0xFF, ENTRY >> 8, 0x00))
    rom[0x134:0x143] = b"GB2MD MBC3 TEST"
    rom[0x143] = 0x00  # DMG-compatible.
    rom[0x146] = 0x00
    rom[0x147] = 0x13  # MBC3 + RAM + battery hardware profile.
    rom[0x148] = 0x01  # 64 KiB / four ROM banks.
    rom[0x149] = 0x03  # 32 KiB / four RAM banks.
    rom[0x14A] = 0x01  # Non-Japanese region marker.
    rom[0x14C] = 0x00
    rom[ENTRY:ENTRY + len(program)] = program

    header = 0
    for value in rom[0x134:0x14D]:
        header = (header - value - 1) & 0xFF
    rom[0x14D] = header
    total = (sum(rom) - rom[0x14E] - rom[0x14F]) & 0xFFFF
    rom[0x14E:0x150] = total.to_bytes(2, "big")
    return bytes(rom)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", nargs="?", type=Path,
                        default=Path("homebrew-mbc3-test.gb"))
    args = parser.parse_args()
    image = build_mbc3_ram_test()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(image)
    print(f"wrote {args.output} ({len(image)} bytes; original GB2MD test code)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
