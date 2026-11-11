"""Clock-rate HUD: original font, nominal PAL/NTSC intervals, native samples."""
import json,os,re,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from fps_overlay import FONT_TILE,GLYPHS,font_assembly,rate_tenths


class FpsOverlayTests(unittest.TestCase):
    def test_rate_is_source_clock_progress_not_render_count(self):
        self.assertEqual(rate_tenths(70224*30),300)
        self.assertEqual(rate_tenths(70224*60),600)
        self.assertEqual(rate_tenths(70224//5),1) # flooring at0.1 precision
        self.assertEqual(rate_tenths(0),0)

    def test_wrap_and_saturation(self):
        start=0xFFFFF000;end=(start+70224*17)&0xFFFFFFFF
        self.assertEqual(rate_tenths((end-start)&0xFFFFFFFF),170)
        self.assertEqual(rate_tenths(70224000),9999)
        self.assertEqual(rate_tenths(0xFFFFFFFF),9999)

    def test_original_font_fits_reserved_tiles(self):
        self.assertEqual(FONT_TILE,644)
        self.assertEqual(len(GLYPHS),17)
        self.assertTrue(all(len(rows)==7 and all(len(row)==5 and set(row)<={'0','1'} for row in rows) for rows in GLYPHS.values()))
        assembly=font_assembly()
        self.assertEqual(assembly.count('\tdc.l '),17)
        self.assertIn('gb_fps_header:',assembly)

    def test_gui_forwards_optional_setting(self):
        from gb2md_gui import compiler_command
        _,normal=compiler_command(Path('/tmp/original.gb'),Path('/tmp/out'),100)
        _,enabled=compiler_command(Path('/tmp/original.gb'),Path('/tmp/out'),100,show_fps=True)
        self.assertNotIn('--show-fps',normal);self.assertEqual(enabled,normal+['--show-fps'])

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_pal_ntsc_samples_and_frozen_source(self):
        from build_recompiled import build
        import build_recompiled as compiler
        from benchmark_chains import benchmark_rom
        from trace_recompiler import emit_native_blocks
        from run_compat_tests import _run_in_pty,_blastem_values
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'original.gb';source.write_bytes(benchmark_rom('video'))
            artifact=build(source,root/'out',2000,show_fps=True)
            self.assertGreater(int.from_bytes(artifact.read_bytes()[0x78:0x7C],'big'),0x200)
            for region,hz in (('U',60),('E',50)):
                query='p/x [$ff0060].l [$ff0064].l [$ff006a].w [$ff006c].w [$ff0070].l [$ff0018].l [$ff0038].l\n'
                command='frames 180\n'+query+f'frames {hz}\n'+query+'quit\n'
                code,output,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-r',region,'-d',str(artifact)],command,30)
                self.assertFalse(timed,output);self.assertEqual(code,0,output);values=_blastem_values(output)
                self.assertEqual(values.get('FF006A.w'),hz,output)
                self.assertEqual(values.get('FF0018.l'),0,output);self.assertEqual(values.get('FF0038.l'),0,output)
                snapshots=[int(x,16) for x in re.findall(r'\[\$ff0064\]\.l:\s*([0-9a-f]+)',output,re.I)]
                self.assertEqual(len(snapshots),2,output)
                self.assertEqual(values.get('FF006C.w'),rate_tenths((snapshots[1]-snapshots[0])&0xFFFFFFFF),output)
                self.assertGreater(values.get('FF0070.l',0),1,output)
            # Deliberately incomplete original coverage: no source clock runs
            # inside the missing-block trap, but the host-clock HUD must live.
            original=compiler.compile_trace
            def missing(*args,**kwargs):
                blocks=original(*args,**kwargs);blocks=[b for b in blocks if (b['bank'],b['pc'])!=(0,0x150)]
                emit_native_blocks(blocks,args[1]);return blocks
            with patch.object(compiler,'compile_trace',side_effect=missing):
                frozen=build(source,root/'frozen',2000,show_fps=True)
            code,output,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(frozen)],'frames 600\np/x [$ff0060].l [$ff006c].w [$ff0070].l [$ff0018].l [$ff0038].l\nquit\n',45)
            self.assertFalse(timed,output);self.assertEqual(code,0,output);values=_blastem_values(output)
            self.assertEqual(values.get('FF0018.l'),0xBADB10C0,output)
            self.assertEqual(values.get('FF006C.w'),0,output)
            self.assertGreater(values.get('FF0070.l',0),1,output)
