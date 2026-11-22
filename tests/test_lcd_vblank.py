"""Original LCD/VBlank event and pending-interrupt regression programs."""
import os,tempfile,unittest
from pathlib import Path
from gb_cpu import CPU,Memory


def diagnostic_rom(case):
    rom=bytearray(0x8000)
    code=bytearray.fromhex('f040ea04c0f331feffafe040e007e041e00feaffff')
    def write_io(address,value):code.extend((0x3e,value,0xe0,address))
    def wait():code.extend(bytes.fromhex('0100180b78b120fb'))
    def sample(index):code.extend((0xf0,0x0f,0xe6,0x1f,0xea,index,0xc0))
    if case=='off':
        write_io(0x41,0x78);write_io(0x0f,0);wait();sample(0)
    elif case=='pending':
        write_io(0x41,0x78);write_io(0x0f,0x1b);wait();sample(0)
    elif case=='on':
        write_io(0x40,0x80);write_io(0x0f,0);wait();sample(0)
    elif case=='toggle':
        wait();sample(0);write_io(0x40,0x80);write_io(0x0f,0)
        wait();sample(1);write_io(0x40,0);write_io(0x0f,0)
        wait();sample(2)
    elif case=='timer':
        write_io(4,0);write_io(6,0xa7);write_io(5,0xff);write_io(7,5)
        wait();sample(0)
    else:raise ValueError(case)
    code.extend(bytes.fromhex('3ea5ea10c0f318fe'))
    rom[0x100:0x100+len(code)]=code
    return bytes(rom)


EXPECTED={'off':[0],'pending':[0x1b],'on':[1],'toggle':[0,1,0],'timer':[4]}


class LcdVblankTests(unittest.TestCase):
    def test_original_postboot_lcdc_observation(self):
        rom=bytearray(0x8000);rom[0x100:0x106]=bytes.fromhex('f040ea00c000')
        c=CPU(Memory(rom));c.step();c.step()
        self.assertEqual(c.m.wram[0],0x91)

    def test_disabled_lcd_never_generates_vblank_or_stat(self):
        for flags in (0,1,2,0x1b):
            with self.subTest(flags=flags):
                m=Memory(bytes(0x8000));m.write(0xff40,0);m.write(0xff41,0x78);m.write(0xff0f,flags)
                m.tick(456*144);m.tick(70224*2)
                self.assertEqual(m.io[15],flags)
                self.assertFalse(m.stat_line)

    def test_bulk_and_machine_cycle_ticks_observe_same_vblank_edges(self):
        for enabled in (False,True):
            a=Memory(bytes(0x8000));b=Memory(bytes(0x8000))
            a.write(0xff40,0x80 if enabled else 0);b.write(0xff40,0x80 if enabled else 0)
            a.tick(70224*2+100)
            for _ in range((70224*2+100)//4):b.tick(4)
            self.assertEqual(a.io,b.io);self.assertEqual(a.io[15]&1,int(enabled))

    def test_acknowledged_vblank_stays_clear_until_next_edge(self):
        m=Memory(bytes(0x8000));m.write(0xff40,0x80)
        m.tick(456*144-4);self.assertFalse(m.io[15]&1)
        m.tick(4);self.assertTrue(m.io[15]&1)
        m.write(0xff0f,0);m.tick(456);self.assertFalse(m.io[15]&1)
        m.tick(70224-456);self.assertTrue(m.io[15]&1)
        m.write(0xff40,0);self.assertTrue(m.io[15]&1)
        m.write(0xff0f,0);m.tick(70224);self.assertFalse(m.io[15]&1)

    def test_original_programs_reference(self):
        for case,expected in EXPECTED.items():
            with self.subTest(case=case):
                c=CPU(Memory(diagnostic_rom(case)))
                for _ in range(100000):
                    c.step()
                    if c.m.wram[0x10]==0xa5:break
                self.assertEqual(c.m.wram[0x10],0xa5)
                self.assertEqual(c.m.wram[4],0x91)
                self.assertEqual(list(c.m.wram[:len(expected)]),expected)
                if case=='timer':self.assertGreater(c.m.div_counter,0)

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_original_programs(self):
        from build_recompiled import build
        from run_compat_tests import _run_in_pty,_blastem_values
        for case,expected in EXPECTED.items():
            with self.subTest(case=case),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);source=root/'original.gb';source.write_bytes(diagnostic_rom(case))
                image=build(source,root/'out',100000)
                rc,out,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(image)],
                    'frames 1800\np/x [$ff2300].b [$ff2301].b [$ff2302].b [$ff2304].b [$ff2310].b [$ff0018].l [$ff0038].l\nquit\n',60)
                self.assertFalse(timed,out);self.assertEqual(rc,0,out);v=_blastem_values(out)
                self.assertEqual(v.get('FF2310.b'),0xa5,out)
                self.assertEqual(v.get('FF2304.b'),0x91,out)
                self.assertEqual([v.get(f'FF230{i}.b') for i in range(len(expected))],expected,out)
                self.assertEqual(v.get('FF0018.l'),0,out);self.assertEqual(v.get('FF0038.l'),0,out)
