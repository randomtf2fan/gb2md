"""Original LCD clock/comparator diagnostics; no external ROM code/data."""
import copy
import os
import pickle
from pathlib import Path
import tempfile
import unittest
from gb_cpu import CPU,Memory


def diagnostic_rom():
    rom=bytearray(0x8000);rom[0x100:0x103]=bytes.fromhex('c35001')
    code=bytearray.fromhex('f331fedfafe007e00feaffff3e40e041afe040')
    code+=bytes.fromhex('f041ea00c03e01e045f041ea01c00100040b78b120fbf044ea02c0')
    code+=bytes.fromhex('3e80e040f041ea03c0afe040e045e00f3e80e040f041ea04c0')
    code+=bytes.fromhex('f00fe602ea05c0afe0402100c106a03e5a223c0520fb')
    helper=bytes.fromhex('3ec1e0463e503d20fdc9')
    code+=bytes.fromhex('2180ff')
    for value in helper:code+=bytes((0x3e,value,0x22))
    code+=bytes.fromhex('cd80fff044ea06c0f004ea07c03ea5ea08c018fe')
    rom[0x150:0x150+len(code)]=code
    return bytes(rom)


def interrupt_diagnostic(trigger):
    rom=bytearray(0x8000);rom[0x100:0x103]=bytes.fromhex('c35001')
    rom[0x48:0x4a]=bytes.fromhex('3cd9')  # Increment A before the following DI.
    code=bytearray.fromhex('f331fedfafe040e041e00feaffff')
    if trigger=='lcdc':
        code+=bytes.fromhex('3e01e0453e80e040afe040e0453e40e041')
        value=0x80;register=0x40
    elif trigger=='lyc':
        code+=bytes.fromhex('3e01e0453e80e0403e40e041')
        value=0;register=0x45
    elif trigger=='stat':
        code+=bytes.fromhex('afe0453e80e040')
        value=0x40;register=0x41
    else:raise ValueError(trigger)
    code+=bytes.fromhex('afe00f3e02eafffffb00')
    code+=bytes((0x3e,value,0xe0,register,0xf3,0xea,0,0xc0,0x3e,0xa5,0xea,1,0xc0,0x18,0xfe))
    rom[0x150:0x150+len(code)]=code
    return bytes(rom),value+1


