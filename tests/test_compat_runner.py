import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_runner():
    spec = importlib.util.spec_from_file_location("run_compat_tests", ROOT / "run_compat_tests.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_homebrew_builder():
    spec = importlib.util.spec_from_file_location(
        "make_homebrew_test_rom", ROOT / "make_homebrew_test_rom.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def blank_rom(opcodes=b"\x00"):
    rom = bytearray(0x8000)
    rom[0x100:0x100 + len(opcodes)] = opcodes
    rom[0x143] = 0
    rom[0x147] = 0
    rom[0x148] = 0
    rom[0x149] = 0
    return rom


class CompatibilityRunnerTests(unittest.TestCase):
    def test_serial_receiver_completes_transfer(self):
        runner = load_runner()
        memory = runner.ProtocolMemory(blank_rom())
        memory.write(0xFF01, ord("P"))
        memory.write(0xFF02, 0x81)
        self.assertEqual(memory.serial, b"P")
        self.assertEqual(memory.read(0xFF02) & 0x80, 0)
        memory.write(0xFF46,0x80)
        self.assertEqual(memory.dma_writes,1)

    def test_blargg_requires_documented_text(self):
        runner = load_runner()
        memory = runner.ProtocolMemory(blank_rom())
        memory.serial.extend(b"01-special\n\nPassed\n")
        self.assertEqual(runner.blargg_result(memory)[0], "PASS")
        memory.serial[:] = b"Failed #3"
        self.assertEqual(runner.blargg_result(memory)[0], "FAIL")

    def test_mooneye_terminal_signature(self):
        runner = load_runner()
        rom = blank_rom(b"\x40\x18\xFE")
        memory = runner.ProtocolMemory(rom)
        cpu = runner.CPU(memory)
        cpu.b, cpu.c, cpu.d, cpu.e, cpu.h, cpu.l = runner.MOONEYE_PASS
        self.assertEqual(runner.terminal_mooneye(cpu, memory, "mooneye_fibonacci")[0], "PASS")
        cpu.b = cpu.c = cpu.d = cpu.e = cpu.h = cpu.l = 0x42
        self.assertEqual(runner.terminal_mooneye(cpu, memory, "mooneye_fibonacci")[0], "FAIL")

    def test_cgb_only_is_explicitly_unsupported(self):
        runner = load_runner()
        rom = blank_rom()
        rom[0x143] = 0xC0
        supported, reason = runner.header_support(rom, Path("fixture.gbc"))
        self.assertFalse(supported)
        self.assertIn("CGB-only", reason)

    def test_mooneye_model_selection_keeps_dmg_groups(self):
        runner = load_runner()
        self.assertTrue(runner.model_support(Path("test_roms/mooneye-test-suite/acceptance/foo-GS.gb"))[0])
        self.assertFalse(runner.model_support(Path("test_roms/mooneye-test-suite/acceptance/foo-S.gb"))[0])
        self.assertFalse(runner.model_support(Path("test_roms/mooneye-test-suite/acceptance/boot-dmg0.gb"))[0])

    def test_blastem_debugger_values_are_parsed(self):
        runner = load_runner()
        output="[$ff0002].w: 4ab4\n [$ff000a].b: 3\n [$ff000f].b: 22\n"
        self.assertEqual(runner._blastem_values(output),{"FF0002.w":0x4AB4,"FF000A.b":3,"FF000F.b":0x22})

    def test_blargg_visual_tests_are_not_claimed_from_booting(self):
        runner = load_runner()
        self.assertEqual(runner.protocol_for(Path("test_roms/blargg/halt_bug.gb")),"manual_visual")
        self.assertEqual(runner.protocol_for(Path("test_roms/blargg/cpu_instrs/individual/01-special.gb")),"blargg_serial")

    def test_original_mbc3_homebrew_passes_reference_protocol(self):
        runner = load_runner()
        image = load_homebrew_builder().build_mbc3_ram_test()
        self.assertEqual(image[0x104:0x134], bytes(0x30))  # No boot-logo asset.
        self.assertEqual(image[0x147:0x14A], bytes((0x13, 0x01, 0x03)))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "mooneye-test-suite"
            path = root / "acceptance" / "mbc3_ram.gb"
            path.parent.mkdir(parents=True)
            path.write_bytes(image)
            result = runner.run_python(path, root, 10_000, None, 1024)
        self.assertEqual(result["python"]["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
