"""Original native code-variant fixtures spanning logical memory windows."""
import os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from gb_cpu import CPU,Memory


def cross_window_rom(oam=False):
    address=0xFDFF if oam else 0xDFFF
    def store(a):return bytes([0xEA,a&255,a>>8])
    code=bytearray(bytes.fromhex('f3afe04031fedf'))
    code+=bytes.fromhex('3e3e')+store(address)+bytes.fromhex('3ec9')+store(address+2)
    for value in (0x11,0x42,0x99):
        code+=bytes([0x3E,value])+store(address+1)+bytes([0xCD,address&255,address>>8])+store(0xC010)
    code+=bytes.fromhex('18fe')
    rom=bytearray(0x8000);rom[0x100:0x103]=bytes.fromhex('c35001');rom[0x150:0x150+len(code)]=code
    return bytes(rom)


class CrossWindowFetchTests(unittest.TestCase):
    def test_uniform_variants_use_timed_bus_reads_and_remaining_cycles(self):
        from trace_recompiler import compile_trace
        for oam in (False,True):
            with self.subTest(oam=oam),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);source=root/'original.gb';source.write_bytes(cross_window_rom(oam))
                memory=Memory(source.read_bytes());cpu=CPU(memory)
                for _ in range(200):cpu.step()
                self.assertEqual(memory.wram[0x10],0x99)
                blocks=compile_trace(source,root/'out',200)
                pc=0xFDFF if oam else 0xDFFF
                block=next(b for b in blocks if b['pc']==pc)
                self.assertEqual({block['bytes'],*block['observed_variants']},{'3e11','3e42','3e99'})
                text=(root/'out'/'translated_trace.s').read_text().split(f'L_gb_B000_{pc:04X}:',1)[1]
                self.assertIn('jsr gb_fetch_read8',text)
                self.assertIn('lea gb_fetch_bytes,a0',text)
                self.assertIn('move.b #0,gb_step_cycles',text)
        from trace_recompiler import emit_native_blocks
        with tempfile.TemporaryDirectory() as folder:
            block={'bank':0,'pc':0xFDFE,'opcode':0xCC,'operand':0x1A00,'bytes':'cc001a',
                   'family':'CALL_CC','hits':1,'native_lowered':True,'observed_variants':['cc001b']}
            emit_native_blocks([block],Path(folder))
            text=(Path(folder)/'translated_trace.s').read_text()
            self.assertIn('move.b #0,gb_step_cycles',text)  # untaken: fetch only
            self.assertIn('move.b #12,gb_step_cycles',text) # taken: remaining push
            self.assertNotIn('move.b #24,gb_step_cycles',text)

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_uniform_variants_and_unknown_variant_trap(self):
        import build_recompiled as compiler
        from trace_recompiler import emit_native_blocks
        from run_compat_tests import _run_in_pty,_blastem_values
        for oam,omit in ((False,False),(True,False),(True,True)):
            with self.subTest(oam=oam,omit=omit),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);source=root/'original.gb';source.write_bytes(cross_window_rom(oam))
                original=compiler.compile_trace
                def discover(*args,**kwargs):
                    blocks=original(*args,**kwargs)
                    if omit:
                        next(b for b in blocks if b['pc']==0xFDFF)['observed_variants'].remove('3e99')
                        emit_native_blocks(blocks,args[1])
                    return blocks
                with patch.object(compiler,'compile_trace',side_effect=discover):
                    image=compiler.build(source,root/'out',200)
                commands='frames 600\np/x [$ff2310].b [$ff0018].l [$ff0038].l [$ff0002].w\nquit\n'
                code,output,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(image)],commands,30)
                self.assertFalse(timed,output);self.assertEqual(code,0,output);v=_blastem_values(output)
                self.assertEqual(v['FF2310.b'],0x42 if omit else 0x99,output)
                self.assertEqual(v['FF0018.l'],0xBADB10C0 if omit else 0,output)
                self.assertEqual(v['FF0038.l'],1 if omit else 0,output)
                if omit:self.assertEqual(v['FF0002.w'],0xFDFF,output)
