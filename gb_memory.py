"""Reference Game Boy cartridge-memory semantics used by GB2MD's target runtime.

This is executable specification code, not an emulator frontend.  The same
operations are required by generated 68000 gb_read8/gb_write8 helpers.
"""
from __future__ import annotations

class MBC3:
    """MBC3 ROM/RAM window and RTC latch semantics (Pokemon Red's mapper)."""
    def __init__(self, rom: bytes, ram_bytes: int = 32 * 1024):
        if len(rom) < 0x8000 or len(rom) % 0x4000: raise ValueError("ROM must contain whole 16 KiB banks")
        self.rom, self.ram = rom, bytearray(ram_bytes)
        self.rom_bank, self.ram_rtc_select, self.ram_enabled = 1, 0, False
        self.rtc = [0, 0, 0, 0, 0]       # seconds, minutes, hours, day low, day high
        self.rtc_latched = self.rtc.copy(); self._latch_write = 0

    @property
    def bank_count(self): return len(self.rom) // 0x4000

    def read(self, address: int) -> int:
        address &= 0xFFFF
        if address < 0x4000: return self.rom[address]
        if address < 0x8000:
            bank = self.rom_bank % self.bank_count
            return self.rom[bank * 0x4000 + address - 0x4000]
        if 0xA000 <= address < 0xC000:
            if not self.ram_enabled: return 0xFF
            if self.ram_rtc_select <= 3:
                offset = self.ram_rtc_select * 0x2000 + address - 0xA000
                return self.ram[offset] if offset < len(self.ram) else 0xFF
            if 0x08 <= self.ram_rtc_select <= 0x0C: return self.rtc_latched[self.ram_rtc_select - 0x08]
        return 0xFF

    def write(self, address: int, value: int):
        address &= 0xFFFF; value &= 0xFF
        if address < 0x2000: self.ram_enabled = (value & 0x0F) == 0x0A
        elif address < 0x4000:
            self.rom_bank = value & 0x7F
            if self.rom_bank == 0: self.rom_bank = 1
        elif address < 0x6000: self.ram_rtc_select = value
        elif address < 0x8000:
            if self._latch_write == 0 and value == 1: self.rtc_latched = self.rtc.copy()
            self._latch_write = value
        elif 0xA000 <= address < 0xC000 and self.ram_enabled:
            if self.ram_rtc_select <= 3:
                offset = self.ram_rtc_select * 0x2000 + address - 0xA000
                if offset < len(self.ram): self.ram[offset] = value
            elif 0x08 <= self.ram_rtc_select <= 0x0C: self.rtc[self.ram_rtc_select - 0x08] = value
