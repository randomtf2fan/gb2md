"""Original probes for compact nonzero-bank page directories."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import build_recompiled as compiler
import trace_recompiler as trace
import test_packed_dispatch as packed


def upper_edge_rom(bank=2,mapper=0x11):
    rom=bytearray(0x10000);rom[0x147:0x14A]=bytes([mapper,1,0])
    rom[0x100:0x108]=bytes([0x3E,bank,0xEA,0,0x20,0xC3,0xF8,0x7F])
    offset=bank*0x4000+0x3FF8
    rom[offset:offset+7]=bytes.fromhex('3e42ea00c018fe')
    return bytes(rom)


class WindowedDispatchTests(unittest.TestCase):
    dispatch_format='windowed'
    native_build=packed.PackedDispatchTests.native_build

    def test_directory_savings_entries_and_invalid_identity_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'original.gb';source.write_bytes(upper_edge_rom())
            blocks=trace.compile_trace(source,root/'out',2)
            trace.emit_native_blocks(blocks,root/'out',dispatch_format='trimmed')
            before=(root/'out/translated_trace.s').read_text();a=json.loads((root/'out/native-codegen-report.json').read_text())
            trace.emit_native_blocks(blocks,root/'out',dispatch_format='windowed')
            after=(root/'out/translated_trace.s').read_text();b=json.loads((root/'out/native-codegen-report.json').read_text())
            self.assertEqual(before.split('gb_dispatch_tree:')[0],after.split('gb_dispatch_tree:')[0])
            self.assertEqual(a['blocks'],b['blocks'])
            self.assertEqual(a['dispatch_table_bytes']-b['dispatch_table_bytes'],768)
            self.assertEqual(b['dispatch_table_bytes'],a['dispatch_windowed_table_bytes'])
            self.assertEqual(b['dispatch_format'],'bank_page_table_24_windowed')
            directory=after.split('gb_dispatch_bank_002:\n')[1].split('gb_dispatch_page_000_01:')[0]
            self.assertEqual(directory.count('\tdc.l '),8)
            self.assertIn('gb_dispatch_page_002_7F',directory)
            with self.assertRaisesRegex(ValueError,'normalized'):
                trace.emit_native_blocks([dict(blocks[0],bank=2,pc=0x100)],root/'invalid',dispatch_format='windowed')

    def test_capacity_retry_preserves_window_and_options(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'original.gb';rom=bytearray(upper_edge_rom())
            # A statically reachable NOP run makes the ordinary auto layout
            # choose pages throughout catalog omission and later retries.
            rom[0x105:0x10B]=bytes.fromhex('c20020c3f87f');rom[0x2200]=0xC9
            source.write_bytes(rom);assembler=root/'assembler';assembler.touch();calls=[]
            def assemble(command,**kwargs):
                calls.append(command);Path(command[-1]).write_bytes(bytes(0x400002 if len(calls)<7 else 0x80000))
            with patch.object(compiler,'compile_trace',wraps=compiler.compile_trace) as discovered,patch.object(compiler.subprocess,'run',side_effect=assemble):
                compiler.build(source,root/'out',20,assembler=assembler,optimize_hram=False,optimize_pure_chains=False)
            attempts=json.loads((root/'out/build-report.json').read_text())['native_layout_attempts']
            self.assertEqual(discovered.call_count,1)
            self.assertEqual([a['dispatch_format'] for a in attempts],['bank_page_table','bank_page_table','bank_page_table_24','bank_page_table_24_trimmed','bank_page_table_24_windowed','bank_page_table_24_windowed','bank_page_table_24_windowed'])
            self.assertEqual(attempts[3]['hot_chain_targets'],attempts[4]['hot_chain_targets'])
            self.assertEqual(attempts[5]['hot_chain_targets'],attempts[4]['hot_chain_targets'])
            self.assertTrue(attempts[5]['compact_bank_immediates'])
            self.assertTrue(attempts[6]['compact_bank_immediates'])
            self.assertLess(attempts[6]['hot_chain_targets'],attempts[5]['hot_chain_targets'])
            stats=json.loads((root/'out/native-codegen-report.json').read_text())
            self.assertFalse(stats['optimize_hram']);self.assertFalse(stats['optimize_pure_chains'])
            self.assertFalse(stats['block_catalog_included'])

    test_native_high_address_and_odd_slot_and_page_boundary=packed.PackedDispatchTests.test_native_high_address_and_odd_slot_and_page_boundary
    test_native_missing_slots_pages_banks_retain_diagnostics=packed.PackedDispatchTests.test_native_missing_slots_pages_banks_retain_diagnostics
    test_native_irq_and_banked_control_flow=packed.PackedDispatchTests.test_native_irq_and_banked_control_flow

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_last_upper_page_and_mbc5_bank_zero(self):
        from run_compat_tests import _run_in_pty,_blastem_values
        for bank,mapper in ((2,0x11),(0,0x19),(3,0x19)):
            with self.subTest(bank=bank,mapper=mapper),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);source=root/'original.gb';source.write_bytes(upper_edge_rom(bank,mapper))
                image=self.native_build(source,root/'out',2)
                rc,out,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(image)],
                    'frames 120\np/x [$ff2300].b [$ff0018].l [$ff0038].l\nquit\n',20)
                self.assertFalse(timed,out);self.assertEqual(rc,0,out);v=_blastem_values(out)
                self.assertEqual([v.get(k) for k in ('FF2300.b','FF0018.l','FF0038.l')],[0x42,0,0],out)
