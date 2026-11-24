"""Original cartridges exercise physical aliases without external ROM data."""
import copy,json,os,pickle,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from cartridge_banking import mbc5_rom_bank_mask,physical_rom_bank
from gb_cpu import CPU,Memory


def cartridge(banks=4,mapper=0x19):
    rom=bytearray(banks*0x4000)
    rom[0x147]=mapper;rom[0x148]=banks.bit_length()-2
    for bank in range(banks):
        rom[bank*0x4000+0x200:bank*0x4000+0x202]=bytes((bank&255,bank>>8))
    return rom


def alias_fixture(partial=False):
    rom=cartridge();rom[0x100:0x103]=bytes.fromhex('c35001')
    code=bytearray.fromhex('f331fedfafe040e007e00feaffff')
    helper=bytes.fromhex('3e40e0463e503d20fdc9')
    if partial=='lower':helper=bytes((0x3e,8))+helper[2:]
    code+=bytes.fromhex('2180ff')
    for value in helper:code+=bytes((0x3e,value,0x22))
    setup_length=len(code)
    code+=bytes.fromhex('3efdea00203effea0030cd0041ea00c0fa0042ea01c0')
    code+=bytes.fromhex('afea00303e04ea0020cd0048ea02c0')
    code+=bytes.fromhex('3effea0030cd0048ea03c03e05ea0020cd80ff')
    code+=bytes.fromhex('fa00feea04c0fa9ffeea05c0f004ea07c03ea5ea06c0')
    if partial:
        code=code[:setup_length]
        code+=bytes.fromhex('3e01ea0020')
        page=8 if partial=='lower' else 0x40
        code+=bytes((0xfa,0,page,0xea,0,0xc0,0xfa,15 if partial=='lower' else 16,page,0xea,1,0xc0))
        code+=bytes.fromhex('3e01ea0030fa0040ea02c0afea0030cd80ff')
        code+=bytes.fromhex('fa00feea03c0fa0ffeea04c0fa10feea05c0f004ea07c03ea5ea06c0')
    code+=bytes.fromhex('18fe');rom[0x150:0x150+len(code)]=code
    rom[0x800:0x803]=bytes.fromhex('3e99c9')
    rom[0x4000:0x40a0]=bytes(((i*17)^0x5a)&255 for i in range(160))
    rom[0x4100:0x4103]=bytes.fromhex('3e42c9');rom[0x4200]=0x5a
    if partial:
        rom[0x148]=0
        if partial=='lower':
            rom[0x800:0x80f]=bytes(range(0xa0,0xaf))
            return bytes(rom[:0x80f])
        rom[0x4000:0x4010]=bytes(range(0xa0,0xb0))
        return bytes(rom[:0x4010])
    return bytes(rom)


class CountingMemory(Memory):
    def __init__(self,rom):super().__init__(rom);self.writes=0
    def write(self,a,v,bus_phase=0):
        self.writes+=1;super().write(a,v,bus_phase=bus_phase)


