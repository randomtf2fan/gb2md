"""Assembler convergence retry must be bounded and preserve existing images."""
import json,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import build_recompiled as compiler


class AssemblerRetryTests(unittest.TestCase):
    def source(self,root):
        rom=bytearray(0x8000);rom[0x100:0x107]=bytes.fromhex('3e42ea00c018fe')
        source=root/'original.gb';source.write_bytes(rom)
        assembler=root/'assembler';assembler.touch()
        return source,assembler

    def test_convergence_failure_retries_without_retracing(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source,assembler=self.source(root);calls=[]
            def assemble(command,**kwargs):
                calls.append(command)
                if len(calls)==1:
                    raise subprocess.CalledProcessError(1,command,output='',stderr='fatal error8: maximum number of passes reached\n')
                Path(command[-1]).write_bytes(bytes(0x80000))
                return subprocess.CompletedProcess(command,0,'assembled\n','')
            with patch.object(compiler,'compile_trace',wraps=compiler.compile_trace) as trace,patch.object(compiler.subprocess,'run',side_effect=assemble):
                artifact=compiler.build(source,root/'out',20,assembler=assembler)
            self.assertEqual(trace.call_count,1);self.assertEqual(len(calls),2)
            self.assertNotIn('-no-opt',calls[0]);self.assertIn('-no-opt',calls[1])
            self.assertEqual(artifact.stat().st_size,0x80000)
            report=json.loads((root/'out'/'build-report.json').read_text())
            self.assertEqual(report['assembler_options'],['-no-opt'])
            self.assertEqual(len(report['assembler_retries']),1)

    def test_other_errors_fail_directly_and_repeated_convergence_failure_is_bounded(self):
        for diagnostic,attempts in (('undefined symbol',1),('maximum number of passes reached',2)):
            with self.subTest(diagnostic=diagnostic),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);source,assembler=self.source(root);out=root/'out';out.mkdir()
                previous=out/'recompiled.md';previous.write_bytes(b'preserve previous image')
                failure=subprocess.CalledProcessError(1,['assembler'],output='',stderr=diagnostic)
                with patch.object(compiler.subprocess,'run',side_effect=failure) as run:
                    with self.assertRaises(subprocess.CalledProcessError):compiler.build(source,out,20,assembler=assembler)
                self.assertEqual(run.call_count,attempts)
                self.assertEqual(previous.read_bytes(),b'preserve previous image')
