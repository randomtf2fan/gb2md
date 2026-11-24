"""Original standard-MBC1 cartridges; no external ROM data or game rules."""
import copy
import json
import os
import pickle
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from cartridge_banking import mbc1_rom_bank_mask
from gb_cpu import CPU, Memory


def cartridge(banks=64,ram=2):
    rom=bytearray(banks*0x4000)
    rom[0x147:0x14a]=bytes((3,banks.bit_length()-2,ram))
    for bank in range(banks):
        rom[bank*0x4000+0x200:bank*0x4000+0x2a0]=bytes([bank])*160
    return rom


def execution_fixture(ram=2):
    rom=cartridge(ram=ram)
    rom[0x100:0x103]=bytes.fromhex('c35001')
    rom[0x150:0x15e]=bytes.fromhex('f331fedfafe040e007e00fc30041')
    # This transfer runs from HRAM while DMA blocks cartridge accesses.
    helper=bytes.fromhex('3e02e0463e503d20fdc9')
    code=bytearray.fromhex('2180ff')
    for value in helper:code+=bytes((0x3e,value,0x22))
    code+=bytes.fromhex('3e0aea00003e01ea00403e01ea0060')
    code+=bytes.fromhex('3e01eaffffe00ffb0000f3cd0008ea00c0fa0002ea01c0fa0042ea02c0')
    code+=bytes.fromhex('3e5aea00a03e03ea0040fa00a0ea03c0')
    code+=bytes.fromhex('cd80fffa00feea04c0fa9ffeea05c0')
    code+=bytes.fromhex('afea0060ea00403e01ea00203ea5ea06c018fe')
    for bank in range(1,64):
        rom[bank*0x4000+0x100:bank*0x4000+0x100+len(code)]=code
    rom[32*0x4000+0x800:32*0x4000+0x804]=bytes.fromhex('cd1008c9')
    rom[32*0x4000+0x810:32*0x4000+0x814]=bytes.fromhex('211808e9')
    rom[32*0x4000+0x818:32*0x4000+0x81d]=bytes.fromhex('3e42b7c0c9')
    rom[32*0x4000+0x40:32*0x4000+0x48]=bytes.fromhex('fa08c03cea08c0d9')
    return bytes(rom)


