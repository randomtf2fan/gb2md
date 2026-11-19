"""Original tagged-record callback programs, with no commercial game data."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from gb_cpu import CPU, Memory
from trace_recompiler import compile_trace, tagged_callback_table


def tagged_rom(upper=False, selected=0x72):
    rom=bytearray(0x10000 if upper else 0x8000)
    bank=2 if upper else 0
    stream=0x4180 if upper else 0x180
    table=0x4500 if upper else 0x500
    targets=(0x4600,0x4620) if upper else (0x600,0x620)
    script=0x4800 if upper else 0x800
    off=lambda a:bank*0x4000+a-0x4000 if a>=0x4000 and upper else a
    def put(a,b):rom[off(a):off(a)+len(b)]=b
    main=b''
    if upper:
        rom[0x147:0x14a]=bytes((0x11,1,0))
        main+=bytes.fromhex('3e02ea0020')
        rom[0x4620]=0xd3
    setup=bytes((0x21,script&255,script>>8,0xc3,stream&255,stream>>8))
    if upper:
        main+=bytes.fromhex('cd504118fe');put(0x4150,setup)
    else:main+=setup
    put(0x100,main)
    load=stream+6;callback=load+20;return_pc=load+64;done=load+70
    put(stream,bytes((0x2a,0xfe,0,0x28,done-(stream+5),0x4f)))
    put(load,bytes((0x11,table&255,table>>8))+bytes.fromhex('1ab9280513131318f72afeff2803')+bytes.fromhex('7618fe'))
    put(callback,bytes.fromhex('e5131a6f131a6711')+return_pc.to_bytes(2,'little')+bytes.fromhex('d5e9'))
    put(return_pc,bytes((0xe1,0x18,(stream-return_pc-3)&255)))
    put(done,bytes.fromhex('3e99ea01c018fe'))
    put(table,bytes((0x31,targets[0]&255,targets[0]>>8,0x72,targets[1]&255,targets[1]>>8,0xff)))
    put(script,bytes((selected,0xff,0)))
    for target,value in zip(targets,(0x11,0x42)):
        put(target,bytes((0x3e,value,0xea,0,0xc0,0xc9)))
    return bytes(rom),bank,load,table,targets,return_pc,off


class TaggedCallbackTests(unittest.TestCase):
    def discover(self,rom,root):
        source=root/'original.gb';source.write_bytes(rom)
        blocks=compile_trace(source,root/'out',2)
        return {(b['bank'],b['pc']) for b in blocks},json.loads((root/'out/trace-profile.json').read_text())

    def test_reference_and_closure_include_unexecuted_callback_and_return(self):
        for upper in (False,True):
            for selected,value in ((0x31,0x11),(0x72,0x42)):
                with self.subTest(upper=upper,selected=selected),tempfile.TemporaryDirectory() as folder:
                    rom,bank,load,table,targets,ret,_=tagged_rom(upper,selected)
                    cpu=CPU(Memory(rom))
                    for _ in range(150):cpu.step()
                    self.assertEqual(list(cpu.m.wram[:2]),[value,0x99]);self.assertEqual(cpu.sp,0xfffc if upper else 0xfffe)
                    diagnostic={};self.assertEqual(set(tagged_callback_table(rom,bank,load,diagnostics=diagnostic)),{(bank,t) for t in targets})
                    self.assertEqual(diagnostic['stop_reason'],'sentinel')
                    keys,report=self.discover(rom,Path(folder))
                    self.assertTrue({(bank,t) for t in (*targets,ret)}<=keys)
                    self.assertEqual(report['tagged_callback_targets'],2)
                    self.assertEqual(report['tagged_callback_returns'],1)
                    self.assertEqual(report['tagged_callback_tables'][0]['table'],table)
                    if upper:self.assertNotIn((1,targets[1]),keys)

    def test_rejects_search_stride_comparison_branch_and_callback_mutations(self):
        original,bank,load,_,_,ret,off=tagged_rom()
        for delta,raw in ((3,b'\x0a'),(4,b'\xb8'),(6,b'\x04'),(8,b'\x23'),
                          (11,b'\xf6'),(12,b'\x3a'),(15,b'\x20'),
                          (20,b'\xf5'),(21,b'\x23'),(24,b'\x23'),
                          (30,b'\xc5'),(3,bytes.fromhex('ea0020'))):
            rom=bytearray(original);rom[off(load+delta):off(load+delta)+len(raw)]=raw
            with self.subTest(delta=delta):self.assertEqual(tagged_callback_table(rom,bank,load),[])
        for a,b in ((ret,b'\xf1'),(ret+1,b'\xc9'),(ret+2,b'\x00')):
            rom=bytearray(original);rom[off(a)]=b[0]
            self.assertEqual(tagged_callback_table(rom,bank,load),[])

    def test_duplicate_tags_and_invalid_pointers_fail_closed(self):
        original,bank,load,table,_,_,off=tagged_rom()
        for delta,raw in ((3,b'\x31'),(4,bytes.fromhex('00c0')),(4,bytes.fromhex('4000')),(4,bytes.fromhex('0007'))):
            rom=bytearray(original);rom[off(table+delta):off(table+delta)+len(raw)]=raw
            if delta==4 and raw==bytes.fromhex('0007'):rom[0x700]=0xd3
            with self.subTest(raw=raw):self.assertEqual(tagged_callback_table(rom,bank,load),[])

    def test_unknown_bank_and_single_record_not_accepted(self):
        original,bank,load,table,_,_,_=tagged_rom()
        rom=bytearray(original);rom[table+3]=0xff
        self.assertEqual(tagged_callback_table(rom,bank,load),[])
        rom=bytearray(original);rom[0x147]=0x11;rom[load+1:load+3]=bytes.fromhex('0045')
        rom[0x4500:0x4507]=original[table:table+7]
        self.assertEqual(tagged_callback_table(rom,0,load),[])

    def test_record_boundary_and_budget_are_reported(self):
        original,bank,load,table,targets,_,_=tagged_rom()
        diagnostic={};self.assertEqual(len(tagged_callback_table(original,bank,load,2,diagnostic)),2)
        self.assertEqual(diagnostic['stop_reason'],'entry_limit')
        rom=bytearray(original);rom[table+1:table+3]=(table+6).to_bytes(2,'little');rom[table+6]=0xc9
        diagnostic={};self.assertEqual(len(tagged_callback_table(rom,bank,load,diagnostics=diagnostic)),2)
        self.assertEqual(diagnostic['stop_reason'],'code_boundary')
        rom=bytearray(original);rom[load+1:load+3]=bytes.fromhex('fd3f');rom[0x3ffd:0x4000]=bytes((0x31,0,6))
        self.assertEqual(tagged_callback_table(rom,bank,load),[])
        for limit in (0,1,257):self.assertEqual(tagged_callback_table(original,bank,load,limit),[])

    def test_sequence_cannot_cross_bank_window(self):
        rom,bank,load,_,_,_,_=tagged_rom();rom=bytearray(rom)+bytearray(0x8000)
        rom[0x3ff0:0x3ff0+17]=rom[load:load+17]
        self.assertEqual(tagged_callback_table(rom,0,0x3ff0),[])

    def test_relocated_callback_return_and_script_are_operands(self):
        original,bank,load,_,targets,ret,_=tagged_rom()
        rom=bytearray(original);callback=load+36;new_return=load+80
        body=bytearray(rom[load+20:load+32]);body[8:10]=new_return.to_bytes(2,'little')
        rom[load+16]=callback-(load+17)
        rom[callback:callback+12]=body
        rom[new_return:new_return+3]=bytes((0xe1,0x18,(load-6-new_return-3)&255))
        diagnostic={}
        self.assertEqual(set(tagged_callback_table(rom,bank,load,diagnostics=diagnostic)),{(bank,t) for t in targets})
        self.assertEqual(diagnostic['return_address'],new_return)

    def test_mbc5_zero_uses_physical_bank_zero_not_fixed_upper_one(self):
        rom,_,load,_,targets,_,_=tagged_rom(True);rom=bytearray(rom)
        rom[:0x4000]=rom[0x8000:0xc000];rom[0x147]=0x19
        diagnostic={}
        self.assertEqual(set(tagged_callback_table(rom,0,load,diagnostics=diagnostic)),{(0,t) for t in targets})
        self.assertEqual(diagnostic['entries'],2)
        # Truncation must never read through a physical file boundary.
        self.assertEqual(tagged_callback_table(rom[:0x4502],1,load),[])

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_callbacks_restore_script_and_stack_in_both_banks(self):
        from build_recompiled import build
        from run_compat_tests import _run_in_pty,_blastem_values
        for upper in (False,True):
            for selected,value in ((0x31,0x11),(0x72,0x42)):
                with self.subTest(upper=upper,selected=selected),tempfile.TemporaryDirectory() as folder:
                    root=Path(folder);rom,*_=tagged_rom(upper,selected);source=root/'original.gb';source.write_bytes(rom)
                    image=build(source,root/'out',2)
                    rc,out,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(image)],
                        'frames 120\np/x [$ff2300].b [$ff2301].b [$ff0018].l [$ff0038].l\nquit\n',25)
                    self.assertFalse(timed,out);self.assertEqual(rc,0,out);values=_blastem_values(out)
                    self.assertEqual([values.get(k) for k in ('FF2300.b','FF2301.b','FF0018.l','FF0038.l')],[value,0x99,0,0],out)
