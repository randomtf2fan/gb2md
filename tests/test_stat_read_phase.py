"""Original programs for STAT read-cycle sampling; no external ROM code/data."""
import os
from pathlib import Path
import tempfile
import unittest
from gb_cpu import CPU, Memory

FORMS={'hl':(bytes.fromhex('7e'),4),'ldh':(bytes.fromhex('f041'),8),
       'absolute':(bytes.fromhex('fa41ff'),12),'bit':(bytes.fromhex('cb46'),8),
       'rotate':(bytes.fromhex('cb0e'),8),'pop-low':(bytes.fromhex('c1'),4),
       'pop-high':(bytes.fromhex('c1'),8)}
CASES=[(form,dot) for form in ('hl','ldh','absolute') for dot in (76,80,248,252)]
CASES += [(form,dot) for form in ('bit','rotate','pop-low','pop-high') for dot in (76,80)]


def cartridge(form,dot):
    opcode,prefix=FORMS[form]
    rom=bytearray(0x8000);rom[0x100:0x103]=bytes.fromhex('c35001')
    code=bytearray.fromhex('f33100dfafe040e041e007e00feaffff2141ff')
    if form.startswith('pop'):
        code+=bytes((0x31,0x41 if form=='pop-low' else 0x40,0xff))
    code+=bytes.fromhex('3e80e040')
    code+=bytes((456+dot-prefix)//4)+opcode
    if form.startswith('pop'):
        code+=bytes.fromhex('78ea00c079ea01c03100df')
    else:
        code+=bytes.fromhex('ea00c0f5c179ea01c0')
    code+=bytes.fromhex('f041ea02c03ea5ea03c018fe')
    rom[0x150:0x150+len(code)]=code
    return bytes(rom)


def reference(form,dot):
    memory=Memory(cartridge(form,dot));cpu=CPU(memory)
    for _ in range(2000):
        cpu.step()
        if memory.wram[3]==0xa5:break
    assert memory.wram[3]==0xa5
    return memory,cpu


class StatReadPhaseTests(unittest.TestCase):
    def test_read_samples_old_mode_but_completes_cycles_and_interrupt_edge(self):
        m=Memory(bytes(0x8000));m.write(0xff41,8);m.tick(456+248)
        m.write(0xff0f,0);cpu=CPU(m);before=m.cycles
        self.assertEqual(cpu.read_cycle(0xff41)&3,3)
        self.assertEqual(m.cycles,before+4)
        self.assertEqual(m.read(0xff41)&3,0)
        self.assertEqual(m.io[15]&2,2)

    def test_original_instruction_forms_have_explicit_boundary_expectations(self):
        for form,dot in CASES:
            with self.subTest(form=form,dot=dot):
                m,c=reference(form,dot);mode=2 if dot<80 else 3 if dot<252 else 0
                if form in ('hl','ldh','absolute'):
                    self.assertEqual(m.wram[0],0x80|mode)
                elif form=='bit':self.assertEqual(m.wram[1],0xa0 if mode==2 else 0x20)
                elif form=='rotate':self.assertEqual(m.wram[1],0 if mode==2 else 0x10)
                elif form=='pop-low':self.assertEqual(m.wram[1],0x80|mode)
                else:self.assertEqual(m.wram[0],0x80|mode)
                self.assertEqual(c.sp,0xdf00)

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_read_forms_match_reference_at_both_mode_boundaries(self):
        from build_recompiled import build
        from run_compat_tests import _run_in_pty,_blastem_values
        for form,dot in CASES:
            with self.subTest(form=form,dot=dot),tempfile.TemporaryDirectory() as folder:
                m,c=reference(form,dot);root=Path(folder);source=root/'original.gb'
                source.write_bytes(cartridge(form,dot));image=build(source,root/'out',2000)
                rc,out,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(image)],
                    'frames 180\np/x [$ff2300].l [$ff0010].w [$ff0018].l [$ff0038].l\nquit\n',25)
                self.assertFalse(timed,out);self.assertEqual(rc,0,out);values=_blastem_values(out)
                self.assertEqual(values.get('FF2300.l'),int.from_bytes(m.wram[:4],'big'),out)
                self.assertEqual(values.get('FF0010.w'),c.sp,out)
                self.assertEqual(values.get('FF0018.l'),0,out);self.assertEqual(values.get('FF0038.l'),0,out)
