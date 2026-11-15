"""Original timer-window fixtures distinguish read/write phases and flags."""
import os,tempfile,unittest
from pathlib import Path
from gb_cpu import CPU,Memory

OPS=('34','35','cb06','cb0e','cb16','cb1e','cb26','cb2e','cb36','cb3e','cb86','cbce','cb46')


def rmw_timing_rom(op,address=0xFF05):
    rom=bytearray(0x8000);rom[0x100:0x103]=bytes.fromhex('c35001')
    prefix=bytes.fromhex('f3afe04031fedf')+bytes([0x21,address&255,address>>8])
    if address!=0xFF05:prefix+=bytes.fromhex('36ff')
    code=prefix+bytes.fromhex('afe0043e35e0063effe0053e05e0073effe00500')+bytes.fromhex(op)
    code+=(bytes.fromhex('f005') if address==0xFF05 else bytes.fromhex('7e'))+bytes.fromhex('ea10c0f5c179ea12c0afe0073e42ea11c018fe')
    rom[0x150:0x150+len(code)]=code
    return bytes(rom)


def reference(op,address=0xFF05):
    m=Memory(rmw_timing_rom(op,address));cpu=CPU(m)
    for _ in range(500):cpu.step()
    return m


class RmwBusTimingTests(unittest.TestCase):
    def test_original_timer_windows_and_readonly_control(self):
        for op in OPS:
            with self.subTest(op=op):self.assertEqual(reference(op).wram[0x11],0x42)
        self.assertEqual(reference('34').wram[0x10:0x13],bytes([0,0x42,0xA0]))
        self.assertEqual(reference('35').wram[0x10:0x13],bytes([0xFE,0x42,0x40]))
        self.assertEqual(reference('cb06').wram[0x10:0x13],bytes([0x36,0x42,0x80]))
        self.assertEqual(reference('cb46').wram[0x10:0x13],bytes([0x35,0x42,0xA0]))

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_values_flags_reload_windows_and_plain_memory(self):
        from build_recompiled import build
        from run_compat_tests import _run_in_pty,_blastem_values
        cases=[(op,0xFF05) for op in ('34','35','cb06','cb86','cbce','cb46')]+[('34',a) for a in (0xC080,0xFE00,0xFFFF)]
        for op,address in cases:
            with self.subTest(op=op,address=address),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);source=root/'original.gb';source.write_bytes(rmw_timing_rom(op,address));image=build(source,root/'out',500)
                command='frames 600\np/x [$ff2310].b [$ff2311].b [$ff2312].b [$ff0018].l [$ff0038].l [$ff0034].b [$ff005c].b\nquit\n'
                code,out,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(image)],command,30)
                self.assertFalse(timed,out);self.assertEqual(code,0,out);v=_blastem_values(out);m=reference(op,address)
                self.assertEqual([v.get(f'FF23{i:02X}.b') for i in range(0x10,0x13)],list(m.wram[0x10:0x13]),out)
                for key in ('FF0018.l','FF0038.l','FF0034.b','FF005C.b'):self.assertEqual(v.get(key),0,out)