class Mbc1MappingTests(unittest.TestCase):
    def test_all_latches_modes_and_disconnected_rom_lines(self):
        for banks in (2,4,32,64,128):
            memory=Memory(bytes(cartridge(banks)))
            self.assertEqual(mbc1_rom_bank_mask(memory.rom),banks-1)
            for mode in range(2):
                memory.write(0x6000,mode)
                for high in range(4):
                    memory.write(0x4000,high)
                    for low in range(32):
                        memory.write(0x2000,low)
                        upper=((high<<5)|(low or 1))&(banks-1)
                        lower=((high<<5)&(banks-1)) if mode else 0
                        self.assertEqual(memory._rom_bank,(high<<5)|low)
                        self.assertEqual((memory.rom_bank,memory.rom0_bank),(upper,lower))
                        self.assertEqual((memory.read(0x4200),memory._dma_read(0x4200)),(upper,upper))
                        self.assertEqual((memory.read(0x200),memory._dma_read(0x200)),(lower,lower))
            self.assertIsNone(mbc1_rom_bank_mask(memory.rom[:-1]))

    def test_ram_mode_changes_enable_and_address_mirroring(self):
        for ram,size in ((0,0),(1,0x800),(2,0x2000),(3,0x8000)):
            memory=Memory(bytes(cartridge(4,ram)))
            memory.write(0xa000,7);self.assertEqual(memory.read(0xa000),255)
            memory.write(0,0xfa);memory.write(0x4000,3);memory.write(0x6000,1)
            memory.write(0xa000,0x42)
            expected=0x42 if size else 255
            self.assertEqual(memory.read(0xa000),expected)
            memory.write(0x6000,0)
            self.assertEqual(memory.read(0xa000),0 if ram==3 else expected)
            memory.write(0x6000,1);self.assertEqual(memory.read(0xa000),expected)
            if ram==1:self.assertEqual(memory.read(0xa800),0x42)
            memory.write(0,0xb);self.assertEqual(memory.read(0xa000),255)

    def test_snapshots_preserve_raw_upper_register_and_lower_identity(self):
        from trace_recompiler import exploration_state_key
        memory=Memory(bytes(cartridge()));cpu=CPU(memory)
        memory.write(0x2000,0);memory.write(0x4000,3);memory.write(0x6000,1)
        for cloned in (copy.deepcopy(memory),pickle.loads(pickle.dumps(memory))):
            self.assertEqual((cloned._rom_bank,cloned.rom_bank,cloned.rom0_bank),(96,33,32))
            cloned.write(0x6000,0);self.assertEqual((cloned.rom_bank,cloned.rom0_bank),(33,0))
        legacy=Memory.__new__(Memory);legacy.__dict__.update(memory.__dict__)
        legacy.__dict__.pop('mbc1_latch_version');legacy.__dict__['rom_bank']=legacy.__dict__.pop('_rom_bank')
        legacy.ram_bank=3
        restored=pickle.loads(pickle.dumps(legacy))
        self.assertEqual((restored.rom_bank,restored.rom0_bank),(33,32))
        before=exploration_state_key(cpu);memory.write(0x4000,1)
        self.assertEqual(memory.rom_bank,33);self.assertNotEqual(before,exploration_state_key(cpu))
        cpu.pc=0x200;cpu.step();self.assertEqual(cpu.last_bank,32)

    def test_reference_lower_code_ram_and_dma(self):
        for ram in (0,1,2,3):
            memory=Memory(execution_fixture(ram));cpu=CPU(memory)
            for _ in range(2000):cpu.step()
            self.assertEqual(memory.wram[:7],bytes((0x42,32,33,255 if ram==0 else 0 if ram==3 else 0x5a,32,32,0xa5)))
            self.assertEqual(memory.oam,bytes([32])*160)
            self.assertEqual(memory.wram[8],1)
            self.assertEqual((memory.rom0_bank,memory.rom_bank,cpu.sp),(0,1,0xdffe))

    def test_lower_rom_coverage_round_trip_and_windowed_directory(self):
        import trace_recompiler as trace
        from coverage_profiles import load_coverage_profiles
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'original.gb';source.write_bytes(execution_fixture())
            blocks=trace.compile_trace(source,root/'out',2000)
            self.assertIn((32,0x800),{(b['bank'],b['pc']) for b in blocks})
            self.assertNotIn((0,0x800),{(b['bank'],b['pc']) for b in blocks})
            self.assertIn((32,0x40),{(b['bank'],b['pc']) for b in blocks})
            profiles=load_coverage_profiles(source.read_bytes(),[root/'out/trace-profile.json'])
            self.assertTrue(profiles)
            self.assertEqual(next(b['bytes'] for b in blocks if b['bank']==32 and b['pc']==0x800),'cd1008')
            trace.emit_native_blocks(blocks,root/'out',dispatch_format='windowed')
            stats=json.loads((root/'out/native-codegen-report.json').read_text())
            self.assertEqual(stats['dispatch_format'],'bank_page_table_24_windowed')
            text=(root/'out/translated_trace.s').read_text()
            self.assertIn('gb_dispatch_page_020_08',text)
            self.assertNotIn('subi.w #$40,d0',text.split('gb_dispatch_tree:')[1])

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_lower_rom_execution_ram_and_dma(self):
        import build_recompiled as compiler
        import trace_recompiler as trace
        from run_compat_tests import _run_in_pty,_blastem_values
        for ram,layout in ((0,'windowed'),(1,'windowed'),(2,'tree'),(2,'windowed'),(3,'windowed')):
            with self.subTest(ram=ram,layout=layout),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);source=root/'original.gb';source.write_bytes(execution_fixture(ram))
                original=compiler.compile_trace
                def discover(*args,**kwargs):
                    blocks=original(*args,**kwargs);trace.emit_native_blocks(blocks,args[1],dispatch_format=layout);return blocks
                with patch.object(compiler,'compile_trace',side_effect=discover):image=compiler.build(source,root/'out',2000)
                commands='frames 360\np/x [$ff2300].l [$ff2304].l [$ff0010].w [$ff0018].l [$ff0038].l [$ff00a2].w [$ff2308].b\n'
                commands+=''.join('p/x '+' '.join(f'[$ff{0x200+i:04x}].l' for i in range(start,start+40,4))+'\n' for start in range(0,160,40))+'quit\n'
                rc,out,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(image)],commands,45)
                self.assertFalse(timed,out);self.assertEqual(rc,0,out);values=_blastem_values(out)
                expected=bytes((0x42,32,33,255 if ram==0 else 0 if ram==3 else 0x5a,32,32,0xa5,0))
                for i in (0,4):self.assertEqual(values.get(f'FF{0x2300+i:04X}.l'),int.from_bytes(expected[i:i+4],'big'),out)
                self.assertEqual(values.get('FF0010.w'),0xdffe,out)
                self.assertEqual(values.get('FF0018.l'),0,out);self.assertEqual(values.get('FF0038.l'),0,out)
                self.assertEqual(values.get('FF00A2.w'),0,out)
                self.assertEqual(values.get('FF2308.b'),1,out)
                for i in range(0,160,4):self.assertEqual(values.get(f'FF{0x200+i:04X}.l'),0x20202020,out)
