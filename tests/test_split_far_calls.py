"""Original cartridges for branch-separated B/HL trampoline arguments."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from gb_cpu import CPU, Memory
from trace_recompiler import constant_far_call_targets, compile_trace


def split_far_rom(kind='jr', mapper=0x11, target_bank=2):
    rom=bytearray(0x10000);rom[0x147:0x14A]=bytes((mapper,1,0))
    program=bytes.fromhex('3e01e090cd2001fa0046ea01c018fe')
    rom[0x100:0x100+len(program)]=program
    helper=bytes.fromhex('f090f578e090ea0020010e03c5e9c178e090ea0020c9')
    rom[0x300:0x316]=helper
    if kind=='jr':
        code=bytes.fromhex('2100451803d3dbdd')+bytes((0x06,target_bank))+bytes.fromhex('c30003')
    elif kind=='reverse':
        code=bytes((0x06,target_bank))+bytes.fromhex('1803d3dbdd210045c30003')
    elif kind=='jp':
        code=bytes.fromhex('210045c33001')
        rom[0x130:0x135]=bytes((0x06,target_bank))+bytes.fromhex('c30003')
    elif kind=='nop':
        code=bytes.fromhex('21004500')+bytes((0x06,target_bank))+bytes.fromhex('00cd0003c9')
    else:raise ValueError(kind)
    rom[0x120:0x120+len(code)]=code
    offset=target_bank*0x4000+0x500
    rom[offset:offset+6]=bytes.fromhex('3e42ea00c0c9')
    rom[0x4600]=0x99;rom[0x8600]=0x55
    return bytes(rom)


class SplitFarCallTests(unittest.TestCase):
    def test_both_orders_and_unconditional_paths_resolve(self):
        for kind in ('jr','reverse','jp','nop'):
            with self.subTest(kind=kind):
                diagnostic={}
                self.assertEqual(constant_far_call_targets(split_far_rom(kind),0,0x120,diagnostic),[(2,0x4500)])
                self.assertEqual(diagnostic['return_target'],(0,0x30E))

    def test_unknown_effects_conditions_cycles_and_budgets_fail_closed(self):
        for code in ('21004528030602c30003','210045240602c30003',
                     '210045ea00200602c30003','210045cd10030602c30003',
                     '21004518fe','210045c30002',
                     '210045'+'00'*16+'0602c30003'):
            with self.subTest(code=code):
                rom=bytearray(split_far_rom());rom[0x120:0x120+len(bytes.fromhex(code))]=bytes.fromhex(code)
                self.assertEqual(constant_far_call_targets(rom,0,0x120),[])
        rom=bytearray(split_far_rom());rom[0x305]=0x91
        self.assertEqual(constant_far_call_targets(rom,0,0x120),[])
        rom=bytearray(split_far_rom());rom[0x3FFC:0x4001]=bytes.fromhex('2100451800')
        self.assertEqual(constant_far_call_targets(rom,0,0x3FFC),[])

    def test_upper_window_uses_physical_caller_bank(self):
        rom=bytearray(split_far_rom());rom[0xC120:0xC12D]=rom[0x120:0x12D]
        self.assertEqual(constant_far_call_targets(rom,3,0x4120),[(2,0x4500)])
        self.assertEqual(constant_far_call_targets(rom,1,0x4120),[])

    def test_closure_discovers_unexecuted_target_and_preserves_original_flow(self):
        for kind in ('jr','reverse','jp','nop'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);rom=split_far_rom(kind);source=root/'original.gb';source.write_bytes(rom)
                m=Memory(rom);c=CPU(m)
                for _ in range(120):c.step()
                self.assertEqual(m.wram[:2],bytes((0x42,0x99)))
                self.assertEqual((m.rom_bank,c.sp),(1,0xFFFE))
                blocks=compile_trace(source,root/'out',2)
                callback=next(b for b in blocks if (b['bank'],b['pc'])==(2,0x4500))
                self.assertEqual(callback['hits'],0)
                self.assertEqual(json.loads((root/'out/trace-profile.json').read_text())['constant_far_call_targets'],1)

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_split_setup_calls_and_restores_bank_and_stack(self):
        from build_recompiled import build
        from run_compat_tests import _run_in_pty, _blastem_values
        for kind,mapper,bank in (('jr',0x11,2),('jp',0x11,2),('reverse',0x19,0),('nop',0,1)):
            with self.subTest(kind=kind,mapper=mapper),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);source=root/'original.gb';source.write_bytes(split_far_rom(kind,mapper,bank))
                image=build(source,root/'out',2)
                code,out,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(image)],
                    'frames 120\np/x [$ff2300].b [$ff2301].b [$ff001e].w [$ff0010].w [$ff0018].l [$ff0038].l\nquit\n',20)
                self.assertFalse(timed,out);self.assertEqual(code,0,out);values=_blastem_values(out)
                self.assertEqual([values.get(a) for a in ('FF2300.b','FF2301.b','FF001E.w','FF0010.w','FF0018.l','FF0038.l')],
                                 [0x42,0x99,1,0xFFFE,0,0],out)
