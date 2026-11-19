"""Original protocol fixtures; no third-party test ROM bytes are included."""
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

import run_compat_tests as runner


class GbMicroProtocolTests(unittest.TestCase):
    def test_mooneye_manual_tools_and_explicit_model_names(self):
        for suite in ('mooneye-test-suite','mooneye-test-suite-wilbertpol'):
            for folder in ('manual-only','utils'):
                self.assertEqual(runner.protocol_for(Path(f'test_roms/{suite}/{folder}/original.gb')),'manual_visual')
            self.assertFalse(runner.model_support(Path(f'test_roms/{suite}/misc/boot_regs-cgb.gb'))[0])
            self.assertFalse(runner.model_support(Path(f'test_roms/{suite}/misc/boot_div-cgbABCDE.gb'))[0])
            self.assertTrue(runner.model_support(Path(f'test_roms/{suite}/acceptance/boot_div-dmgABCmgb.gb'))[0])

    def test_reference_boot_palette_matches_native_startup(self):
        # Original program observes the post-boot register before writing it.
        rom=bytearray(0x8000);rom[0x100:0x105]=bytes.fromhex('f047ea00c0')
        memory=runner.ProtocolMemory(rom);cpu=runner.CPU(memory)
        cpu.step();cpu.step()
        self.assertEqual(memory.wram[0],0xFC)
        memory.write(0xFF47,0xE4);self.assertEqual(memory.read(0xFF47),0xE4)

    def test_suite_detection_and_result_flag_only(self):
        self.assertEqual(runner.protocol_for(Path('test_roms/gbmicrotest/original.gb')),'gbmicro_hram')
        memory=runner.ProtocolMemory(bytes(0x8000));memory.cycles=runner.GBMICRO_OBSERVE_CYCLES
        for flag,expected in ((1,'PASS'),(255,'FAIL')):
            memory.write(0xFF80,0x42);memory.write(0xFF81,0x42);memory.write(0xFF82,flag)
            self.assertEqual(runner.gbmicro_result(memory)[0],expected)
        memory.write(0xFF82,0);self.assertIsNone(runner.gbmicro_result(memory))
        memory.write(0xFF82,1);memory.cycles-=1;self.assertIsNone(runner.gbmicro_result(memory))

    def test_early_flag_not_accepted_and_idle_loop_can_reach_floor(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);suite=root/'gbmicrotest';suite.mkdir();p=suite/'original.gb'
            rom=bytearray(0x8000);rom[0x100:0x108]=bytes.fromhex('3e01e082f37618fe');p.write_bytes(rom)
            short=runner.run_python(p,root,1000,1,10)
            self.assertEqual(short['python']['status'],'TIMEOUT')
            full=runner.run_python(p,root,500000,24,10)
            self.assertEqual(full['python']['status'],'PASS')
            self.assertGreaterEqual(full['python']['cycles'],runner.GBMICRO_OBSERVE_CYCLES)
            self.assertEqual(full['native_genesis']['status'],'NOT_RUN')

    def test_native_observer_rejects_early_flags_and_equal_failure_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'original.gb';source.write_bytes(bytes(0x8000))
            for cycles,flag,expected in ((0,1,'TIMEOUT'),(runner.GBMICRO_OBSERVE_CYCLES,255,'FAIL'),(runner.GBMICRO_OBSERVE_CYCLES,1,'PASS')):
                item={'protocol':'gbmicro_hram','native_genesis':{'build_status':'BUILT','artifact':str(root/'out.md')}}
                output=f'[$ff0020].l: {cycles:x}\n[$ff0180].b: 42\n[$ff0181].b: 42\n[$ff0182].b: {flag:x}\n[$ff0018].l: 0\n[$ff0038].l: 0\n'
                with patch.object(runner,'_run_in_pty',return_value=(0,output,False)) as launched:
                    runner.run_native_blastem(item,source,root/'blastem',900,30)
                self.assertEqual(item['native_genesis']['status'],expected)
                self.assertIn('[$ff0182].b',launched.call_args.args[1])

    def test_missing_native_block_takes_precedence_over_pass_flag(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'original.gb';source.write_bytes(bytes(0x8000))
            item={'protocol':'gbmicro_hram','native_genesis':{'build_status':'BUILT','artifact':str(root/'out.md')}}
            output=f'[$ff0020].l: {runner.GBMICRO_OBSERVE_CYCLES:x}\n[$ff0182].b: 1\n[$ff0018].l: badb10c0\n[$ff0038].l: 1\n'
            with patch.object(runner,'_run_in_pty',return_value=(0,output,False)):
                runner.run_native_blastem(item,source,root/'blastem',900,30)
            self.assertEqual(item['native_genesis']['status'],'FAIL')
            self.assertEqual(item['native_genesis']['category'],'missing_native_block')

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_original_flag_protocol(self):
        from build_recompiled import build
        for flag,expected in ((1,'PASS'),(255,'FAIL')):
            with self.subTest(flag=flag),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);source=root/'original.gb';rom=bytearray(0x8000)
                code=bytes((0x3e,0x42,0xe0,0x80,0xe0,0x81,0x3e,flag,0xe0,0x82,0xf3,0x76,0x18,0xfe))
                rom[0x100:0x100+len(code)]=code;source.write_bytes(rom)
                image=build(source,root/'out',2)
                item={'protocol':'gbmicro_hram','native_genesis':{'build_status':'BUILT','artifact':str(image)}}
                original=runner._run_in_pty
                def host_turbo(command,commands,timeout):
                    return original(command,'binddown "ui.set_speed.4"\nbindup "ui.set_speed.4"\n'+commands,timeout)
                # Host acceleration only; the source-clock floor still applies.
                with patch.object(runner,'_run_in_pty',side_effect=host_turbo):
                    runner.run_native_blastem(item,source,Path(os.environ['GB2MD_BLASTEM']),4000,45)
                self.assertEqual(item['native_genesis']['status'],expected,item)
                self.assertEqual(item['native_genesis']['category'],'protocol')
