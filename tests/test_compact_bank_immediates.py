"""Original capacity encoding probes for shared native scheduler bank arguments."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import build_recompiled as compiler
import trace_recompiler as trace
import test_packed_dispatch as packed


class CompactBankImmediateTests(unittest.TestCase):
    def test_signed_byte_limit_and_exact_savings_without_body_changes(self):
        blocks=[]
        for bank in (0,1,127,128,255,511):
            for pc in (0x4100,0x4101):
                blocks.append(dict(bank=bank,pc=pc,bytes='00',opcode=0,operand=0,family='NOP',hits=1,native_lowered=True,observed_variants=[]))
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            trace.emit_native_blocks(blocks,root,max_hot_chains=0,include_block_table=False)
            before=(root/'translated_trace.s').read_text()
            trace.emit_native_blocks(blocks,root,max_hot_chains=0,include_block_table=False,compact_bank_immediates=True)
            after=(root/'translated_trace.s').read_text();report=json.loads((root/'native-codegen-report.json').read_text())
            for bank in (0,1,127):
                self.assertIn(f'\tmoveq #{bank},d1',after)
                after=after.replace(f'\tmoveq #{bank},d1',f'\tmove.w #${bank:04X},d1')
            for bank in (128,255,511):self.assertIn(f'\tmove.w #${bank:04X},d1',after)
            self.assertEqual(before,after)
            self.assertEqual(report['compact_bank_bytes_saved'],6)
            self.assertEqual(report['blocks'],len(blocks))

    def native_build(self,source,out,steps,pad=False):
        original=compiler.compile_trace
        def discover(*args,**kwargs):
            blocks=original(*args,**kwargs)
            trace.emit_native_blocks(blocks,args[1],dispatch_format='windowed',max_hot_chains=0,compact_bank_immediates=True)
            return blocks
        with patch.object(compiler,'compile_trace',side_effect=discover):return compiler.build(source,out,steps)

    test_native_irq_and_banked_control_flow=packed.PackedDispatchTests.test_native_irq_and_banked_control_flow
    test_native_missing_slots_pages_banks_retain_diagnostics=packed.PackedDispatchTests.test_native_missing_slots_pages_banks_retain_diagnostics
