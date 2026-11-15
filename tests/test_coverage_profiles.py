"""Original cartridge fixtures for reusable, explicitly bounded coverage."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from coverage_profiles import load_coverage_profiles
from trace_recompiler import compile_trace


def rom_image():
    rom = bytearray(0x8000)
    rom[0x100:0x103] = bytes.fromhex('c35001')
    # A tag precedes each inline routine; boot selects only the first stream.
    rom[0x150:0x155] = bytes.fromhex('21000223e9')
    rom[0x200:0x208] = bytes.fromhex('083e42ea00c018fe')
    rom[0x220:0x228] = bytes.fromhex('083e99ea00c018fe')
    return bytes(rom)


class CoverageProfileTests(unittest.TestCase):
    def make_profile(self, root, rom, blocks):
        path = root / 'coverage.json'
        path.write_text(json.dumps({'source_sha256': hashlib.sha256(rom).hexdigest(), 'blocks': blocks}))
        return path

    def test_import_closes_indirect_path_without_replaying_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);rom=rom_image();source=root/'original.gb';source.write_bytes(rom)
            block={'bank':0,'pc':0x221,'bytes':'3e99','hits':1}
            path=self.make_profile(root,rom,[block])
            plain=compile_trace(source,root/'plain',10)
            merged=compile_trace(source,root/'merged',10,coverage_profiles=[path,path])
            self.assertNotIn((0,0x221),{(b['bank'],b['pc']) for b in plain})
            self.assertIn((0,0x223),{(b['bank'],b['pc']) for b in merged})
            report=json.loads((root/'merged/trace-profile.json').read_text())
            self.assertEqual(report['source_sha256'],hashlib.sha256(rom).hexdigest())
            self.assertEqual(report['total_steps_executed'],10)
            self.assertEqual(len(report['coverage_imports']),1)
            self.assertEqual(report['coverage_imports'][0]['new_entries'],1)

    def test_rejects_mismatched_rom_bytes_digest_shape_and_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);rom=rom_image();good={'bank':0,'pc':0x221,'bytes':'3e99','hits':1}
            for patch in ({'bank':1},{'bank':2},{'bytes':'3e42'},{'bytes':'3e'},
                          {'pc':65535},{'hits':-1},{'hits':True},{'observed_variants':['00']}):
                with self.subTest(patch=patch):
                    path=self.make_profile(root,rom,[dict(good,**patch)])
                    with self.assertRaises(ValueError):load_coverage_profiles(rom,[path])
            path=self.make_profile(root,rom,[good,good])
            with self.assertRaises(ValueError):load_coverage_profiles(rom,[path])
            path=self.make_profile(root,rom,[good]);wrong=bytearray(rom);wrong[-1]=1
            with self.assertRaises(ValueError):load_coverage_profiles(bytes(wrong),[path])
            path.write_text('{}')
            with self.assertRaises(ValueError):load_coverage_profiles(rom,[path])
            with self.assertRaises(ValueError):load_coverage_profiles(rom,[path]*17)

    def test_ram_variants_are_preserved_as_guarded_observations(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);rom=rom_image();source=root/'original.gb';source.write_bytes(rom)
            path=self.make_profile(root,rom,[{'bank':0,'pc':0xC100,'bytes':'3e42','hits':1,'observed_variants':['3e99']}])
            blocks=compile_trace(source,root/'out',2,coverage_profiles=[path])
            block=next(b for b in blocks if b['pc']==0xC100)
            self.assertEqual(block['observed_variants'],['3e99'])
            assembly=(root/'out/translated_trace.s').read_text()
            self.assertIn('L_gb_B000_C100',assembly)
            self.assertIn('gb_missing_block',assembly)

    def test_static_imports_are_not_reported_as_new_dynamic_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);rom=rom_image();source=root/'original.gb';source.write_bytes(rom)
            path=self.make_profile(root,rom,[{'bank':0,'pc':0x221,'bytes':'3e99','hits':0}])
            compile_trace(source,root/'out',2,coverage_profiles=[path])
            report=json.loads((root/'out/trace-profile.json').read_text())
            self.assertEqual(report['dynamic_unique_blocks'],2)
            self.assertEqual(report['fresh_dynamic_unique_block_count'],2)
            self.assertEqual(report['coverage_imports'][0]['observed_entries'],0)

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_import_executes_only_live_selected_path(self):
        from build_recompiled import build
        from run_compat_tests import _run_in_pty, _blastem_values
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);rom=bytearray(rom_image())
            # Select the imported branch through normal source execution.
            rom[0x150:0x154]=bytes.fromhex('21200223');rom[0x154]=0xE9
            source=root/'original.gb';source.write_bytes(rom)
            path=self.make_profile(root,bytes(rom),[{'bank':0,'pc':0x221,'bytes':'3e99','hits':1}])
            image=build(source,root/'out',2,coverage_profiles=[path])
            rc,out,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(image)],
                'frames 120\np/x [$ff2300].b [$ff0018].l [$ff0038].l\nquit\n',20)
            self.assertFalse(timed,out);self.assertEqual(rc,0,out)
            values=_blastem_values(out)
            self.assertEqual(values.get('FF2300.b'),0x99,out)
            self.assertEqual(values.get('FF0018.l'),0,out)
            self.assertEqual(values.get('FF0038.l'),0,out)

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_import_keeps_ram_variants_and_unseen_code_traps(self):
        from build_recompiled import build
        from run_compat_tests import _run_in_pty, _blastem_values
        for value in (0x99,0x17):
            with self.subTest(value=value),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);rom=bytearray(rom_image());code=bytearray.fromhex('2100c1')
                for i,byte in enumerate((0x3E,value,0xEA,0,0xC0,0x18,0xFE)):
                    if i:code.append(0x23)
                    code.extend((0x36,byte))
                code.extend(bytes.fromhex('c300c1'));rom[0x150:0x150+len(code)]=code
                source=root/'original.gb';source.write_bytes(rom)
                path=self.make_profile(root,bytes(rom),[
                    {'bank':0,'pc':0xC100,'bytes':'3e42','hits':1,'observed_variants':['3e99']},
                    {'bank':0,'pc':0xC102,'bytes':'ea00c0','hits':1},
                    {'bank':0,'pc':0xC105,'bytes':'18fe','hits':1}])
                image=build(source,root/'out',2,coverage_profiles=[path])
                rc,out,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(image)],
                    'frames 120\np/x [$ff2300].b [$ff0018].l [$ff0038].l\nquit\n',20)
                self.assertFalse(timed,out);self.assertEqual(rc,0,out);values=_blastem_values(out)
                self.assertEqual(values.get('FF2300.b'),0x99 if value==0x99 else 0,out)
                self.assertEqual(values.get('FF0018.l'),0 if value==0x99 else 0xBADB10C0,out)
                self.assertEqual(values.get('FF0038.l'),0 if value==0x99 else 1,out)
