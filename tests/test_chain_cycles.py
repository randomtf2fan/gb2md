"""Constant-cycle specialization must retain native timing/IRQ boundaries."""
import json,os,tempfile,unittest
from pathlib import Path
from trace_recompiler import compile_trace,emit_native_blocks


def cycle_fixture():
    code=bytes.fromhex('f3afe04031fedfafe00406000e55')
    code+=bytes.fromhex('040d78a9')*32
    code+=bytes.fromhex('f004ea01c0fb00f33e42ea00c0f5c178ea02c00803c018fe')
    rom=bytearray(0x8000);rom[0x100:0x103]=bytes.fromhex('c35001');rom[0x150:0x150+len(code)]=code
    return bytes(rom)


class ChainCycleTests(unittest.TestCase):
    def emit(self,code,**options):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        root=Path(folder.name);rom=bytearray(0x8000);rom[0x100:0x100+len(code)]=code
        source=root/'original.gb';source.write_bytes(rom);blocks=compile_trace(source,root/'out',200)
        emit_native_blocks(blocks,root/'out',**options)
        return (root/'out'/'translated_trace.s').read_text(),json.loads((root/'out'/'native-codegen-report.json').read_text())

    def test_fixed_cycles_drop_fast_path_loads_but_restore_pending_cost_on_flush(self):
        text,report=self.emit(bytes.fromhex('040d18fc'))
        self.assertGreater(report['constant_cycle_chain_targets'],0)
        stub=text.split('gb_chain_B000_0101:',1)[1].split('gb_chain_',1)[0]
        self.assertIn('cmpi.w #196,d7',stub)
        self.assertIn('addq.w #4,d7',stub)
        self.assertIn('.chain_flush_B000_0101:\n\tmove.b #4,gb_step_cycles',stub)
        self.assertNotIn('move.b gb_step_cycles,d0',stub)
        entry=text.split('L_gb_B000_0100:',1)[1].split('L_gb_',1)[0]
        self.assertNotIn('gb_step_cycles',entry)
        self.assertIn('gb_ei_delay',stub);self.assertIn('gb_force_tick',stub)

    def test_memory_and_cpu_control_predecessors_use_generic_costs(self):
        for code in ('f00418fc','ea00c018fb','fb0018fc','f30018fc','361118fc'):
            with self.subTest(code=code):
                text,report=self.emit(bytes.fromhex(code))
                first=text.split('L_gb_B000_0100:',1)[1].split('L_gb_',1)[0]
                self.assertIn('gb_step_cycles',first)

    def test_mixed_cost_predecessors_reject_target_specialization(self):
        # NOP at100 ->101; JR at102 also returns101. A shared target
        # cannot assume the four-cycle NOP when entered from a twelve-cycle JR.
        text,_=self.emit(bytes.fromhex('000418fd'))
        stub=text.split('gb_chain_B000_0101:',1)[1].split('gb_chain_',1)[0]
        self.assertIn('move.b gb_step_cycles,d0',stub)

    def test_disabled_and_compact_modes_keep_pending_cycle_stores(self):
        for options in ({'optimize_pure_chains':False},{'max_hot_chains':0}):
            text,report=self.emit(bytes.fromhex('040d18fc'),**options)
            self.assertEqual(report['constant_cycle_chain_targets'],0)
            self.assertEqual(report['elided_cycle_stores'],0)
            self.assertIn('move.b #4,gb_step_cycles',text)

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_ab_timing_irq_and_mapper_state(self):
        from build_recompiled import build
        from run_compat_tests import _run_in_pty,_blastem_values
        from test_smoke import stat_diagnostic_rom,bank_switch_diagnostic_rom
        fixtures=(('cycles',cycle_fixture()),('irq',stat_diagnostic_rom()),('mapper',bank_switch_diagnostic_rom()))
        for name,rom in fixtures:
            observations=[]
            for enabled in (False,True):
                with self.subTest(name=name,enabled=enabled),tempfile.TemporaryDirectory() as folder:
                    root=Path(folder);source=root/'original.gb';source.write_bytes(rom)
                    artifact=build(source,root/'out',3000,optimize_pure_chains=enabled)
                    addresses=['FF2300.b','FF2301.b','FF2302.b','FF2303.b','FF2304.b','FF0018.l','FF0038.l']
                    commands='frames 600\np/x '+' '.join('[$'+a.split('.')[0].lower()+'].'+a.split('.')[1] for a in addresses)+'\nquit\n'
                    code,output,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(artifact)],commands,30)
                    self.assertFalse(timed,output);self.assertEqual(code,0,output)
                    values=_blastem_values(output);self.assertEqual(values.get('FF0018.l'),0,output)
                    self.assertEqual(values.get('FF0038.l'),0,output)
                    observations.append([values.get(a) for a in addresses])
            self.assertEqual(observations[0],observations[1],(name,observations))
            self.assertEqual(observations[0][0],0x42)
