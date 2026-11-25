"""Original DMG OAM-source-at-VBlank programs; no external test code/assets."""
import os,tempfile,unittest
from pathlib import Path
from gb_cpu import CPU,Memory


def diagnostic_rom(case):
    rom=bytearray(0x8000);rom[0x100:0x103]=bytes.fromhex('c35001')
    rom[0x40]=0xc9;rom[0x48]=0xc9
    mask=0x28 if case=='blocked' else 0x30 if case=='combined' else 0x20
    ie=2 if case=='stat' else 3 if case=='priority' else 1
    code=bytearray.fromhex('f331fedfafe007e00feaffff')
    code+=bytes((0x3e,mask,0xe0,0x41))
    # Stop in the last visible HBlank, then acknowledge old requests.
    code+=bytes.fromhex('f044fe8f20faf041e60320faafe00f')
    if case=='poll':
        code+=bytes.fromhex('f044fe9020fa')
    else:
        code+=bytes((0x3e,ie,0xea,0xff,0xff,0xfb,0))
        if case=='flag':
            rom[0x40:0x46]=bytes.fromhex('3e01ea10c0c9')
            code+=bytes.fromhex('fa10c0a728fa')
        else:code+=bytes.fromhex('7600')
    code+=bytes.fromhex('f3f00fe603ea00c0f041e603ea01c0afe00f')
    code+=b'\x00'*16+bytes.fromhex('f041f00fe603ea02c03ea5ea03c018fe')
    rom[0x150:0x150+len(code)]=code
    return bytes(rom)


EXPECTED={'vblank':2,'stat':1,'priority':2,'blocked':0,'combined':2,'poll':3,'flag':2}


class VblankOamIrqTests(unittest.TestCase):
    def test_vblank_entry_requests_oam_source_without_reporting_mode2(self):
        memory=Memory(bytes(0x8000));memory.write(0xff41,0x20)
        memory.tick(456*144-4);memory.write(0xff0f,0)
        self.assertFalse(memory.stat_line);memory.tick(4)
        self.assertEqual(memory.io[15]&3,3);self.assertEqual(memory.read(0xff41)&3,1)
        self.assertFalse(memory.stat_line) # entry event is not an asserted mode2 level
        memory.write(0xff0f,0)
        for _ in range(100):memory.read(0xff41);memory.tick(4)
        self.assertEqual(memory.io[15]&3,0)
        memory.tick(456*8);self.assertEqual(memory.io[15]&3,0)

    def test_shared_line_blocks_event_and_mode1_remains_level_triggered(self):
        for mask,expected in ((0x20,3),(0x28,1),(0x30,3),(0x38,1)):
            memory=Memory(bytes(0x8000));memory.write(0xff41,mask)
            memory.tick(456*144-4);memory.write(0xff0f,0);memory.tick(4)
            self.assertEqual(memory.io[15]&3,expected,hex(mask))
            memory.write(0xff0f,0);memory.tick(456)
            self.assertEqual(memory.io[15]&3,0,hex(mask))

    def test_disabled_source_and_disabled_lcd_do_not_request_it(self):
        for mask in (0,0x20):
            memory=Memory(bytes(0x8000));memory.write(0xff41,mask)
            if mask:memory.write(0xff40,0)
            memory.write(0xff0f,0);memory.tick(70224*2)
            self.assertFalse(memory.io[15]&2)

    def test_bulk_and_bus_ticks_agree_on_repeated_frame_edges(self):
        for mask in (0x20,0x28,0x30):
            a=Memory(bytes(0x8000));b=Memory(bytes(0x8000))
            for memory in (a,b):memory.write(0xff41,mask);memory.write(0xff0f,0)
            a.tick(70224*2+8)
            for _ in range((70224*2+8)//4):b.tick(4)
            self.assertEqual((a.io,a.stat_line,a.ppu_cycles),(b.io,b.stat_line,b.ppu_cycles))

    def test_reference_original_interrupts_priority_and_masked_requests(self):
        for case,expected in EXPECTED.items():
            memory=Memory(diagnostic_rom(case));cpu=CPU(memory)
            for _ in range(20000):
                cpu.step()
                if memory.wram[3]==0xa5:break
            self.assertEqual(memory.wram[:4],bytes((expected,1,0,0xa5)),case)
            self.assertEqual(cpu.sp,0xdffe)

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_original_halt_flag_priority_and_masked_requests(self):
        import json
        from build_recompiled import build
        from run_compat_tests import _run_in_pty,_blastem_values
        for case,expected in EXPECTED.items():
            with self.subTest(case=case),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);source=root/'original.gb';source.write_bytes(diagnostic_rom(case))
                image=build(source,root/'out',20000)
                if case=='flag':self.assertIn('jsr gb_idle_flag_wait',(root/'out/translated_trace.s').read_text())
                rc,out,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(image)],'frames 600\np/x [$ff2300].l [$ff0010].w [$ff0018].l [$ff0038].l\nquit\n',45)
                self.assertFalse(timed,out);self.assertEqual(rc,0,out);values=_blastem_values(out)
                self.assertEqual(values.get('FF2300.l'),(expected<<24)|0x0100a5,out)
                self.assertEqual(values.get('FF0010.w'),0xdffe,out)
                self.assertEqual(values.get('FF0018.l'),0,out);self.assertEqual(values.get('FF0038.l'),0,out)
