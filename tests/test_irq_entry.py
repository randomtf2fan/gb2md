"""Original interrupt stack-entry and cancellation fixtures (no suite code)."""
import os,tempfile,unittest
from pathlib import Path
from gb_cpu import CPU,Memory


def irq_entry_rom(case):
    rom=bytearray(0x8000)
    start=0x400 if case=='priority' else 0x800
    sp=1 if case=='low_ie' else (0xC100 if case=='normal' else 0)
    request=5 if case=='priority' else 4
    rom[0x100:0x103]=bytes([0xC3,start&255,start>>8])
    # Handlers always leave via the original success/failure recorder.
    rom[0:3]=bytes.fromhex('c30003' if case=='cancel' else 'c38003')
    rom[0x40:0x43]=bytes.fromhex('c38003')
    rom[0x50:0x53]=bytes.fromhex('c30003' if case!='cancel' else 'c38003')
    rom[0x60:0x63]=bytes.fromhex('c38003')
    setup=bytes.fromhex('f3afe040e00f')+bytes([0x3E,request])+bytes.fromhex('eafffffb00')+bytes([0x31,sp&255,sp>>8])
    rom[start:start+len(setup)]=setup
    # Trigger returns to xx40: high byte determines the IE upper-push
    # scenarios; low40 disables the timer if written later through SP=1.
    rom[start+0x3E:start+0x40]=bytes.fromhex('e00f')
    rom[start+0x40:start+0x43]=bytes.fromhex('c38003')
    success=bytes.fromhex('31fedff00fe61fea01c0f0ffea02c03e10e0ffe00f003e42ea00c018fe')
    failure=bytes.fromhex('31fedf3e99ea00c018fe')
    rom[0x300:0x300+len(success)]=success;rom[0x380:0x380+len(failure)]=failure
    return bytes(rom)


class IrqEntryTests(unittest.TestCase):
    def test_reference_selection_after_high_push_and_twenty_cycles(self):
        cases=((0x3456,0xC100,4,0x50,0), (0x0876,0,4,0,4),
               (0x0840,1,4,0x50,0), (0x0412,0,5,0x50,1))
        for pc,sp,pending,vector,flags in cases:
            with self.subTest(pc=pc,sp=sp,pending=pending):
                class Bus(Memory):
                    def write(self,address,value,bus_phase=0):
                        self.events.append((address,value&255,self.cycles))
                        super().write(address,value,bus_phase)
                m=Bus(bytes(0x8000));m.events=[];m.ie=pending;m.io[15]=pending
                c=CPU(m);c.pc=pc;c.sp=sp;c.ime=True;c.step()
                self.assertEqual((c.pc,c.sp,c.ime,m.cycles),(vector,(sp-2)&65535,False,20))
                self.assertEqual(m.io[15]&31,flags)
                self.assertEqual(m.events,[((sp-1)&65535,pc>>8,12),((sp-2)&65535,pc&255,16)])
                self.assertIsNone(c.last_instruction)

    def test_cancellation_consumes_ime_and_leaves_request_pending(self):
        m=Memory(bytes(0x8000));m.ie=4;m.io[15]=4;c=CPU(m)
        c.pc=0x0876;c.sp=0;c.ime=True;c.step()
        m.ie=16;m.io[15]=16;c.step()
        self.assertEqual((c.pc,c.ime),(1,False))
        self.assertEqual(m.io[15]&31,16)

    def test_original_fixtures_match_reference(self):
        for case in ('normal','cancel','low_ie','priority'):
            with self.subTest(case=case):
                m=Memory(irq_entry_rom(case));c=CPU(m)
                for _ in range(1000):c.step()
                self.assertEqual(m.wram[0],0x42)
                self.assertEqual(m.wram[1],{'normal':0,'cancel':4,'low_ie':0,'priority':1}[case])
                self.assertEqual(m.wram[2],{'normal':4,'cancel':8,'low_ie':0x40,'priority':4}[case])
                self.assertFalse(c.ime)

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_entry_order_and_cancellation(self):
        from build_recompiled import build
        from run_compat_tests import _run_in_pty,_blastem_values
        for case in ('normal','cancel','low_ie','priority'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);source=root/'original.gb';source.write_bytes(irq_entry_rom(case))
                image=build(source,root/'out',1000)
                commands='frames 600\np/x [$ff2300].b [$ff2301].b [$ff2302].b [$ff0012].b [$ff0058].b [$ff0034].b [$ff0018].l [$ff0038].l\nquit\n'
                code,output,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(image)],commands,30)
                self.assertFalse(timed,output);self.assertEqual(code,0,output);v=_blastem_values(output)
                m=Memory(irq_entry_rom(case));c=CPU(m)
                for _ in range(1000):c.step()
                self.assertEqual([v.get(f'FF230{i}.b') for i in range(3)],list(m.wram[:3]),output)
                for address in ('FF0012.b','FF0058.b','FF0034.b','FF0018.l','FF0038.l'):
                    self.assertEqual(v.get(address),0,output)
