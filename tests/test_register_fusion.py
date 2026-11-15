"""Bounded pure-register runs must preserve entries, flags and IRQ deadlines."""
import json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from trace_recompiler import compile_trace,emit_native_blocks


class RegisterFusionTests(unittest.TestCase):
    def trace(self,code):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        root=Path(folder.name);rom=bytearray(0x8000)
        rom[0x100:0x100+len(code)]=code
        source=root/'original.gb';source.write_bytes(rom)
        blocks=compile_trace(source,root/'out',500)
        return root,blocks

    def emit(self,root,blocks,**options):
        emit_native_blocks(blocks,root/'out',**options)
        return ((root/'out/translated_trace.s').read_text(),
                json.loads((root/'out/native-codegen-report.json').read_text()))

    def test_guard_deadline_and_all_original_entries_retained(self):
        root,blocks=self.trace(bytes.fromhex('040d78a9040d78a918f6'))
        text,report=self.emit(root,blocks)
        self.assertGreater(report['fused_register_regions'],0)
        self.assertLessEqual(report['fused_register_estimated_bytes'],32768)
        for run in report['fused_register_runs']:
            stem=f"B{run['bank']:03X}_{run['pc']:04X}"
            entry=text.split(f'L_gb_{stem}:',1)[1].split(f'.fused_slow_{stem}:',1)[0]
            self.assertIn('tst.b gb_force_tick',entry)
            self.assertIn('tst.b gb_ei_delay',entry)
            self.assertIn(f"cmpi.w #{200-run['cycles']},d7",entry)
            self.assertIn('bhs.s',entry) # equality must fall back and tick
            self.assertGreaterEqual(len(run['instruction_pcs']),3)
            self.assertLessEqual(len(run['instruction_pcs']),8)
        for block in blocks:
            self.assertIn(f"L_gb_B{block['bank']:03X}_{block['pc']:04X}:",text)

    def test_memory_control_dynamic_and_bank_edges_are_not_fused(self):
        root,blocks=self.trace(bytes.fromhex('f3fb00040d78ea00c0040d78cb4618fe'))
        text,report=self.emit(root,blocks)
        by_pc={block['pc']:block for block in blocks}
        for run in report['fused_register_runs']:
            for pc in run['instruction_pcs']:
                self.assertNotIn(by_pc[pc]['opcode'],(0xF3,0xFB,0xEA,0xCB))
        # A mutable variant cannot be assumed immutable just because its
        # currently selected opcode happens to use registers only.
        mutable=[{**block,'pc':block['pc']+0xBF00,'observed_variants':['00']} for block in blocks]
        _,report=self.emit(root,mutable)
        self.assertEqual(report['fused_register_regions'],0)
        # Three bytes immediately below a cartridge-window boundary do not
        # justify executing a statically observed upper-bank successor.
        root,blocks=self.trace(bytes.fromhex('0000040d78a918fe'))
        shifted=[{**b,'pc':b['pc']+0x3EFD} for b in blocks]
        _,report=self.emit(root,shifted)
        for run in report['fused_register_runs']:
            windows={pc//0x4000 for pc in (*run['instruction_pcs'],run['target_pc'])}
            self.assertEqual(len(windows),1)

    def test_limits_and_existing_disable_switch(self):
        root,blocks=self.trace(bytes.fromhex('040d78a9')*8+bytes.fromhex('18fe'))
        for options in ({'max_fused_regions':0},{'optimize_pure_chains':False},{'max_hot_chains':0}):
            _,report=self.emit(root,blocks,**options)
            self.assertEqual(report['fused_register_regions'],0)
        _,report=self.emit(root,blocks,max_fused_regions=1)
        self.assertEqual(report['fused_register_regions'],1)
        with self.assertRaises(ValueError):self.emit(root,blocks,max_fused_regions=-1)

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_registers_flags_clock_and_irq_return_match_unfused(self):
        import build_recompiled as compiler
        from run_compat_tests import _run_in_pty,_blastem_values
        from test_chain_cycles import cycle_fixture
        from test_irq_batch_deadline import irq_deadline_rom
        fixtures=[('registers',cycle_fixture())]+[(f'irq-{n}',irq_deadline_rom(n)) for n in (2,3,4,6)]
        for name,rom in fixtures:
            observations=[]
            for enabled in (False,True):
                with self.subTest(name=name,enabled=enabled),tempfile.TemporaryDirectory() as folder:
                    root=Path(folder);source=root/'original.gb';source.write_bytes(rom)
                    original=compiler.compile_trace
                    def discover(*args,**kwargs):
                        blocks=original(*args,**kwargs)
                        emit_native_blocks(blocks,args[1],max_fused_regions=128 if enabled else 0)
                        return blocks
                    with patch.object(compiler,'compile_trace',side_effect=discover):
                        image=compiler.build(source,root/'out',3000)
                    addresses=[f'FF23{i:02X}.b' for i in range(0x16)]+['FF0018.l','FF0038.l']
                    commands='frames 600\np/x '+' '.join('[$'+a.split('.')[0].lower()+'].'+a.split('.')[1] for a in addresses)+'\nquit\n'
                    code,out,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(image)],commands,30)
                    self.assertFalse(timed,out);self.assertEqual(code,0,out)
                    values=_blastem_values(out)
                    self.assertEqual(values.get('FF0018.l'),0,out)
                    self.assertEqual(values.get('FF0038.l'),0,out)
                    observations.append([values.get(a) for a in addresses])
            self.assertEqual(observations[0],observations[1],(name,observations))
