import json
import os
import pathlib
import tempfile
import unittest

from ram_callback_analysis import RamCallbackAnalyzer
from trace_recompiler import _selected_bank_candidates


def record_callback_rom(mapper=0x11, selected_bank=3, prefix=b''):
    """Original two-record loader and callback consumer with variable operands."""
    rom = bytearray(0x10000)
    rom[0x147:0x14A] = bytes([mapper, 1, 0])
    program = bytes.fromhex('3e01e0903e01ea20c0cd8001cd4002fa0048ea01c018fe')
    rom[0x100:0x100 + len(program)] = program
    loader = (bytes.fromhex('fa20c0cd0003') + prefix +
              bytes.fromhex('210006fa20c0cb27300124856f3001242a666f1180c10e062a12130d20fac9'))
    rom[0x180:0x180 + len(loader)] = loader
    consumer = bytes.fromhex('fa20c0cd00032182c12a666f115102d5e9c9')
    rom[0x240:0x240 + len(consumer)] = consumer
    selector = bytes.fromhex('e5c54f06003e02cd8003210042097ee091cda003f091e090ea0020c1e1c9')
    rom[0x300:0x300 + len(selector)] = selector
    rom[0x380:0x391] = bytes.fromhex('ea11c0f090ea10c0fa11c0e090ea0020c9')
    rom[0x3A0:0x3A9] = bytes.fromhex('fa10c0e090ea0020c9')
    rom[0x600:0x606] = bytes.fromhex('00440045ffff')
    table_bank = 1 if mapper in (0, 8, 9) else 2
    rom[table_bank * 0x4000 + 0x200:table_bank * 0x4000 + 0x203] = bytes([1, selected_bank, 255])
    active = 1 if mapper in (0, 8, 9) else selected_bank
    rom[0x4400:0x4406] = bytes.fromhex('99fe00463704')
    header = active * 0x4000 + 0x500
    rom[header:header + 6] = bytes.fromhex('99fe00473704')
    rom[0x4600:0x4606] = bytes.fromhex('3e11ea00c0c9')
    callback = active * 0x4000 + 0x700
    rom[callback:callback + 6] = bytes.fromhex('3e42ea00c0c9')
    for bank in range(4):
        rom[bank * 0x4000 + 0x800] = 0xA0 + bank
    return bytes(rom)


def relocated_record_callback_rom():
    """Same original program with different index, record and selector slots."""
    rom = record_callback_rom()
    for old, new in (('20c0', '98ff'), ('80c1', '20d1'), ('82c1', '22d1'),
                     ('11c0', '01c8'), ('10c0', '00c8'),
                     ('e090', 'e0a0'), ('f090', 'f0a0'),
                     ('e091', 'e0a1'), ('f091', 'f0a1')):
        rom = rom.replace(bytes.fromhex(old), bytes.fromhex(new))
    rom = bytearray(rom)
    rom[0x680:0x686] = rom[0x600:0x606]
    rom[0x187:0x189] = bytes.fromhex('8006')
    rom[0x8000 + 0x300:0x8000 + 0x303] = rom[0x8000 + 0x200:0x8000 + 0x203]
    rom[0x30B:0x30D] = bytes.fromhex('0043')
    return bytes(rom)


