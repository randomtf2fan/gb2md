"""Optional diagnostic link peer, not a hardware-accurate serial implementation.

Matches the test runner's established instantaneous internal-clock receiver.
Normal compiler/runtime builds do not enable this behavior.
"""
from gb_cpu import Memory

SERIAL_CAPACITY = 512
SERIAL_COUNT_ADDRESS = "FFC600.w"
SERIAL_OVERFLOW_ADDRESS = "FFC602.b"
SERIAL_BUFFER_BASE = 0xFFD000

class SerialTestMemory(Memory):
    def __init__(self, rom):
        super().__init__(rom)
        self.serial = bytearray()

    def write(self, address, value, bus_phase=0):
        super().write(address, value, bus_phase=bus_phase)
        if (address & 0xFFFF) == 0xFF02 and (value & 0x81) == 0x81:
            self.serial.append(self.io[1])
            self.io[2] = value & 0x7F
