"""Original stack bus-phase diagnostics, generated without external ROM data."""
import os,tempfile,unittest
from pathlib import Path
from gb_cpu import CPU,Memory


def stack_read_rom(kind):
    sp=0xFF03 if kind=='pop-high' else 0xFF04
    if kind=='wram':sp=0xC100
    if kind=='wrap':sp=0xFFFF
    opcode={'ret':0xC9,'reti':0xD9,'retcc':0xC0,'untaken':0xC8,'wram':0xC9}.get(kind,0xD1)
    # 244T after DIV reset (240T for RET cc's extra condition cycle).
    setup=bytes.fromhex('f3afe040')+bytes([0x31,sp&255,sp>>8])+bytes.fromhex('3e01b7e004')
    code=setup+bytes(57 if kind=='retcc' else 58)+bytes.fromhex('213412')+bytes([opcode])+bytes.fromhex('c30003')
    rom=bytearray(0x8000);rom[:4]=bytes.fromhex('00c30003');rom[0x100:0x103]=bytes.fromhex('c35001')
    rom[0x150:0x150+len(code)]=code
    success=bytes.fromhex('7bea14c07aea15c0f8007dea11c07cea12c03e42ea10c018fe')
    rom[0x300:0x300+len(success)]=success
    return bytes(rom)


def reference(kind):
    memory=Memory(stack_read_rom(kind));cpu=CPU(memory)
    for _ in range(250):cpu.step()
    return memory,cpu


class StackReadTimingTests(unittest.TestCase):
    def test_original_bus_phase_fixtures_and_lowering(self):
        from trace_recompiler import compile_trace
        for kind in ('pop-low','pop-high','ret','reti','retcc','untaken','wram','wrap'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as folder:
                memory,cpu=reference(kind)
                self.assertEqual(memory.wram[0x10],0x42)
                expected_sp={'untaken':0xFF04,'pop-high':0xFF05,'wram':0xC102,'wrap':1}.get(kind,0xFF06)
                self.assertEqual(memory.wram[0x11:0x13],expected_sp.to_bytes(2,'little'))
                if kind=='pop-low':self.assertEqual(memory.wram[0x14:0x16],bytes([0,0]))
                if kind=='pop-high':self.assertEqual(memory.wram[0x14:0x16],bytes([0,1]))
                root=Path(folder);source=root/'original.gb';source.write_bytes(stack_read_rom(kind))
                compile_trace(source,root/'out',250)
                text=(root/'out'/'translated_trace.s').read_text()
                self.assertIn('jsr gb_pop16_timed',text)
                self.assertIn('cmpi.w #$FDFF,gb_sp',text)
                self.assertIn('moveq #12,d0' if kind in ('retcc','untaken') else 'moveq #8,d0',text)

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_pop_return_phases_match_reference(self):
        from build_recompiled import build
        from run_compat_tests import _run_in_pty,_blastem_values
        for kind in ('pop-low','pop-high','ret','reti','retcc','untaken'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);source=root/'original.gb';source.write_bytes(stack_read_rom(kind));image=build(source,root/'out',250)
                addresses=[f'FF23{n:02X}.b' for n in range(0x10,0x16)]+['FF0018.l','FF0038.l','FF0034.b']
                commands='frames 600\np/x '+' '.join('[$'+x.split('.')[0].lower()+'].'+x.split('.')[1] for x in addresses)+'\nquit\n'
                code,output,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(image)],commands,30)
                self.assertFalse(timed,output);self.assertEqual(code,0,output);values=_blastem_values(output);memory,_=reference(kind)
                self.assertEqual([values.get(x) for x in addresses[:6]],list(memory.wram[0x10:0x16]),output)
                for x in addresses[6:]:self.assertEqual(values.get(x),0,output)