class RamCallbackTest(unittest.TestCase):
    def discover(self, rom, **budgets):
        return RamCallbackAnalyzer(rom, _selected_bank_candidates, **budgets).discover(
            {(0, 0x180), (0, 0x240)})

    def test_reference_executes_copied_callback_with_selected_data_bank(self):
        from gb_cpu import CPU, Memory
        for mapper, bank, expected in ((0x11, 3, 0xA3), (0x19, 0, 0xA0), (0, 3, 0xA1)):
            with self.subTest(mapper=mapper, bank=bank):
                memory = Memory(record_callback_rom(mapper, bank))
                cpu = CPU(memory)
                for _ in range(300):
                    cpu.step()
                self.assertEqual(memory.wram[:2], bytes([0x42, expected]))

    def test_derives_callback_offset_and_consumer_return(self):
        result = self.discover(record_callback_rom())
        self.assertEqual(result['targets'], {(1, 0x4600), (3, 0x4700)})
        self.assertEqual(result['returns'], {(0, 0x251)})
        self.assertEqual(len(result['records']), 1)
        record = result['records'][0]
        self.assertEqual((record['destination'], record['size'], record['callback_offset']), (0xC180, 6, 2))
        self.assertEqual(record['valid_indices'], 2)
        self.assertFalse(result['pair_limit_reached'])

    def test_relocated_operands_are_derived_without_layout_constants(self):
        from gb_cpu import CPU, Memory
        rom = relocated_record_callback_rom()
        result = self.discover(rom)
        self.assertEqual(result['targets'], {(1, 0x4600), (3, 0x4700)})
        record = result['records'][0]
        self.assertEqual((record['destination'], record['index_address'], record['pointer_table']), (0xD120, 0xFF98, 0x680))
        memory = Memory(rom)
        cpu = CPU(memory)
        for _ in range(300):cpu.step()
        self.assertEqual(memory.wram[:2], bytes([0x42, 0xA3]))

    def test_trace_closure_seeds_unexecuted_records_and_return(self):
        from trace_recompiler import compile_trace
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder)
            source = root / 'records.gb'
            source.write_bytes(record_callback_rom())
            blocks = compile_trace(source, root / 'out', 2)
            keys = {(b['bank'], b['pc']) for b in blocks}
            self.assertTrue({(1, 0x4600), (3, 0x4700), (0, 0x251)} <= keys)
            report = json.loads((root / 'out' / 'trace-profile.json').read_text())
            self.assertEqual(report['ram_callback_targets'], 2)
            self.assertEqual(report['ram_callback_returns'], 1)
            self.assertEqual(report['ram_callback_records'][0]['callback_offset'], 2)

    def test_invalid_callback_and_header_crossing_ram_are_not_guessed(self):
        rom = bytearray(record_callback_rom())
        rom[3 * 0x4000 + 0x700] = 0xD3
        self.assertEqual(self.discover(rom)['targets'], {(1, 0x4600)})
        rom = bytearray(record_callback_rom())
        rom[0x602:0x604] = bytes.fromhex('ff7f')
        self.assertEqual(self.discover(rom)['targets'], {(1, 0x4600)})

    def test_supports_rom_only_and_mbc5_bank_zero(self):
        self.assertIn((1, 0x4700), self.discover(record_callback_rom(0))['targets'])
        self.assertIn((0, 0x4700), self.discover(record_callback_rom(0x19, 0))['targets'])

    def test_mbc1_enumerates_unknown_upper_bank_bits(self):
        rom = bytearray(record_callback_rom(1))
        rom.extend(bytes(0x200000 - len(rom)))
        rom[34 * 0x4000 + 0x200:34 * 0x4000 + 0x203] = bytes([1, 3, 255])
        rom[35 * 0x4000 + 0x500:35 * 0x4000 + 0x506] = bytes.fromhex('99fe00473704')
        rom[35 * 0x4000 + 0x700:35 * 0x4000 + 0x706] = bytes.fromhex('3e42ea00c0c9')
        self.assertTrue({(3, 0x4700), (35, 0x4700)} <= self.discover(rom)['targets'])

    def test_rejects_unproven_selector_semantics(self):
        original = record_callback_rom()
        for address, data in ((0x304, b'\x01'), (0x317, b'\x91'),
                              (0x384, b'\x46'), (0x3A1, b'\x11'),
                              (0x30F, b'\xea')):
            with self.subTest(address=address):
                rom = bytearray(original)
                rom[address:address + len(data)] = data
                self.assertEqual(self.discover(rom)['targets'], set())

    def test_rejects_context_bank_index_stores_and_unknown_calls(self):
        for prefix in (bytes.fromhex('ea0020'), bytes.fromhex('ea20c0'), bytes.fromhex('cd0004')):
            with self.subTest(prefix=prefix.hex()):
                self.assertEqual(self.discover(record_callback_rom(prefix=prefix))['targets'], set())
        self.assertEqual(len(self.discover(record_callback_rom(prefix=b'\x00\x00'))['targets']), 2)

    def test_rejects_mismatched_index_or_outside_copy_field(self):
        original = record_callback_rom()
        for address, data in ((0x241, bytes.fromhex('21c0')), (0x247, bytes.fromhex('86c1')),
                              (0x251, b'\x00'), (0x186 + 25, b'\x0a')):
            with self.subTest(address=address):
                rom = bytearray(original)
                rom[address:address + len(data)] = data
                self.assertEqual(self.discover(rom)['targets'], set())

    def test_rejects_callback_field_clobbered_by_selector_or_context(self):
        rom = bytearray(record_callback_rom())
        # The copied word aliases the selector's old/new-bank scratch slots.
        rom[0x186 + 20:0x186 + 22] = bytes.fromhex('0ec0')
        rom[0x247:0x249] = bytes.fromhex('10c0')
        self.assertEqual(self.discover(rom)['targets'], set())
        for address, expected in ((0xC182, set()), (0xC1F0, {(1,0x4600),(3,0x4700)})):
            rom = bytearray(record_callback_rom())
            consumer = bytes.fromhex('fa20c0cd0003') + bytes([0xEA,address&255,address>>8]) + bytes.fromhex('2182c12a666f115402d5e9c9')
            rom[0x240:0x240 + len(consumer)] = consumer
            with self.subTest(store=address):self.assertEqual(self.discover(rom)['targets'], expected)

    def test_rejects_copy_over_index_and_non_rom_pointer_table(self):
        rom = bytearray(record_callback_rom())
        rom[0x186 + 20:0x186 + 22] = bytes.fromhex('1cc0')
        rom[0x247:0x249] = bytes.fromhex('1ec0')
        self.assertEqual(self.discover(rom)['targets'], set())
        rom = bytearray(record_callback_rom())
        rom[0x187:0x189] = bytes.fromhex('0080')
        self.assertEqual(self.discover(rom)['targets'], set())

    def test_aliases_and_alias_cycles(self):
        rom = bytearray(record_callback_rom())
        rom[0x3C0:0x3D1] = rom[0x380:0x391]
        rom[0x380:0x383] = bytes.fromhex('c3c003')
        self.assertEqual(len(self.discover(rom)['targets']), 2)
        rom[0x3C0:0x3C3] = bytes.fromhex('c38003')
        self.assertEqual(self.discover(rom)['targets'], set())

    def test_budgets_report_limits_and_do_not_scan_unbounded_indices(self):
        rom = record_callback_rom()
        result = self.discover(rom, max_indices=1)
        self.assertEqual(result['targets'], {(1, 0x4600)})
        self.assertEqual(result['records'][0]['index_limit'], 1)
        self.assertEqual(self.discover(rom, max_indices=100000)['records'][0]['index_limit'], 256)
        result = self.discover(record_callback_rom(prefix=b'\0\0'), max_walk_steps=1)
        self.assertIn(0x180, result['exhausted_contexts'])
        self.assertEqual(result['targets'], set())
        rom = bytearray(rom)
        rom[0x280:0x292] = rom[0x240:0x252]
        rom[0x28D:0x28F] = bytes.fromhex('9102')
        result = RamCallbackAnalyzer(rom, _selected_bank_candidates, max_pairs=1).discover(
            {(0, 0x180), (0, 0x240), (0, 0x280)})
        self.assertEqual(len(result['records']), 1)
        self.assertTrue(result['pair_limit_reached'])

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS') == '1', 'opt-in external BlastEm integration')
    def test_native_record_callbacks_and_return_mapping(self):
        from build_recompiled import build
        from run_compat_tests import _run_in_pty, _blastem_values
        cases = [('mbc3', record_callback_rom(), 3),
                 ('mbc5-zero', record_callback_rom(0x19, 0), 0),
                 ('rom-only', record_callback_rom(0), 1),
                 ('relocated', relocated_record_callback_rom(), 3)]
        for name, rom, bank in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                root = pathlib.Path(folder)
                source = root / 'records.gb'
                source.write_bytes(rom)
                build(source, root / 'out', 2)
                commands = 'frames 600\np/x [$ff2300].b [$ff2301].b [$ff001e].w [$ff0018].l\nquit\n'
                code, output, timed = _run_in_pty([os.environ['GB2MD_BLASTEM'], '-d', str(root/'out'/'recompiled.md')], commands, 30)
                self.assertFalse(timed, output)
                self.assertEqual(code, 0, output)
                values = _blastem_values(output)
                self.assertEqual([values.get(a) for a in ('FF2300.b','FF2301.b','FF001E.w','FF0018.l')], [0x42,0xA0+bank,bank,0], output)


if __name__ == '__main__':
    unittest.main()
