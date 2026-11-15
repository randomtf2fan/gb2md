"""Constant HRAM access must retain flags, bus boundaries and mutable code."""
import json,os,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from gb_cpu import CPU,Memory
from trace_recompiler import native_body,family,compile_trace,emit_native_blocks


def hram_fixture(kind):
    rom=bytearray(0x8000);rom[0x100:0x103]=bytes.fromhex('c35001')
    prefix=bytes.fromhex('f331fedfafe040e007')
    if kind=='roundtrip':
        code=bytes.fromhex('3e5a37e080f080ea10c0fa80ffea11c03ea5eafefffafeffea12c0f5c179ea13c0f004ea14c0')
    elif kind=='mutable':
        code=bytes.fromhex('2180ff363e2336112336c9cd80ffea10c03e22e081cd80ffea11c0')
    elif kind=='mutable-address':
        code=bytes.fromhex('3e11e0f03e22e0f12180ff36f02336f02336c9cd80ffea10c03ef1e081cd80ffea11c0')
    elif kind=='dma':
        body=bytes.fromhex('3ec0e0463e5ae0eef0eee0ef06280520fdf0efea10c0faeeffea11c03e42ea15c018fe')
        rom[0x200:0x200+len(body)]=body
        code=bytes.fromhex('1100022180ff')+bytes([0x06,len(body)])+bytes.fromhex('1a22130520fac380ff')
    else:raise ValueError(kind)
    code=prefix+code+(b'' if kind=='dma' else bytes.fromhex('3e42ea15c018fe'))
    rom[0x150:0x150+len(code)]=code
    return bytes(rom)


def reference(kind):
    memory=Memory(hram_fixture(kind));cpu=CPU(memory)
    for _ in range(5000):cpu.step()
    return memory,cpu


class HramLoweringTests(unittest.TestCase):
    def test_only_constant_hram_bytes_are_specialized(self):
        for op in (0xE0,0xF0,0xEA,0xFA):
            for address in (0xFF7F,0xFF80,0xFFFE,0xFFFF):
                with self.subTest(op=op,address=address):
                    raw=bytes([op,address&255]) if op in (0xE0,0xF0) else bytes([op,address&255,address>>8])
                    block={'bank':0,'pc':0x100,'opcode':op,'operand':address&255 if len(raw)==2 else address,'bytes':raw.hex(),'family':family(op)}
                    body=native_body(block);direct=any('gb_hram+$' in x for x in body)
                    self.assertEqual(direct,0xFF80<=address<0xFFFF)
                    self.assertFalse(any('gb_hram+$' in x for x in native_body(block,optimize_hram=False)))
                    if direct:
                        self.assertFalse(any('jsr ' in x for x in body))
                        self.assertEqual(body.count('addq.l #1,gb_write_count'),int(op in (0xE0,0xEA)))
        for op in (0xE2,0xF2,0x0A,0x1A):
            body=native_body({'bank':0,'pc':0x100,'opcode':op,'operand':0,'bytes':bytes([op]).hex(),'family':family(op)})
            self.assertTrue(any('jsr gb_' in x for x in body))

    def test_reference_original_fixtures(self):
        for kind in ('roundtrip','mutable','mutable-address','dma'):
            m,c=reference(kind);self.assertEqual(m.wram[0x15],0x42)
            self.assertEqual(c.sp,0xDFFE)
        m,_=reference('roundtrip');self.assertEqual(m.wram[0x10:0x14],bytes([0x5A,0x5A,0xA5,0x90]))
        m,_=reference('mutable');self.assertEqual(m.wram[0x10:0x12],bytes([0x11,0x22]))
        m,_=reference('mutable-address');self.assertEqual(m.wram[0x10:0x12],bytes([0x11,0x22]))
        m,_=reference('dma');self.assertEqual(m.wram[0x10:0x12],bytes([0x5A,0x5A]));self.assertFalse(m.dma_active)

    def test_reports_and_capacity_retries_retain_disabled_mode(self):
        import build_recompiled as compiler
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'original.gb';source.write_bytes(hram_fixture('roundtrip'))
            blocks=compile_trace(source,root/'out',500)
            stats=json.loads((root/'out/native-codegen-report.json').read_text());self.assertGreater(stats['direct_hram_sites'],0)
            assembler=root/'assembler';assembler.touch();calls=[]
            def assemble(command,**kwargs):
                calls.append(command);Path(command[-1]).write_bytes(bytes(0x400002 if len(calls)==1 else 0x80000))
                return subprocess.CompletedProcess(command,0,'','')
            with patch.object(compiler.subprocess,'run',side_effect=assemble):
                compiler.build(source,root/'out',500,assembler=assembler,optimize_hram=False)
            stats=json.loads((root/'out/native-codegen-report.json').read_text())
            self.assertFalse(stats['optimize_hram']);self.assertEqual(stats['direct_hram_sites'],0)
            self.assertFalse(json.loads((root/'out/build-report.json').read_text())['optimize_hram'])

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_values_flags_clock_stack_dma_and_variants(self):
        from build_recompiled import build
        from run_compat_tests import _run_in_pty,_blastem_values
        for kind in ('roundtrip','mutable','mutable-address','dma'):
            observations=[];m,_=reference(kind)
            for enabled in (False,True):
                with self.subTest(kind=kind,enabled=enabled),tempfile.TemporaryDirectory() as folder:
                    root=Path(folder);source=root/'original.gb';source.write_bytes(hram_fixture(kind))
                    image=build(source,root/'out',5000,optimize_hram=enabled)
                    keys=[f'FF23{x:02X}.b' for x in range(0x10,0x16)]+['FF0010.w','FF0014.l','FF0018.l','FF0038.l']
                    commands='frames 600\np/x '+' '.join('[$'+key.split('.')[0].lower()+'].'+key.split('.')[1] for key in keys)+'\nquit\n'
                    rc,out,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(image)],commands,30)
                    self.assertFalse(timed,out);self.assertEqual(rc,0,out);v=_blastem_values(out)
                    self.assertEqual([v.get(k) for k in keys[:6]],list(m.wram[0x10:0x16]),out)
                    self.assertEqual(v.get('FF0010.w'),0xDFFE,out)
                    self.assertEqual(v.get('FF0018.l'),0,out);self.assertEqual(v.get('FF0038.l'),0,out)
                    observations.append([v.get(k) for k in keys])
            self.assertEqual(observations[0],observations[1],(kind,observations))
