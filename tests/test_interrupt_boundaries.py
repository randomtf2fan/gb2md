"""Original request/enable ordering fixtures; no commercial code or addresses."""
import os,tempfile,unittest
from pathlib import Path
from gb_cpu import CPU,Memory


def interrupt_boundary_rom(trigger='request'):
    rom=bytearray(0x8000);rom[0x50:0x52]=bytes.fromhex('3cc9') # IRQ increments A, then returns.
    code=bytes.fromhex('f331fedfafe040e00feaffff')
    if trigger=='request':
        code+=bytes.fromhex('3e04eafffffb003e04e00f')
    elif trigger=='enable':
        code+=bytes.fromhex('3e04e00ffb003e04eaffff')
    elif trigger=='disabled':
        code+=bytes.fromhex('3e04eaffff3e04e00f')
    elif trigger=='push_ie':
        code+=bytes.fromhex('310000010104c531fedff0feea02c0f0ff')
    elif trigger=='delayed_ei':
        code+=bytes.fromhex('3e04eaffff3e04e00ffb00')
    else:raise ValueError(trigger)
    code+=bytes.fromhex('ea00c0')+b'\x00'*80+bytes.fromhex('ea01c018fe')
    rom[0x100:0x103]=bytes.fromhex('c35001');rom[0x150:0x150+len(code)]=code
    return bytes(rom)


class InterruptBoundaryTests(unittest.TestCase):
    def test_reference_request_enable_disabled_and_ei_order(self):
        for trigger in ('request','enable','disabled','delayed_ei','push_ie'):
            with self.subTest(trigger=trigger):
                memory=Memory(interrupt_boundary_rom(trigger));cpu=CPU(memory)
                for _ in range(500):cpu.step()
                value=4 if trigger in ('disabled','push_ie') else 5
                self.assertEqual(list(memory.wram[:2]),[value,value])
                self.assertEqual(cpu.sp,0xDFFE)
                if trigger=='push_ie':self.assertEqual(memory.wram[2],1)

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_matches_reference_at_next_instruction(self):
        from build_recompiled import build
        from run_compat_tests import _run_in_pty,_blastem_values
        for trigger in ('request','enable','disabled','delayed_ei','push_ie'):
            with self.subTest(trigger=trigger),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);source=root/'original.gb';source.write_bytes(interrupt_boundary_rom(trigger))
                artifact=build(source,root/'out',500)
                commands='frames 180\np/x [$ff2300].b [$ff2301].b [$ff2302].b [$ff0010].w [$ff0018].l [$ff0038].l\nquit\n'
                code,output,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(artifact)],commands,20)
                self.assertFalse(timed,output);self.assertEqual(code,0,output);v=_blastem_values(output)
                expected=4 if trigger in ('disabled','push_ie') else 5
                self.assertEqual([v.get('FF2300.b'),v.get('FF2301.b')],[expected,expected],output)
                if trigger=='push_ie':self.assertEqual(v.get('FF2302.b'),1,output)
                self.assertEqual(v.get('FF0010.w'),0xDFFE,output)
                self.assertEqual(v.get('FF0018.l'),0,output);self.assertEqual(v.get('FF0038.l'),0,output)
