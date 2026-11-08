import unittest

from bank_analysis import fixed_bank_context_targets, leaf_preserves_rom_bank
from test_smoke import bank_context_diagnostic_rom


class BankAnalysisTests(unittest.TestCase):
    def leaf(self, program):
        rom = bytearray(bank_context_diagnostic_rom())
        rom[0x8100:0x8100 + len(program)] = program
        return rom

    def test_constant_wram_store_is_proven(self):
        rom = bank_context_diagnostic_rom()
        self.assertTrue(leaf_preserves_rom_bank(rom, 2, 0x4100))
        self.assertEqual(fixed_bank_context_targets(rom, 2, 0x105), [(2, 0x4100), (2, 0x4200)])

    def test_unknown_mapper_and_stack_writes_fail_closed(self):
        for program in ('3e02ea0020c9', '36aac9', '2100c026203602c9',
                        '21ffff223602c9', 'cb86c9', 'c5c1c9', '02c9', '12c9'):
            with self.subTest(program=program):
                rom = self.leaf(bytes.fromhex(program))
                self.assertFalse(leaf_preserves_rom_bank(rom, 2, 0x4100))
                self.assertEqual(fixed_bank_context_targets(rom, 2, 0x105), [(2, 0x4100)])

    def test_both_conditional_paths_must_preserve_mapping(self):
        rom = self.leaf(bytes.fromhex('fa00c0a728053e02ea0020c9'))
        self.assertFalse(leaf_preserves_rom_bank(rom, 2, 0x4100))
        rom = self.leaf(bytes.fromhex('fa00c0a728032102c034c9'))
        # One path reaches INC (HL) without initializing HL.
        self.assertFalse(leaf_preserves_rom_bank(rom, 2, 0x4100))

    def test_unknown_control_flow_and_budgets_stop_analysis(self):
        for program in ('cd0042c9', 'e9', '18fe', '76c9'):
            self.assertFalse(leaf_preserves_rom_bank(self.leaf(bytes.fromhex(program)), 2, 0x4100))
        rom = bank_context_diagnostic_rom()
        self.assertFalse(leaf_preserves_rom_bank(rom, 2, 0x4100, 0))
        self.assertEqual(fixed_bank_context_targets(rom, 2, 0x105, 1), [(2, 0x4100)])
        self.assertFalse(leaf_preserves_rom_bank(bytes(0x4000), 2, 0x4100))

    def test_conditional_call_retains_untaken_bank_context(self):
        rom = self.leaf(bytes.fromhex('3e02ea0020c9'))
        rom[0x105] = 0xC4
        self.assertEqual(fixed_bank_context_targets(rom, 2, 0x105), [(2, 0x4100), (2, 0x4200)])


if __name__ == '__main__':
    unittest.main()
