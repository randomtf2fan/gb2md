"""Original timer-edge programs verify IRQ arbitration before the next opcode."""
import json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from gb_cpu import CPU,Memory

PREFIX=bytes.fromhex('f331fedfafe040e00fe007e0063e04eafffffb00afe0043effe0053e05e007')


def irq_deadline_rom(nops,enabled=True):
    rom=bytearray(0x8000);rom[0x100:0x103]=bytes.fromhex('c35001')
    handler=bytes.fromhex('f8007eea14c0237eea15c03e42ea10c0d9');rom[0x50:0x50+len(handler)]=handler
    prefix=PREFIX if enabled else PREFIX.replace(bytes.fromhex('3e04eaffff'),bytes.fromhex('3e00eaffff'))
    code=prefix+bytes(nops)+bytes.fromhex('f3afe0073e99ea11c0f00fe61fea12c0f004ea13c018fe')
    rom[0x150:0x150+len(code)]=code
    return bytes(rom)


def reference(nops,enabled=True):
    m=Memory(irq_deadline_rom(nops,enabled));cpu=CPU(m)
    for _ in range(500):cpu.step()
    return m


class IrqBatchDeadlineTests(unittest.TestCase):
    def test_reference_interrupt_fires_at_boundary_before_di_or_final_nop(self):
        for nops in range(7):
            for enabled in (False,True):
                with self.subTest(nops=nops,enabled=enabled):
                    m=reference(nops,enabled)
                    fired=enabled and nops>=3
                    self.assertEqual(m.wram[0x10],0x42 if fired else 0)
                    self.assertEqual(m.wram[0x11],0x99)
                    self.assertEqual(m.wram[0x14:0x16],(0x150+len(PREFIX)+3 if fired else 0).to_bytes(2,'little'))

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_deadline_return_pc_and_div_match_reference(self):
        import build_recompiled as compiler
        from trace_recompiler import emit_native_blocks
        from run_compat_tests import _run_in_pty,_blastem_values
        cases=[(n,True,'default') for n in (0,2,3,4,6)]+[(4,False,'default'),(4,True,'compact'),(4,True,'unoptimized')]
        for nops,enabled,mode in cases:
            with self.subTest(nops=nops,enabled=enabled,mode=mode),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);source=root/'original.gb';source.write_bytes(irq_deadline_rom(nops,enabled))
                original=compiler.compile_trace
                def discover(*args,**kwargs):
                    blocks=original(*args,**kwargs)
                    if mode=='compact':emit_native_blocks(blocks,args[1],max_hot_chains=0)
                    return blocks
                with patch.object(compiler,'compile_trace',side_effect=discover):
                    image=compiler.build(source,root/'out',500,optimize_pure_chains=mode!='unoptimized')
                if mode=='compact':self.assertEqual(json.loads((root/'out/native-codegen-report.json').read_text())['hot_chain_targets'],0)
                addresses=[f'FF23{x:02X}.b' for x in range(0x10,0x16)]+['FF0018.l','FF0038.l','FF005E.w']
                commands='frames 600\np/x '+' '.join('[$'+a.split('.')[0].lower()+'].'+a.split('.')[1] for a in addresses)+'\nquit\n'
                code,out,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(image)],commands,30)
                self.assertFalse(timed,out);self.assertEqual(code,0,out);v=_blastem_values(out);m=reference(nops,enabled)
                self.assertEqual([v.get(a) for a in addresses[:6]],list(m.wram[0x10:0x16]),out)
                for a in addresses[6:]:self.assertEqual(v.get(a),0,out)
