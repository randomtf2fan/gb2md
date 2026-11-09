"""Original programs exercising finite self-modifying native WRAM code."""
import json,os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


def wram_variant_rom(echo=False):
    address=0xE100 if echo else 0xC100
    code=bytearray(bytes.fromhex('f331fedf3e3eea00c13ec9ea02c1'))
    for value in (0x11,0x42,0x99):
        code.extend(bytes([0x3E,value])+bytes.fromhex('ea01c1')+bytes([0xCD,address&255,address>>8])+bytes.fromhex('ea00c0'))
    code.extend(bytes.fromhex('18fe'))
    rom=bytearray(0x8000);rom[0x100:0x103]=bytes.fromhex('c35001');rom[0x150:0x150+len(code)]=code
    return bytes(rom)


class WramVariantTests(unittest.TestCase):
    def test_reference_and_lowering_preserve_logical_echo_identity(self):
        from gb_cpu import CPU,Memory
        from trace_recompiler import compile_trace
        for echo in (False,True):
            with self.subTest(echo=echo),tempfile.TemporaryDirectory() as folder:
                rom=wram_variant_rom(echo);memory=Memory(rom);cpu=CPU(memory)
                for _ in range(150):cpu.step()
                self.assertEqual(memory.wram[0],0x99)
                root=Path(folder);source=root/'original.gb';source.write_bytes(rom)
                blocks=compile_trace(source,root/'out',150)
                pc=0xE100 if echo else 0xC100
                block=next(b for b in blocks if b['pc']==pc)
                self.assertEqual({block['bytes'],*block['observed_variants']},{'3e11','3e42','3e99'})
                text=(root/'out'/'translated_trace.s').read_text()
                self.assertIn('lea gb_wram,a0',text)
                self.assertIn(f'.dynamic_missing_000_{pc:04X}:',text)

    def test_cross_window_variant_is_rejected(self):
        from trace_recompiler import emit_native_blocks
        from lr35902_lowering import family
        with tempfile.TemporaryDirectory() as folder:
            block={'bank':0,'pc':0xDFFF,'opcode':0,'operand':0,'bytes':'00','family':family(0),'hits':1,'native_lowered':True,'observed_variants':['3e11']}
            with self.assertRaisesRegex(RuntimeError,'crosses WRAM window'):
                emit_native_blocks([block],Path(folder))

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_variants_and_unseen_variant_trap(self):
        import build_recompiled as compiler
        from trace_recompiler import emit_native_blocks
        from run_compat_tests import _run_in_pty,_blastem_values
        for echo,omit in ((False,False),(True,False),(False,True)):
            with self.subTest(echo=echo,omit=omit),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);source=root/'original.gb';source.write_bytes(wram_variant_rom(echo))
                original=compiler.compile_trace
                def discover(*args,**kwargs):
                    blocks=original(*args,**kwargs)
                    if omit:
                        for b in blocks:
                            if b['pc']==0xC100:b['observed_variants'].remove('3e99')
                        emit_native_blocks(blocks,args[1])
                    return blocks
                with patch.object(compiler,'compile_trace',side_effect=discover):
                    artifact=compiler.build(source,root/'out',150)
                commands='frames 180\np/x [$ff2300].b [$ff0018].l [$ff0038].l [$ff0002].w\nquit\n'
                code,output,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(artifact)],commands,20)
                self.assertFalse(timed,output);self.assertEqual(code,0,output);values=_blastem_values(output)
                if omit:
                    self.assertEqual(values['FF2300.b'],0x42,output)
                    self.assertEqual(values['FF0018.l'],0xBADB10C0,output)
                    self.assertEqual(values['FF0038.l'],1,output)
                    self.assertEqual(values['FF0002.w'],0xC100,output)
                else:
                    self.assertEqual(values['FF2300.b'],0x99,output)
                    self.assertEqual(values['FF0018.l'],0,output)