class PpuClockTests(unittest.TestCase):
    def test_frozen_comparison_and_restart_edge_all_four_transitions(self):
        for before in (False,True):
            for after in (False,True):
                memory=Memory(bytes(0x8000));memory.tick(456*144)
                memory.write(0xff45,144 if before else 143);memory.write(0xff41,0x40)
                self.assertEqual(memory.stat_line,before)
                memory.write(0xff40,0);memory.write(0xff0f,0)
                memory.write(0xff45,0 if after else 1);memory.tick(70224+36)
                self.assertEqual(memory.read(0xff44),0)
                self.assertEqual(memory.read(0xff41),0xc4 if before else 0xc0)
                self.assertEqual(memory.stat_line,before);self.assertEqual(memory.io[15],0)
                memory.write(0xff40,0x80)
                self.assertEqual(memory.read(0xff41),0xc4 if after else 0xc0)
                self.assertEqual(bool(memory.io[15]&2),after and not before)

    def test_ppu_stops_independently_of_cpu_timer_and_dma(self):
        memory=Memory(bytes(0x8000));memory.tick(2320);memory.write(0xff40,0)
        memory.wram[0x100:0x1a0]=bytes(range(160));memory.write(0xff46,0xc1)
        memory.write(0xff06,0xa7);memory.write(0xff05,0xff);memory.write(0xff07,5)
        before=(memory.cycles,memory.div_counter)
        memory.tick(1024)
        self.assertEqual(memory.ppu_cycles,0);self.assertEqual(memory.read(0xff44),0)
        self.assertEqual(memory.cycles,before[0]+1024)
        self.assertEqual(memory.div_counter,(before[1]+1024)&65535)
        self.assertTrue(memory.io[15]&4);self.assertEqual(memory.oam,bytes(range(160)))
        self.assertFalse(memory.dma_active)

    def test_restart_phase_vblank_and_readonly_ly(self):
        memory=Memory(bytes(0x8000));memory.tick(1012);memory.write(0xff40,0)
        memory.tick(511);memory.write(0xff0f,0);memory.write(0xff40,0x80)
        self.assertEqual(memory.read(0xff41)&3,0)
        memory.tick(80);self.assertEqual(memory.read(0xff41)&3,3)
        phase=memory.ppu_cycles;memory.write(0xff44,99)
        self.assertEqual(memory.ppu_cycles,phase);self.assertEqual(memory.read(0xff44),0)
        memory.tick(456-80);self.assertFalse(memory.ppu_starting)
        self.assertEqual((memory.read(0xff44),memory.read(0xff41)&3),(1,2))
        memory.tick(456*143-4);self.assertFalse(memory.io[15]&1)
        memory.tick(4);self.assertTrue(memory.io[15]&1)

    def test_bulk_and_small_ticks_and_same_enable_preserve_phase(self):
        a=Memory(bytes(0x8000));a.write(0xff40,0);a.tick(1032);a.write(0xff40,0x80)
        b=copy.deepcopy(a);a.tick(70224*2+64)
        for _ in range((70224*2+64)//4):b.tick(4)
        self.assertEqual((a.io,a.ppu_cycles,a.ppu_starting),(b.io,b.ppu_cycles,b.ppu_starting))
        phase=a.ppu_cycles;a.write(0xff40,0x91);self.assertEqual(a.ppu_cycles,phase)

    def test_snapshot_hash_and_legacy_phase_migration(self):
        from trace_recompiler import exploration_state_key
        cpu=CPU(Memory(bytes(0x8000)));cpu.m.tick(104)
        before=exploration_state_key(cpu);changed=copy.deepcopy(cpu);changed.m.ppu_cycles+=4
        self.assertNotEqual(before,exploration_state_key(changed))
        changed=copy.deepcopy(cpu);changed.m.ppu_starting=True
        self.assertNotEqual(before,exploration_state_key(changed))
        clone=pickle.loads(pickle.dumps(changed));self.assertEqual(exploration_state_key(clone),exploration_state_key(changed))
        legacy=copy.deepcopy(cpu.m);del legacy.ppu_cycles;del legacy.ppu_starting
        clone=pickle.loads(pickle.dumps(legacy));self.assertEqual(clone.ppu_cycles,104)
        self.assertFalse(clone.ppu_starting)

    def test_original_program_reference(self):
        memory=Memory(diagnostic_rom());cpu=CPU(memory)
        for _ in range(20000):
            cpu.step()
            if memory.wram[8]==0xa5:break
        self.assertEqual(memory.wram[:7],bytes((0xc4,0xc4,0,0xc0,0xc4,2,0)))
        self.assertEqual(memory.wram[8],0xa5);self.assertNotEqual(memory.wram[7],0)
        self.assertEqual(memory.oam,bytes((0x5a+i)&255 for i in range(160)))

    def test_ppu_control_irq_preempts_immediately_following_di(self):
        for trigger in ('lcdc','lyc','stat'):
            rom,expected=interrupt_diagnostic(trigger);memory=Memory(rom);cpu=CPU(memory)
            for _ in range(1000):cpu.step()
            self.assertEqual(memory.wram[:2],bytes((expected,0xa5)),trigger)
            self.assertEqual(cpu.sp,0xdffe)

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_ppu_control_irq_preempts_di(self):
        from build_recompiled import build
        from run_compat_tests import _run_in_pty,_blastem_values
        for trigger in ('lcdc','lyc','stat'):
            with self.subTest(trigger=trigger),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);rom,expected=interrupt_diagnostic(trigger)
                source=root/'original.gb';source.write_bytes(rom);image=build(source,root/'out',1000)
                commands='frames 180\np/x [$ff2300].w [$ff0010].w [$ff0018].l [$ff0038].l\nquit\n'
                rc,out,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(image)],commands,20)
                self.assertFalse(timed,out);self.assertEqual(rc,0,out);values=_blastem_values(out)
                self.assertEqual(values.get('FF2300.w'),expected*256+0xa5,out)
                self.assertEqual(values.get('FF0010.w'),0xdffe,out)
                self.assertEqual(values.get('FF0018.l'),0,out);self.assertEqual(values.get('FF0038.l'),0,out)

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_original_program(self):
        from build_recompiled import build
        from run_compat_tests import _run_in_pty,_blastem_values
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'original.gb';source.write_bytes(diagnostic_rom())
            image=build(source,root/'out',20000)
            commands='frames 600\np/x [$ff2300].l [$ff2304].l [$ff2308].b [$ff0144].b [$ff0018].l [$ff0038].l\n'
            commands+=''.join('p/x '+' '.join(f'[$ff{0x200+i:04x}].l' for i in range(start,start+40,4))+'\n' for start in range(0,160,40))+'quit\n'
            rc,out,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(image)],commands,45)
            self.assertFalse(timed,out);self.assertEqual(rc,0,out);values=_blastem_values(out)
            self.assertEqual(values.get('FF2300.l'),0xc4c400c0,out)
            self.assertEqual(values.get('FF2304.l')>>8,0xc40200,out)
            self.assertNotEqual(values.get('FF2304.l')&255,0,out)
            self.assertEqual(values.get('FF2308.b'),0xa5,out);self.assertEqual(values.get('FF0144.b'),0,out)
            self.assertEqual(values.get('FF0018.l'),0,out);self.assertEqual(values.get('FF0038.l'),0,out)
            for i in range(0,160,4):
                self.assertEqual(values.get(f'FF{0x200+i:04X}.l'),int.from_bytes(bytes((0x5a+j)&255 for j in range(i,i+4)),'big'),out)
