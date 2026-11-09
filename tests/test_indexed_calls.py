import json
import os
import pathlib
import tempfile
import unittest

from trace_recompiler import compile_trace, hl_dispatch_table


def indexed_callback_rom(index=1, tail=True, upper_table=False, upper_helper=False):
    """Original indexed call helper preserving BC/DE/HL across its callback."""
    rom = bytearray(0x8000)
    table = 0x4600 if upper_table else 0x600
    helper = 0x4300 if upper_helper else 0x300
    main = bytes([0x3E,index]) + bytes.fromhex('ea10c0cd3001ea00c078ea01c079ea02c07aea03c07bea04c07cea05c07dea06c018fe')
    rom[0x100:0x100 + len(main)] = main
    caller = bytes.fromhex('013412117856') + bytes([0x21,table&255,table>>8]) + bytes.fromhex('fa10c0')
    caller += bytes([0xC3 if tail else 0xCD,helper&255,helper>>8]) + (b'' if tail else b'\xc9')
    rom[0x130:0x130 + len(caller)] = caller
    body = bytes.fromhex('e5d5c58716005f192a666f11') + bytes([(helper+16)&255,(helper+16)>>8]) + bytes.fromhex('d5e9c1d1e1c9')
    rom[helper:helper + len(body)] = body
    count = 128 if index >= 127 else 2
    entries = bytes.fromhex('0008') * (count - 1) + bytes.fromhex('2008ffff')
    rom[table:table + len(entries)] = entries
    rom[0x800:0x803] = bytes.fromhex('3e11c9')
    rom[0x820:0x82C] = bytes.fromhex('01ffee11ddcc21bbaa3e42c9')
    return bytes(rom)


