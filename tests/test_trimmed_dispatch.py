"""Original fixtures for bounded, packed native dispatch pages."""
import json
import os
from pathlib import Path
import tempfile
import unittest

import test_packed_dispatch as packed
import trace_recompiler as trace


class TrimmedDispatchTests(unittest.TestCase):
    dispatch_format = 'trimmed'
    native_build = packed.PackedDispatchTests.native_build

    def test_headers_retain_holes_and_report_aligned_table_size(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);rom=bytearray(0x8000)
            rom[0x100:0x103]=bytes.fromhex('c35103')
            rom[0x351:0x355]=bytes.fromhex('210004e9')
            source=root/'original.gb';source.write_bytes(rom)
            blocks=trace.compile_trace(source,root/'out',3)
            trace.emit_native_blocks(blocks,root/'out',dispatch_format='packed')
            wide=(root/'out/translated_trace.s').read_text()
            before=json.loads((root/'out/native-codegen-report.json').read_text())
            trace.emit_native_blocks(blocks,root/'out',dispatch_format='trimmed')
            bounded=(root/'out/translated_trace.s').read_text()
            after=json.loads((root/'out/native-codegen-report.json').read_text())
            self.assertEqual(wide.split('gb_dispatch_tree:')[0],bounded.split('gb_dispatch_tree:')[0])
            self.assertEqual(after['dispatch_format'],'bank_page_table_24_trimmed')
            self.assertEqual(after['blocks'],before['blocks'])
            self.assertEqual(after['dispatch_leaf_entry_bytes'],3)
            self.assertIn('gb_dispatch_page_000_01:\n\tdc.b 0,0\n',bounded)
            self.assertIn('gb_dispatch_page_000_03:\n\tdc.b 81,3\n',bounded)
            # Instruction operands are not entry slots: root page has one.
            self.assertEqual(after['dispatch_table_bytes'],4+2*1024+6+6+14)
            self.assertEqual(after['dispatch_table_bytes'],before['dispatch_trimmed_table_bytes'])
            self.assertLess(after['dispatch_table_bytes'],before['dispatch_table_bytes'])
            page=bounded.split('gb_dispatch_page_000_03:\n')[1].split('\teven')[0]
            self.assertEqual(page.count('(gb_missing_block>>16)'),2)

    def test_full_page_uses_inclusive_span_255_without_wrapping(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);rom=bytearray(0x8000)
            rom[0x100:0x103]=bytes.fromhex('c30002');rom[0x300]=0xC9
            source=root/'original.gb';source.write_bytes(rom)
            blocks=trace.compile_trace(source,root/'out',1)
            trace.emit_native_blocks(blocks,root/'out',dispatch_format='trimmed')
            assembly=(root/'out/translated_trace.s').read_text()
            self.assertIn('gb_dispatch_page_000_02:\n\tdc.b 0,255\n',assembly)
            page=assembly.split('gb_dispatch_page_000_02:\n')[1].split('\teven')[0]
            self.assertIn('(L_gb_B000_02FF>>16)',page)

    # Reuse the original external probes with the bounded leaf format. They
    # execute high/odd addresses, page edges, IRQs, mapping and missing entries.
    test_native_high_address_and_odd_slot_and_page_boundary = packed.PackedDispatchTests.test_native_high_address_and_odd_slot_and_page_boundary
    test_native_missing_slots_pages_banks_retain_diagnostics = packed.PackedDispatchTests.test_native_missing_slots_pages_banks_retain_diagnostics
    test_native_irq_and_banked_control_flow = packed.PackedDispatchTests.test_native_irq_and_banked_control_flow

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_lower_upper_bounds_and_internal_hole(self):
        from run_compat_tests import _run_in_pty,_blastem_values
        for name,entry,program,target in (
                ('below',0x380,'210103e9',0x301),
                ('above',0x330,'21ff03e9',0x3FF),
                ('hole',0x330,'204e214003e9',0x340)):
            with self.subTest(case=name),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);rom=bytearray(0x8000)
                rom[0x100:0x103]=bytes([0xC3,entry&255,entry>>8])
                raw=bytes.fromhex(program);rom[entry:entry+len(raw)]=raw
                if name=='hole':rom[0x380]=0xC9
                source=root/'original.gb';source.write_bytes(rom)
                image=self.native_build(source,root/'out',2)
                rc,out,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(image)],
                    'frames 120\np/x [$ff0000].w [$ff0002].w [$ff0018].l [$ff0038].l\nquit\n',20)
                self.assertFalse(timed,out);self.assertEqual(rc,0,out);v=_blastem_values(out)
                self.assertEqual([v.get(k) for k in ('FF0000.w','FF0002.w','FF0018.l','FF0038.l')],
                                 [0,target,0xBADB10C0,1],out)
