"""Differential checks for native skipping of pure LY equality loops."""
import json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from gb_cpu import CPU,Memory


def cartridge(target,padding=0,pre_target=None):
    rom=bytearray(0x8000);rom[0x100:0x103]=bytes.fromhex('c35001')
    code=bytearray.fromhex('f331fedfafe040e007e041e00feaffff3e80e040')
    if pre_target is not None:
        code+=bytes((0xf0,0x44,0xfe,pre_target,0x20,0xfa,0xaf,0xe0,0x0f))
    code+=bytes(padding)
    code+=bytes((0xf0,0x44,0xfe,target,0x20,0xfa))
    code+=bytes.fromhex('f004ea00c0f044ea01c0f5c179ea02c078ea03c0f00fe603ea05c03ea5')
    marker=0x150+len(code);code+=bytes.fromhex('ea04c018fe')
    rom[0x150:0x150+len(code)]=code
    return bytes(rom),marker


CASES=((1,0,None),(2,1,None),(143,7,None),(144,19,None),(0,3,1),(146,5,145))


class LyPollCadenceTests(unittest.TestCase):
    def test_reference_samples_full_loops_and_does_not_repeat_vblank(self):
        for target,padding,pre_target in CASES:
            memory=Memory(cartridge(target,padding,pre_target)[0]);cpu=CPU(memory)
            for _ in range(20000):
                cpu.step()
                if memory.wram[4]==0xa5:break
            self.assertEqual(memory.wram[4],0xa5)
            self.assertEqual(memory.wram[1],target)
            self.assertEqual(memory.wram[2],0xc0)
            if pre_target==145:self.assertEqual(memory.wram[5],0)

    def test_discovery_reports_the_exact_sampling_contract(self):
        from trace_recompiler import compile_trace
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'original.gb';source.write_bytes(cartridge(143,7)[0])
            blocks=compile_trace(source,root/'out',20000)
            polls=[b for b in blocks if 'idle_ly_target' in b]
            self.assertEqual(len(polls),1)
            self.assertEqual((polls[0]['idle_ly_period'],polls[0]['idle_ly_read_offset']),(32,12))

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_optimized_and_plain_polling_match_reference_cycles(self):
        import build_recompiled as compiler
        import trace_recompiler as trace
        from run_compat_tests import _run_in_pty,_blastem_values
        capture=['movem.l d0-d2,-(sp)','move.l gb_cycle_counter,d0','moveq #0,d1','move.w d7,d1','add.l d1,d0',
                 'moveq #0,d1','move.w gb_batch_bias,d1','sub.l d1,d0','moveq #0,d1','move.b gb_step_cycles,d1','add.l d1,d0',
                 'moveq #0,d1','move.w gb_cycle_batch,d1','add.l d1,d0','move.l d0,$FF2310','movem.l (sp)+,d0-d2']
        for target,padding,pre_target in CASES:
            rom,marker=cartridge(target,padding,pre_target);memory=Memory(rom);cpu=CPU(memory)
            for _ in range(20000):
                cpu.step()
                if memory.wram[4]==0xa5:break
            for optimized in (True,False):
                with self.subTest(target=target,padding=padding,optimized=optimized),tempfile.TemporaryDirectory() as folder:
                    root=Path(folder);source=root/'original.gb';source.write_bytes(rom);original=compiler.compile_trace
                    def discover(*args,**kwargs):
                        blocks=original(*args,**kwargs)
                        if not optimized:
                            blocks=[dict(b) for b in blocks]
                            for b in blocks:
                                if 'idle_ly_target' in b:b.pop('idle_wait',None)
                            trace.emit_native_blocks(blocks,args[1])
                        path=args[1]/'translated_trace.s';text=path.read_text();label=f'L_gb_B000_{marker:04X}:\n'
                        before,sep,after=text.partition(label);assert sep
                        body,sep2,tail=after.partition('\nL_gb_');assert '\tjsr gb_write8' in body
                        body=body.replace('\tjsr gb_write8','\tjsr gb_write8\n\t'+'\n\t'.join(capture),1)
                        path.write_text(before+sep+body+sep2+tail)
                        return blocks
                    with patch.object(compiler,'compile_trace',side_effect=discover):image=compiler.build(source,root/'out',20000)
                    commands='frames 600\np/x [$ff2300].l [$ff2304].w [$ff2310].l [$ff0010].w [$ff0018].l [$ff0038].l\nquit\n'
                    rc,out,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(image)],commands,45)
                    self.assertFalse(timed,out);self.assertEqual(rc,0,out);values=_blastem_values(out)
                    self.assertEqual(values.get('FF2300.l'),int.from_bytes(memory.wram[:4],'big'),out)
                    self.assertEqual(values.get('FF2304.w'),int.from_bytes(memory.wram[4:6],'big'),out)
                    self.assertEqual(values.get('FF2310.l'),memory.cycles,out)
                    self.assertEqual(values.get('FF0010.w'),cpu.sp,out)
                    self.assertEqual(values.get('FF0018.l'),0,out);self.assertEqual(values.get('FF0038.l'),0,out)

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_irq_on_entry_never_skips_past_the_handler(self):
        import build_recompiled as compiler
        from run_compat_tests import _run_in_pty,_blastem_values
        for ime,delay in ((1,0),(0,1)):
            with self.subTest(ime=ime,delay=delay),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);rom=bytearray(0x8000);rom[0x100:0x102]=bytes.fromhex('18fe')
                source=root/'original.gb';source.write_bytes(rom);original=compiler.compile_trace
                def discover(*args,**kwargs):
                    blocks=original(*args,**kwargs);path=args[1]/'translated_trace.s';text=path.read_text()
                    import re
                    text,n=re.subn(r'(gb_compiled_entry:\n)\tbra.w L_gb_[^\n]+',r'\1\tbra.w idle_irq_probe',text,count=1);assert n==1
                    program=['idle_irq_probe:',f'\tmove.b #{ime},gb_ime',f'\tmove.b #{delay},gb_ei_delay','\tmove.b #1,gb_ie','\tmove.b #1,gb_io+$0F',
                             '\tmove.w #$1234,gb_pc','\tmove.w #144,d0','\tjsr gb_idle_ly','.finished:','\tbra.s .finished']
                    path.write_text(text+'\n'+'\n'.join(program)+'\n');return blocks
                with patch.object(compiler,'compile_trace',side_effect=discover):image=compiler.build(source,root/'out',2)
                rc,out,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(image)],'frames 180\np/x [$ff0020].l [$ff0002].w [$ff0010].w [$ff0028].w [$ff0018].l\nquit\n',20)
                self.assertFalse(timed,out);self.assertEqual(rc,0,out);values=_blastem_values(out)
                self.assertEqual(values.get('FF0020.l'),20,out)
                self.assertEqual(values.get('FF0002.w'),0x40,out);self.assertEqual(values.get('FF0010.w'),0xfffc,out)
                self.assertEqual(values.get('FF0028.w'),20,out);self.assertEqual(values.get('FF0018.l'),0,out)