class IndexedCallTest(unittest.TestCase):
    def test_reference_restores_registers_for_call_tail_and_wrapped_index(self):
        from gb_cpu import CPU, Memory
        for kwargs in ({}, {'tail':False}, {'index':127}, {'index':255},
                       {'upper_table':True}, {'upper_helper':True}):
            with self.subTest(kwargs=kwargs):
                memory=Memory(indexed_callback_rom(**kwargs));cpu=CPU(memory)
                for _ in range(200):cpu.step()
                self.assertEqual(memory.wram[:7],bytes([0x42,0x12,0x34,0x56,0x78,0x46 if kwargs.get('upper_table') else 6,0]))

    def test_static_closure_includes_callbacks_and_preserving_return(self):
        for kwargs in ({}, {'tail':False}, {'index':127}, {'upper_helper':True}):
            with self.subTest(kwargs=kwargs),tempfile.TemporaryDirectory() as folder:
                root=pathlib.Path(folder);source=root/'indexed.gb';source.write_bytes(indexed_callback_rom(**kwargs))
                blocks=compile_trace(source,root/'out',2)
                keys={(b['bank'],b['pc']) for b in blocks}
                self.assertIn((0,0x820),keys)
                self.assertIn((1,0x4310) if kwargs.get('upper_helper') else (0,0x310),keys)
                report=json.loads((root/'out'/'trace-profile.json').read_text())
                self.assertEqual(report['indexed_call_returns'],1)
                self.assertEqual(report['indexed_call_tables'][0]['entry_limit'],128)

    def test_single_entry_is_valid_for_exact_callback_helper(self):
        rom=bytearray(indexed_callback_rom(index=0));rom[0x602:0x604]=b'\xff\xff'
        with tempfile.TemporaryDirectory() as folder:
            root=pathlib.Path(folder);source=root/'single.gb';source.write_bytes(rom)
            blocks=compile_trace(source,root/'out',2)
            self.assertIn((0,0x800),{(b['bank'],b['pc']) for b in blocks})

    def test_table_scan_stops_before_its_forward_code_target(self):
        rom=bytearray(indexed_callback_rom(index=0))
        # Two pointers immediately followed by valid function code. Its first
        # bytes also look like a pointer into unrelated NOP padding at70FA.
        rom[0x600:0x608]=bytes.fromhex('04060706fa70d0c9')
        with tempfile.TemporaryDirectory() as folder:
            root=pathlib.Path(folder);source=root/'bounded.gb';source.write_bytes(rom)
            blocks=compile_trace(source,root/'out',2)
            keys={(b['bank'],b['pc']) for b in blocks}
            self.assertIn((0,0x604),keys)
            self.assertNotIn((0,0x70FA),keys)
            report=json.loads((root/'out'/'trace-profile.json').read_text())
            self.assertEqual(report['indexed_call_tables'][0]['entries'],2)
            self.assertEqual(report['indexed_call_tables'][0]['stop_reason'],'code_boundary')

    def test_rejects_changed_helper_hl_writes_and_unknown_mapping(self):
        original=indexed_callback_rom()
        for address,value in ((0x303,0x86),(0x30C,0x11),(0x310,0xD1)):
            rom=bytearray(original);rom[address]=value
            with self.subTest(address=address):self.assertIsNone(hl_dispatch_table(rom,0,0x136))
        rom=bytearray(original);rom[0x139]=0x23
        self.assertIsNone(hl_dispatch_table(rom,0,0x136))
        rom=bytearray(indexed_callback_rom(upper_table=True));rom[0x147]=0x11
        with tempfile.TemporaryDirectory() as folder:
            root=pathlib.Path(folder);source=root/'unknown.gb';source.write_bytes(rom)
            blocks=compile_trace(source,root/'out',2)
            self.assertNotIn((0,0x820),{(b['bank'],b['pc']) for b in blocks})

    def test_alias_return_is_checked_against_resolved_helper(self):
        rom=bytearray(indexed_callback_rom());body=bytearray(rom[0x300:0x314])
        body[12:14]=bytes.fromhex('5003');rom[0x340:0x354]=body;rom[0x300:0x303]=bytes.fromhex('c34003')
        diagnostic={};self.assertEqual(hl_dispatch_table(rom,0,0x136,diagnostic),0x600)
        self.assertEqual(diagnostic['return_address'],0x350)
        rom[0x340:0x343]=bytes.fromhex('c30003')
        self.assertIsNone(hl_dispatch_table(rom,0,0x136))

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_preserving_callbacks(self):
        from build_recompiled import build
        from run_compat_tests import _run_in_pty,_blastem_values
        for kwargs in ({}, {'tail':False}, {'index':127}, {'upper_helper':True}):
            with self.subTest(kwargs=kwargs),tempfile.TemporaryDirectory() as folder:
                from unittest.mock import patch
                import build_recompiled as compiler
                root=pathlib.Path(folder);source=root/'indexed.gb';source.write_bytes(indexed_callback_rom(**kwargs))
                discover=compiler.compile_trace
                def without_catalog(*args,**options):
                    from trace_recompiler import emit_native_blocks
                    blocks=discover(*args,**options)
                    emit_native_blocks(blocks,args[1],include_block_table=False)
                    return blocks
                with patch.object(compiler,'compile_trace',side_effect=without_catalog):
                    build(source,root/'out',2)
                report=json.loads((root/'out'/'native-codegen-report.json').read_text())
                self.assertFalse(report['block_catalog_included'])
                addresses=[f'FF230{i}.b' for i in range(7)]+['FF0018.l']
                commands='frames 600\np/x '+' '.join('[$'+a.split('.')[0].lower()+'].'+a.split('.')[1] for a in addresses)+'\nquit\n'
                code,output,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(root/'out'/'recompiled.md')],commands,30)
                self.assertFalse(timed,output);self.assertEqual(code,0,output)
                values=_blastem_values(output)
                self.assertEqual([values.get(a) for a in addresses],[0x42,0x12,0x34,0x56,0x78,6,0,0],output)
