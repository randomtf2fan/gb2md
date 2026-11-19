"""Original native probes for size-only 24-bit dispatch-table fallback."""
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

import build_recompiled as compiler
import trace_recompiler as trace


class PackedDispatchTests(unittest.TestCase):
    def test_packing_retains_every_block_and_saves_one_byte_per_leaf_slot(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);rom=bytearray(0x8000);rom[0x100:0x105]=bytes.fromhex('21ff01e900')
            rom[0x1FF:0x206]=bytes.fromhex('3e42ea00c018fe');source=root/'original.gb';source.write_bytes(rom)
            blocks=trace.compile_trace(source,root/'out',3)
            trace.emit_native_blocks(blocks,root/'out',dispatch_format='paged')
            wide=(root/'out/translated_trace.s').read_text();a=json.loads((root/'out/native-codegen-report.json').read_text())
            trace.emit_native_blocks(blocks,root/'out',dispatch_format='packed')
            packed=(root/'out/translated_trace.s').read_text();b=json.loads((root/'out/native-codegen-report.json').read_text())
            self.assertEqual(wide.split('gb_dispatch_tree:')[0],packed.split('gb_dispatch_tree:')[0])
            self.assertEqual(b['dispatch_format'],'bank_page_table_24')
            self.assertEqual(b['dispatch_leaf_entry_bytes'],3)
            self.assertEqual(a['dispatch_table_bytes']-b['dispatch_table_bytes'],256*(1+a['dispatch_pages']))
            self.assertEqual(a['blocks'],b['blocks'])

    def test_capacity_fallback_precedes_quota_reduction_and_retains_options(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);rom=bytearray(0x8000);rom[0x100:0x103]=bytes.fromhex('c35001')
            rom[0x650:0x652]=bytes.fromhex('18fe');source=root/'original.gb';source.write_bytes(rom)
            assembler=root/'assembler';assembler.touch();calls=[]
            def assemble(command,**kwargs):
                calls.append(command);Path(command[-1]).write_bytes(bytes(0x400002 if len(calls)<5 else 0x80000))
            with patch.object(compiler,'compile_trace',wraps=compiler.compile_trace) as discovered,patch.object(compiler.subprocess,'run',side_effect=assemble):
                compiler.build(source,root/'out',2,assembler=assembler,optimize_hram=False,optimize_pure_chains=False)
            report=json.loads((root/'out/build-report.json').read_text());a=report['native_layout_attempts']
            self.assertEqual(discovered.call_count,1)
            self.assertEqual([x['dispatch_format'] for x in a],['bank_page_table','bank_page_table','bank_page_table_24','bank_page_table_24_trimmed','bank_page_table_24_trimmed'])
            self.assertEqual([x['block_catalog_included'] for x in a],[True,False,False,False,False])
            self.assertEqual(a[0]['hot_chain_targets'],a[2]['hot_chain_targets'])
            self.assertEqual(a[3]['hot_chain_targets'],a[2]['hot_chain_targets'])
            self.assertEqual(a[4]['hot_chain_targets'],a[3]['hot_chain_targets'])
            self.assertTrue(a[4]['compact_bank_immediates'])
            stats=json.loads((root/'out/native-codegen-report.json').read_text())
            self.assertFalse(stats['optimize_hram']);self.assertFalse(stats['optimize_pure_chains'])

    def native_build(self,source,out,steps,pad=False):
        original=compiler.compile_trace
        def discover(*args,**kwargs):
            blocks=original(*args,**kwargs);trace.emit_native_blocks(blocks,args[1],dispatch_format=getattr(self,'dispatch_format','packed'))
            if pad:
                p=args[1]/'translated_trace.s';s=p.read_text()
                s,count=re.subn(r'(gb_compiled_entry:\n)\tbra.w (L_gb_[^\n]+)',r'\1\tjmp \2\n\tdcb.b $123456,0',s,count=1)
                assert count==1;p.write_text(s)
            return blocks
        with patch.object(compiler,'compile_trace',side_effect=discover):return compiler.build(source,out,steps)

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_high_address_and_odd_slot_and_page_boundary(self):
        from run_compat_tests import _run_in_pty,_blastem_values
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);rom=bytearray(0x8000)
            rom[0x100:0x104]=bytes.fromhex('21ff01e9');rom[0x1FF:0x206]=bytes.fromhex('3e42ea00c018fe')
            source=root/'original.gb';source.write_bytes(rom);image=self.native_build(source,root/'out',3,pad=True)
            self.assertGreater(image.stat().st_size,0x123456)
            rc,out,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(image)],
                'frames 120\np/x [$ff2300].b [$ff0010].w [$ff0018].l [$ff0038].l\nquit\n',20)
            self.assertFalse(timed,out);self.assertEqual(rc,0,out);v=_blastem_values(out)
            self.assertEqual([v.get(k) for k in ('FF2300.b','FF0010.w','FF0018.l','FF0038.l')],[0x42,0xFFFE,0,0],out)

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_missing_slots_pages_banks_retain_diagnostics(self):
        from run_compat_tests import _run_in_pty,_blastem_values
        cases=(('odd-slot','218101e9',0,0x181),('page','21b6ffe9',0,0xFFB6),
               ('bank-limit','3e03ea0020210041e9',3,0x4100),
               ('bank-hole','3e02ea0020cd00413e01ea0020210041e9',1,0x4100))
        for name,program,bank,pc in cases:
            with self.subTest(case=name),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);rom=bytearray(0x10000);rom[0x147:0x14A]=bytes((1,1,0));rom[0x8100]=0xC9
                raw=bytes.fromhex(program);rom[0x100:0x100+len(raw)]=raw;source=root/'original.gb';source.write_bytes(rom)
                image=self.native_build(source,root/'out',2)
                rc,out,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(image)],
                    'frames 120\np/x [$ff0000].w [$ff0002].w [$ff0018].l [$ff0038].l\nquit\n',20)
                self.assertFalse(timed,out);self.assertEqual(rc,0,out);v=_blastem_values(out)
                self.assertEqual([v.get(k) for k in ('FF0000.w','FF0002.w','FF0018.l','FF0038.l')],[bank,pc,0xBADB10C0,1],out)

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_irq_and_banked_control_flow(self):
        from test_smoke import stat_diagnostic_rom,bank_switch_diagnostic_rom
        from run_compat_tests import _run_in_pty,_blastem_values
        for name,rom,expected in (('stat',stat_diagnostic_rom(),[0x42,0x77,0,0]),
                                  ('mapper',bank_switch_diagnostic_rom(),[0x42,0,0,0]),
                                  ('mbc5-zero',bank_switch_diagnostic_rom(0x19,0),[0x42,0,0,0])):
            with self.subTest(case=name),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);source=root/'original.gb';source.write_bytes(rom);image=self.native_build(source,root/'out',600)
                rc,out,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(image)],
                    'frames 600\np/x [$ff2300].b [$ff2301].b [$ff0018].l [$ff0038].l\nquit\n',30)
                self.assertFalse(timed,out);self.assertEqual(rc,0,out);v=_blastem_values(out)
                self.assertEqual([v.get(k) for k in ('FF2300.b','FF2301.b','FF0018.l','FF0038.l')],expected,out)
