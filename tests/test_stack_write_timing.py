"""Original stack-write bus diagnostics; no external test code or ROM data."""
import os,tempfile,unittest
from pathlib import Path
from gb_cpu import CPU,Memory


def stack_write_rom(kind='push',sp=0xFF05):
    if kind=='reload':
        code=bytes.fromhex('f3afe0403106ff115aa5afe0043effe006e0053e05e00700d5f005ea11c0afe0073e42ea10c018fe')
        rom=bytearray(0x8000);rom[0x100:0x103]=bytes.fromhex('c35001');rom[0x150:0x150+len(code)]=code
        return bytes(rom)
    opcode={'push':0xD5,'af':0xF5,'call':0xCD,'callcc':0xC4,'untaken':0xCC,'rst':0xEF}[kind]
    setup=bytes.fromhex('f3afe040')+bytes([0x31,sp&255,sp>>8])+bytes.fromhex('11276b3e01b7')
    instruction=bytes([opcode])+(bytes.fromhex('0003') if kind in ('call','callcc','untaken') else b'')
    rom=bytearray(0x8000);rom[0x100:0x103]=bytes.fromhex('c35001');rom[0x28:0x2B]=bytes.fromhex('c30003')
    code=setup+instruction+bytes.fromhex('c30003');rom[0x150:0x150+len(code)]=code
    # The high DIV stack write must precede the low write by4T. With the
    # following delay, that4T determines which side of DIV's edge is sampled.
    success=bytes(60 if kind in ('call','callcc') else 56)+bytes.fromhex('f004ea11c0f003ea12c0f0ffea13c0f8007dea14c07cea15c0')
    low=(sp-2)&65535;high=(sp-1)&65535
    success+=bytes([0xFA,low&255,low>>8])+bytes.fromhex('ea16c0')+bytes([0xFA,high&255,high>>8])+bytes.fromhex('ea17c03e42ea10c018fe')
    rom[0x300:0x300+len(success)]=success
    return bytes(rom)


def reference(kind,sp):
    m=Memory(stack_write_rom(kind,sp));c=CPU(m)
    for _ in range(350):c.step()
    return m


class StackWriteTimingTests(unittest.TestCase):
    def test_original_stack_write_fixtures(self):
        cases=[(kind,0xFF05) for kind in ('push','af','call','callcc','rst','untaken')]+[('push',sp) for sp in (0,1,0xC100,0xFE01)]
        for kind,sp in cases:
            with self.subTest(kind=kind,sp=sp):
                m=reference(kind,sp);self.assertEqual(m.wram[0x10],0x42)
                final_sp=sp if kind=='untaken' else (sp-2)&65535
                self.assertEqual(m.wram[0x14:0x16],final_sp.to_bytes(2,'little'))
                if sp==0xFF05 and kind!='untaken':self.assertEqual(m.wram[0x11],1)
                if sp in (0xC100,0xFE01):self.assertEqual(m.wram[0x16:0x18],bytes([0x27,0x6B]))
        self.assertEqual(reference('reload',0xFF06).wram[0x10:0x12],bytes([0x42,0xFF]))

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_stack_write_phases_match_reference(self):
        from build_recompiled import build
        from run_compat_tests import _run_in_pty,_blastem_values
        cases=[(kind,0xFF05) for kind in ('push','af','call','callcc','rst','untaken')]+[('push',sp) for sp in (0,0xFE01)]+[('reload',0xFF06)]
        for kind,sp in cases:
            with self.subTest(kind=kind,sp=sp),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);source=root/'original.gb';source.write_bytes(stack_write_rom(kind,sp));image=build(source,root/'out',350)
                addresses=[f'FF23{x:02X}.b' for x in range(0x10,0x18)]+['FF0018.l','FF0038.l','FF0034.b','FF005C.b']
                command='frames 600\np/x '+' '.join('[$'+a.split('.')[0].lower()+'].'+a.split('.')[1] for a in addresses)+'\nquit\n'
                code,output,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(image)],command,30)
                self.assertFalse(timed,output);self.assertEqual(code,0,output);v=_blastem_values(output);m=reference(kind,sp)
                self.assertEqual([v.get(a) for a in addresses[:8]],list(m.wram[0x10:0x18]),output)
                for a in addresses[8:]:self.assertEqual(v.get(a),0,output)