class Mbc5AliasTests(unittest.TestCase):
    def test_physical_mask_requires_complete_standard_mbc5_image(self):
        for banks in (2,4,64,512):
            rom=cartridge(banks);self.assertEqual(mbc5_rom_bank_mask(rom),banks-1)
        for mapper in (0,1,0x11):self.assertIsNone(mbc5_rom_bank_mask(cartridge(mapper=mapper)))
        rom=cartridge();self.assertIsNone(mbc5_rom_bank_mask(rom[:-1]))
        self.assertIsNone(mbc5_rom_bank_mask(rom[:0x8000])) # truncated, header still64KiB
        self.assertIsNone(mbc5_rom_bank_mask(cartridge(3)))
        rom[0x148]=0x52;self.assertIsNone(mbc5_rom_bank_mask(rom))
        self.assertEqual(physical_rom_bank(rom,7),7)

    def test_latches_reads_and_dma_resolve_all_nine_bit_selections(self):
        for banks in (2,4,64,512):
            memory=Memory(bytes(cartridge(banks)))
            for selected in range(512):
                memory.write(0x3000,selected>>8);memory.write(0x2000,selected&255)
                physical=selected&(banks-1)
                self.assertEqual(memory._rom_bank,selected)
                self.assertEqual(memory.rom_bank,physical)
                self.assertEqual(memory.read(0x4200),physical&255)
                self.assertEqual(memory.read(0x4201),physical>>8)
                self.assertEqual(memory._dma_read(0x4200),physical&255)
                self.assertEqual(memory.read(0x200),0)
            memory.write(0x2000,0);memory.write(0x3000,0)
            self.assertEqual(memory.rom_bank,0) # no MBC1-style zero remapping

    def test_snapshot_and_legacy_pickle_keep_raw_register(self):
        from trace_recompiler import exploration_state_key
        m=Memory(bytes(cartridge()));c=CPU(m);m.write(0x2000,0xfd);m.write(0x3000,1)
        for cloned in (copy.deepcopy(m),pickle.loads(pickle.dumps(m))):
            self.assertEqual((cloned.rom_bank,cloned._rom_bank),(1,0x1fd))
            cloned.write(0x2000,2);self.assertEqual((cloned.rom_bank,cloned._rom_bank),(2,0x102))
        legacy=Memory.__new__(Memory);legacy.__dict__.update(m.__dict__)
        legacy.__dict__['rom_bank']=legacy.__dict__.pop('_rom_bank');legacy.__dict__.pop('rom_bank_mask')
        restored=pickle.loads(pickle.dumps(legacy));self.assertEqual((restored.rom_bank,restored._rom_bank),(1,0x1fd))
        before=exploration_state_key(c);m.write(0x3000,0)
        self.assertEqual(m.rom_bank,1);self.assertNotEqual(before,exploration_state_key(c))

    def test_partial_images_do_not_wrap_missing_data(self):
        rom=cartridge()[:0x8000];m=Memory(bytes(rom));m.write(0x2000,5)
        self.assertEqual(m.rom_bank,5);self.assertEqual(m.read(0x4200),0xff)
        self.assertEqual(m._dma_read(0x4200),0xff)

    def test_static_closure_uses_aliases_including_upper_bank_zero(self):
        from trace_recompiler import compile_trace,constant_bank_call_targets,_selected_bank_candidates
        for selected,bank,target in ((0xfd,1,0x4100),(4,0,0x4800)):
            rom=cartridge();rom[0x100:0x103]=bytes.fromhex('c35001')
            rom[0x150:0x15a]=bytes((0x3e,selected,0xea,0,0x20,0xcd,target&255,target>>8,0x18,0xfe))
            offset=bank*0x4000+target-0x4000;rom[offset:offset+6]=bytes.fromhex('3e42ea00c0c9')
            self.assertEqual(_selected_bank_candidates(rom,selected,0x2000),[bank])
            self.assertEqual(constant_bank_call_targets(rom,0x150),[(bank,target)])
            with tempfile.TemporaryDirectory() as folder:
                root=Path(folder);source=root/'original.gb';source.write_bytes(rom)
                blocks=compile_trace(source,root/'out',2)
                self.assertIn((bank,target),{(b['bank'],b['pc']) for b in blocks})
        self.assertEqual(_selected_bank_candidates(cartridge(512),5,0x2000),[5,261])

    def test_reference_execution_calls_aliases_and_copies_dma(self):
        for partial in (False,True,'lower'):
            memory=CountingMemory(alias_fixture(partial));cpu=CPU(memory)
            for _ in range(1500):cpu.step()
            expected=bytes((0xa0,0xff,0xff,0xa0,0xff if partial=='lower' else 0xaf,0xff,0xa5)) if partial else bytes((0x42,0x5a,0x99,0x99,0x5a,0xd5,0xa5))
            self.assertEqual(memory.wram[:7],expected)
            oam=(bytes(range(0xa0,0xaf))+bytes([255])*145 if partial=='lower' else bytes(range(0xa0,0xb0))+bytes([255])*144) if partial else bytes(((i*17)^0x5a)&255 for i in range(160))
            self.assertEqual(memory.oam,oam)
            self.assertEqual((memory.rom_bank,memory._rom_bank,cpu.sp),(1,1 if partial else 0x105,0xdffe))
            self.assertFalse(memory.dma_active)

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_alias_dispatch_calls_dma_and_flags(self):
        import build_recompiled as compiler
        from trace_recompiler import emit_native_blocks
        from run_compat_tests import _run_in_pty,_blastem_values
        for partial,layout in ((False,'tree'),(False,'windowed'),(True,'tree'),(True,'windowed'),('lower','windowed')):
            memory=CountingMemory(alias_fixture(partial));cpu=CPU(memory)
            for _ in range(1500):cpu.step()
            with self.subTest(layout=layout,partial=partial),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);source=root/'original.gb';source.write_bytes(alias_fixture(partial))
                original=compiler.compile_trace
                def discover(*args,**kwargs):
                    blocks=original(*args,**kwargs)
                    if not partial:
                        self.assertIn((0,0x4800),{(b['bank'],b['pc']) for b in blocks})
                        self.assertIn((1,0x4100),{(b['bank'],b['pc']) for b in blocks})
                    self.assertTrue(all(0<=b['bank']<4 for b in blocks))
                    emit_native_blocks(blocks,args[1],dispatch_format=layout)
                    return blocks
                with patch.object(compiler,'compile_trace',side_effect=discover):image=compiler.build(source,root/'out',5000)
                report=json.loads((root/'out/build-report.json').read_text())
                self.assertEqual(report['mbc5_rom_bank_mask'],None if partial else 3)
                self.assertEqual(report['mbc5_bounded_rom'],bool(partial))
                query='p/x [$ff2300].l [$ff2304].l [$ff0010].w [$ff0014].l [$ff001e].w [$ff00a0].w [$ff0008].b [$ff0009].b [$ff0018].l [$ff0038].l\n'
                addresses=[f'[$ff{0x200+i:04x}].l' for i in range(0,160,4)]
                query+=''.join('p/x '+' '.join(addresses[i:i+10])+'\n' for i in range(0,40,10))
                rc,out,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(image)],'frames 360\n'+query+'quit\n',30)
                self.assertFalse(timed,out);self.assertEqual(rc,0,out);v=_blastem_values(out)
                self.assertEqual(v.get('FF2300.l'),int.from_bytes(memory.wram[:4],'big'),out)
                self.assertEqual(v.get('FF2304.l'),int.from_bytes(memory.wram[4:8],'big'),out)
                self.assertEqual(v.get('FF0010.w'),cpu.sp,out);self.assertEqual(v.get('FF0014.l'),memory.writes,out)
                self.assertEqual(v.get('FF001E.w'),1,out);self.assertEqual(v.get('FF00A0.w'),1 if partial else 0x105,out)
                self.assertEqual((v.get('FF0008.b'),v.get('FF0009.b')),(cpu.a,cpu.f),out)
                self.assertEqual(v.get('FF0018.l'),0,out);self.assertEqual(v.get('FF0038.l'),0,out)
                for i in range(0,160,4):self.assertEqual(v.get(f'FF{0x200+i:04X}.l'),int.from_bytes(memory.oam[i:i+4],'big'),out)
