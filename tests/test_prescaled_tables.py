"""Original fixtures for ROM tables indexed by an already prepared byte offset."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from gb_cpu import CPU, Memory
from trace_recompiler import compile_trace, hl_dispatch_table


def lookup_rom(index=1, scale=True, upper=False):
    rom=bytearray(0x10000 if upper else 0x8000)
    pc,table,target=(0x4100,0x4500,0x4600) if upper else (0x100,0x900,0x600)
    offset=lambda address:2*0x4000+address-0x4000 if upper else address
    if upper:
        rom[0x147:0x14A]=bytes((0x11,1,0))
        rom[0x100:0x10A]=bytes.fromhex('3e02ea0020cd004118fe')
        rom[0x4620]=0xD3  # Same logical address in the wrong physical bank.
    raw=bytes([0x3E,index])+(b'\x87' if scale else b'')
    base=pc+len(raw)
    raw+=bytes([0x21,table&255,table>>8])+bytes.fromhex('06004f092a666fe9')
    start=offset(pc);rom[start:start+len(raw)]=raw
    count=128 if index>=127 else 2
    pointers=bytes([target&255,target>>8])*(count-1)+bytes([(target+0x20)&255,(target+0x20)>>8])+b'\xff\xff'
    rom[offset(table):offset(table)+len(pointers)]=pointers
    for address,value in ((target,0x11),(target+0x20,0x42)):
        rom[offset(address):offset(address)+7]=bytes([0x3E,value,0xEA,0,0xC0,0x18,0xFE])
    return bytes(rom),base,table,(2 if upper else 0,target+0x20)


class PrescaledTableTests(unittest.TestCase):
    def discover(self,root,rom):
        source=root/'original.gb';source.write_bytes(rom)
        blocks=compile_trace(source,root/'out',2)
        return {(b['bank'],b['pc']) for b in blocks},json.loads((root/'out/trace-profile.json').read_text())

    def test_reference_and_short_trace_find_selected_targets(self):
        for options in ({},{'index':2,'scale':False},{'index':127},{'index':255},{'upper':True}):
            with self.subTest(options=options),tempfile.TemporaryDirectory() as folder:
                rom,base,table,target=lookup_rom(**options);memory=Memory(rom);cpu=CPU(memory)
                for _ in range(100):cpu.step()
                self.assertEqual(memory.wram[0],0x42)
                self.assertEqual(hl_dispatch_table(rom,target[0],base),table)
                keys,report=self.discover(Path(folder),rom)
                self.assertIn(target,keys)
                if options.get('upper'):self.assertNotIn((1,target[1]),keys)
                self.assertEqual(report['indexed_call_tables'],[])
                self.assertEqual(report['indexed_call_returns'],0)
                self.assertEqual(len(report['inline_byte_offset_tables']),1)
                self.assertEqual(report['inline_byte_offset_tables'][0]['entry_limit'],128)

    def test_rejects_changed_index_load_pointer_order_and_bank_effects(self):
        original,base,_,_=lookup_rom()
        for position,value in ((4,1),(5,0x48),(6,0x19),(7,0x3A),(8,0x6E),(9,0x67),(10,0xE8)):
            rom=bytearray(original);rom[base+position]=value
            with self.subTest(position=position):self.assertIsNone(hl_dispatch_table(rom,0,base))
        rom=bytearray(original);rom[base+3:base+6]=bytes.fromhex('ea0020')
        self.assertIsNone(hl_dispatch_table(rom,0,base))

    def test_table_scan_stops_before_forward_code(self):
        rom,base,_,_=lookup_rom();rom=bytearray(rom);rom[base+1:base+3]=bytes.fromhex('0005')
        rom[0x500:0x508]=bytes.fromhex('04050705fa70d0c9')
        with tempfile.TemporaryDirectory() as folder:
            keys,report=self.discover(Path(folder),rom)
            self.assertIn((0,0x504),keys);self.assertIn((0,0x507),keys)
            self.assertNotIn((0,0x70FA),keys)
            record=report['inline_byte_offset_tables'][0]
            self.assertEqual(record['entries'],2);self.assertEqual(record['stop_reason'],'code_boundary')

    def test_unknown_upper_mapping_and_incomplete_tables_do_not_add_roots(self):
        original,base,table,target=lookup_rom()
        for name in ('unknown-bank','single-pointer','window-edge'):
            with self.subTest(case=name),tempfile.TemporaryDirectory() as folder:
                rom=bytearray(original)
                if name=='unknown-bank':
                    rom[0x147]=0x11;rom[base+1:base+3]=bytes.fromhex('0045')
                    rom[0x4500:0x4506]=bytes.fromhex('00062006ffff')
                elif name=='single-pointer':rom[table+2:table+4]=b'\xff\xff'
                else:rom[base+1:base+3]=bytes.fromhex('ff7f')
                keys,report=self.discover(Path(folder),rom)
                self.assertNotIn(target,keys);self.assertEqual(report['inline_byte_offset_tables'],[])

    def test_instruction_sequence_cannot_cross_rom_window(self):
        rom,base,_,_=lookup_rom();rom=bytearray(rom)+bytearray(0x8000)
        raw=rom[base:base+11];rom[0x7FF7:0x8002]=raw
        self.assertIsNone(hl_dispatch_table(rom,1,0x7FF7))

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_prescaled_byte_index_and_physical_bank(self):
        from build_recompiled import build
        from run_compat_tests import _run_in_pty,_blastem_values
        for options in ({},{'index':2,'scale':False},{'index':127},{'upper':True}):
            with self.subTest(options=options),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);rom,_,_,_=lookup_rom(**options);source=root/'original.gb';source.write_bytes(rom)
                image=build(source,root/'out',2)
                rc,out,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(image)],
                    'frames 120\np/x [$ff2300].b [$ff0018].l [$ff0038].l\nquit\n',20)
                self.assertFalse(timed,out);self.assertEqual(rc,0,out);v=_blastem_values(out)
                self.assertEqual([v.get(k) for k in ('FF2300.b','FF0018.l','FF0038.l')],[0x42,0,0],out)
