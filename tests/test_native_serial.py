"""Original diagnostic programs and independent native protocol checks."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from serial_test import SerialTestMemory, SERIAL_BUFFER_BASE, SERIAL_CAPACITY
from run_compat_tests import run_native_blastem


def serial_fixture(text=b'Passed\n', wait_for_peer=True):
    rom=bytearray(0x8000)
    code=bytearray(bytes.fromhex('f331fedf'))
    for value in text:
        code.extend(bytes([0x3E,value,0xE0,1,0x3E,0x81,0xE0,2]))
        if wait_for_peer:code.extend(bytes.fromhex('f002cb7f20fa'))
    code.extend(bytes.fromhex('3e42ea00c018fe'))
    # Keep original test code out of the cartridge header area.
    rom[0x100:0x103]=bytes.fromhex('c35001')
    rom[0x150:0x150+len(code)]=code
    return bytes(rom)


def serial_dump(text=b'Passed\n',count=None,overflow=0,marker=0,missing=0):
    data=text.ljust(SERIAL_CAPACITY,b'\0')[:SERIAL_CAPACITY]
    lines=[f'[$ffc600].w: {len(text) if count is None else count:x}',
           f'[$ffc602].b: {overflow:x}',f'[$ff0018].l: {marker:x}',
           f'[$ff0038].l: {missing:x}','[$ff0000].w: 0','[$ff0002].w: 150']
    lines += [f'[${SERIAL_BUFFER_BASE+i:06x}].l: {int.from_bytes(data[i:i+4],"big"):x}' for i in range(0,SERIAL_CAPACITY,4)]
    return '\n'.join(lines)


class NativeSerialTests(unittest.TestCase):
    def test_reference_peer_is_explicit_and_completes_only_internal_transfers(self):
        from gb_cpu import CPU,Memory
        rom=serial_fixture();m=SerialTestMemory(rom);c=CPU(m)
        for _ in range(200):c.step()
        self.assertEqual(m.serial,b'Passed\n');self.assertEqual(m.wram[0],0x42)
        normal=Memory(rom);normal.write(0xFF02,0x81)
        self.assertEqual(normal.io[2],0x81)
        m.write(0xFF02,0x80);m.write(0xFF02,0x01)
        self.assertEqual(m.serial,b'Passed\n')

    def observe(self,output,code=0,timed=False,instrumented=True):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'original.gb';source.write_bytes(serial_fixture())
            result={'protocol':'blargg_serial','native_genesis':{'status':'NOT_RUN','build_status':'BUILT','artifact':str(Path(folder)/'original.md'),'build_report':{'test_serial':instrumented}}}
            with patch('run_compat_tests._run_in_pty',return_value=(code,output,timed)) as emulator:
                run_native_blastem(result,source,Path('/tmp/blastem'),600,10)
            return result['native_genesis'],emulator.call_count

    def test_native_protocol_pass_fail_timeout_are_independent(self):
        for text,status in ((b'Passed\n','PASS'),(b'Failed #3\n','FAIL'),(b'Testing\n','TIMEOUT')):
            with self.subTest(text=text):
                result,calls=self.observe(serial_dump(text))
                self.assertEqual(calls,1);self.assertEqual(result['status'],status)
                self.assertEqual(result['serial_output'],text.decode())

    def test_observer_refuses_uninstrumented_build_and_invalid_dump(self):
        result,calls=self.observe(serial_dump(),instrumented=False)
        self.assertEqual((result['status'],calls),('NOT_RUN',0))
        for output in (serial_dump(count=513),serial_dump().split('[$ffd000]')[0],serial_dump(overflow=1)):
            result,_=self.observe(output)
            self.assertEqual(result['status'],'FAIL');self.assertTrue(result['category'].startswith('observer'))

    def test_missing_block_and_emulator_failure_override_serial_pass(self):
        for output,code,timed,category in ((serial_dump(marker=0xBADB10C0,missing=1),0,False,'missing_native_block'),(serial_dump(),1,False,'emulator_exit'),(serial_dump(),0,True,'emulator_timeout')):
            result,_=self.observe(output,code,timed)
            self.assertNotEqual(result['status'],'PASS');self.assertEqual(result['category'],category)

    def test_trace_peer_can_cover_code_after_serial_busy_wait(self):
        from trace_recompiler import compile_trace
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'original.gb';rom=serial_fixture();source.write_bytes(rom)
            blocks=compile_trace(source,root/'out',200,test_serial=True)
            marker=rom.find(bytes.fromhex('3e42ea00c0'))
            self.assertIn((0,marker),{(b['bank'],b['pc']) for b in blocks if b['hits']})

    def test_cli_returns_failure_for_native_failure_after_python_pass(self):
        import run_compat_tests as runner
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'original.gb';source.write_bytes(serial_fixture())
            result={'python':{'status':'PASS'},'native_genesis':{'status':'NOT_RUN'}}
            def native_failure(*args):args[0]['native_genesis'].update(status='FAIL',category='protocol')
            with patch.object(runner,'run_python',return_value=result),patch.object(runner,'compile_native'),patch.object(runner,'run_native_blastem',side_effect=native_failure):
                code=runner.main([str(source),'--root',str(root),'--json',str(root/'report.json'),'--compile-native','--run-native-blastem','--blastem',str(source)])
            self.assertEqual(code,1)

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_original_serial_messages_and_peer_completion(self):
        from build_recompiled import build
        for text,status in ((b'Passed\n','PASS'),(b'Failed #3\n','FAIL')):
            with self.subTest(text=text),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);source=root/'original.gb';source.write_bytes(serial_fixture(text))
                artifact=build(source,root/'out',500,test_serial=True)
                result={'protocol':'blargg_serial','native_genesis':{'status':'NOT_RUN','build_status':'BUILT','artifact':str(artifact),'build_report':json.loads((root/'out'/'build-report.json').read_text())}}
                run_native_blastem(result,source,Path(os.environ['GB2MD_BLASTEM']),180,20)
                self.assertEqual(result['native_genesis']['status'],status,result)
                self.assertEqual(result['native_genesis']['serial_output'],text.decode())
