"""Original fetch-context, control-flow, IRQ and coverage-profile fixtures."""
import hashlib,json,os,tempfile,unittest
from pathlib import Path
from gb_cpu import CPU,Memory
from trace_recompiler import compile_trace
from coverage_profiles import load_coverage_profiles


def context_rom(case):
    rom=bytearray(0x8000)
    code=bytearray.fromhex('f3afe040e004e005e00f3e05e00706000e02')
    if case.startswith('late'):
        # A timer IRQ approaches HALT's fetch boundary; padding shifts it.
        code=bytearray.fromhex('f3afe040e00f06000e023e04eaffffafe007e0043effe0053e06e007')
        code+=b'\x00'*int(case[4:]);code+=b'\x76';fetch=0x100+len(code);code+=b'\x04'
    else:
        code+=bytes.fromhex('3e01eaffffe00f')
        if case in ('ei_halt','ei_nop'):
            code+=b'\xfb'+(b'\x00' if case=='ei_nop' else b'')
        halt=0x100+len(code);code+=b'\x76';fetch=0x100+len(code)
        if case in ('ei_halt','ei_nop'):
            # Inspect IRQ's actual saved PC; discard it and finish the probe.
            handler=bytearray.fromhex('04f8002aea00c07eea01c078ea05c0c1c3')
            finish=0x100+len(code)+3;handler+=finish.to_bytes(2,'little')
            rom[0x40:0x40+len(handler)]=handler;code+=bytes.fromhex('c30001')
        elif case=='single':code+=bytes.fromhex('0478ea00c03e42ea01c0')
        elif case=='word':code+=bytes.fromhex('2104c07cea00c07dea01c0')
        elif case=='cb':code+=bytes.fromhex('cb060478ea00c07bea01c0')
        elif case in ('jr','jr_z'):
            op=0x18 if case=='jr' else 0x28;code+=bytes((op,op))
            code+=bytes(op-1);code+=bytes.fromhex('0478ea00c03e42ea01c0')
        elif case=='jr_not':code+=bytes.fromhex('200478ea00c03e42ea01c0')
        elif case in ('call','call_z','call_not'):
            op={'call':0xcd,'call_z':0xcc,'call_not':0xc4}[case]
            code+=bytes((op,4,4))+bytes.fromhex('78ea00c03e42ea01c0')
            rom[0x400+op]=0xc9
        elif case=='rst':
            rom[:2]=bytes.fromhex('04c9');code+=bytes.fromhex('c778ea00c03e42ea01c0')
        elif case=='mixed':
            code+=bytes.fromhex('3e04ea01c00d')+bytes((0xc2,fetch&255,fetch>>8))+bytes.fromhex('78ea00c0')
        else:raise ValueError(case)
    if case.startswith('late'):code+=bytes.fromhex('78ea00c03e42ea01c0')
    code+=bytes.fromhex('f004ea03c0f005ea04c03ea5ea02c0f318fe')
    rom[0x100:0x100+len(code)]=code
    return bytes(rom),fetch


def bank_rom(bank,mapper):
    rom,_=context_rom('single');image=bytearray(0x10000)
    logical=0x4800;physical=bank*0x4000+logical-0x4000
    image[physical:physical+0x100]=rom[0x100:0x200]
    image[0x147:0x14a]=bytes((mapper,1,0))
    image[0x100:0x108]=bytes((0x3e,bank,0xea,0,0x20,0xc3,0,0x48))
    return bytes(image)


def edge_rom(unsupported=False):
    rom,fetch=context_rom('single');image=bytearray(0x8000)
    halt=0x7fff if unsupported else 0x3ffe
    setup=rom[0x100:fetch-1]+bytes((0xc3,halt&255,halt>>8))
    image[0x100:0x100+len(setup)]=setup;image[halt]=0x76
    if not unsupported:
        image[0x3fff]=4;image[0x4000:0x4100]=rom[fetch+1:fetch+0x101]
    return bytes(image)


def reference(rom):
    cpu=CPU(Memory(rom))
    for _ in range(500):cpu.step()
    return list(cpu.m.wram[:6]),cpu


CASES=['single','word','cb','jr','jr_z','jr_not','call','call_z','call_not','rst','mixed','ei_halt','ei_nop','late0','late1','late2','late3','late4','late5','late6','late7','late8']


class HaltContextTests(unittest.TestCase):
    def test_reference_hardware_expectations(self):
        expected={'single':[2,0x42],'word':[4,0x21],'cb':[4,0xda],
                  'jr':[1,0x42],'jr_z':[1,0x42],'jr_not':[1,0x42],
                  'call':[1,0x42],'call_z':[1,0x42],'call_not':[1,0x42],
                  'rst':[2,0x42],'mixed':[1,4]}
        for case in CASES:
            with self.subTest(case=case):
                rom,fetch=context_rom(case);actual,cpu=reference(rom)
                self.assertEqual(actual[2],0xa5)
                if case in expected:self.assertEqual(actual[:2],expected[case])
                if case.startswith('ei_'):
                    self.assertEqual(actual[:2],[(fetch-1)&255,(fetch-1)>>8])
                    self.assertEqual(actual[5],1);self.assertFalse(cpu.halt_bug)
                if case.startswith('late'):self.assertEqual(actual[0],1 if int(case[4:])<7 else 2)

    def test_canonical_rom_and_halt_context_survive_profile_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);rom,fetch=context_rom('mixed');source=root/'original.gb';source.write_bytes(rom)
            blocks=compile_trace(source,root/'first',200)
            item=next(b for b in blocks if b['pc']==fetch)
            self.assertEqual(item['bytes'],'3e04');self.assertEqual(item['halt_fetch_bytes'],'3e3e')
            self.assertEqual(item['observed_variants'],[])
            imported=compile_trace(source,root/'merged',2,coverage_profiles=[root/'first/trace-profile.json'])
            new=next(b for b in imported if b['pc']==fetch)
            self.assertEqual(new['halt_fetch_bytes'],'3e3e')
            profile=json.loads((root/'first/trace-profile.json').read_text())
            for replacement in ('3e04','0000'):
                bad=json.loads(json.dumps(profile));next(b for b in bad['blocks'] if b['pc']==fetch)['halt_fetch_bytes']=replacement
                path=root/'invalid.json';path.write_text(json.dumps(bad))
                with self.assertRaises(ValueError):load_coverage_profiles(rom,[path])

    def test_short_trace_statically_closes_both_fetch_context_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);rom,fetch=context_rom('word');source=root/'original.gb';source.write_bytes(rom)
            blocks=compile_trace(source,root/'out',2);by={b['pc']:b for b in blocks}
            self.assertEqual(by[fetch]['halt_fetch_bytes'],'212104')
            self.assertIn(fetch+2,by) # exposed RET NZ byte has its own normal entry

    def test_metadata_does_not_authenticate_arbitrary_rom_or_ram_bytes(self):
        rom,fetch=context_rom('mixed')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            good={'bank':0,'pc':fetch,'bytes':'3e04','hits':1,'halt_fetch_bytes':'3e3e','halt_fetch_hits':1}
            for changes in ({'halt_fetch_hits':-1},{'halt_fetch_hits':True},
                            {'halt_fetch_bytes':'3e05'},{'pc':0xc100}):
                profile={'source_sha256':hashlib.sha256(rom).hexdigest(),'blocks':[{**good,**changes}]}
                path=root/'bad.json';path.write_text(json.dumps(profile))
                with self.assertRaises(ValueError):load_coverage_profiles(rom,[path])

    def test_banked_and_window_edge_reference_results(self):
        for bank,mapper in ((2,0x11),(0,0x19)):
            image=bank_rom(bank,mapper)
            actual,_=reference(image);self.assertEqual(actual[:3],[2,0x42,0xa5])
            with tempfile.TemporaryDirectory() as folder:
                root=Path(folder);source=root/'original.gb';source.write_bytes(image)
                blocks=compile_trace(source,root/'out',200)
                self.assertTrue(any(b['bank']==bank and b['pc']>=0x4800 and b.get('halt_fetch_bytes') for b in blocks))

    def test_writable_context_is_rejected_and_observer_reports_its_reason(self):
        from unittest.mock import patch
        import run_compat_tests as harness
        # Original HRAM program executes HALT with an enabled pending IRQ.
        rom=bytearray(0x8000);code=bytes.fromhex('f3afe04006003e01eaffffe00f3e76e0803e04e0812180ffe9')
        rom[0x100:0x100+len(code)]=code
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'original.gb';source.write_bytes(rom)
            with self.assertRaisesRegex(ValueError,'writable code'):
                compile_trace(source,root/'out',200)
            item={'protocol':'mooneye_fibonacci','native_genesis':{'build_status':'BUILT','artifact':str(root/'unused.md')}}
            output='[$ff0000].w: 0\n[$ff0002].w: ff81\n[$ff0018].l: badb10c0\n[$ff0038].l: 1\n[$ff0081].b: 1\n'
            with patch.object(harness,'_run_in_pty',return_value=(0,output,False)):
                harness.run_native_blastem(item,source,root/'blastem',120,10)
            self.assertEqual(item['native_genesis']['status'],'FAIL')
            self.assertEqual(item['native_genesis']['category'],'missing_native_fetch_context')

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_control_flow_and_timer_phases_match_reference(self):
        from build_recompiled import build
        from run_compat_tests import _run_in_pty,_blastem_values
        for case in CASES:
            with self.subTest(case=case),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);rom,_=context_rom(case);expected,_=reference(rom)
                source=root/'original.gb';source.write_bytes(rom);image=build(source,root/'out',200)
                rc,out,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(image)],
                    'frames 120\np/x [$ff2300].b [$ff2301].b [$ff2302].b [$ff2303].b [$ff2304].b [$ff2305].b [$ff0018].l [$ff0038].l\nquit\n',20)
                self.assertFalse(timed,out);self.assertEqual(rc,0,out)
                v=_blastem_values(out);actual=[v.get(f'FF230{i}.b') for i in range(6)]
                self.assertEqual(actual,expected,out)
                self.assertEqual(v.get('FF0018.l'),0,out);self.assertEqual(v.get('FF0038.l'),0,out)

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_banks_window_edge_and_missing_context_diagnostic(self):
        from build_recompiled import build
        from run_compat_tests import _run_in_pty,_blastem_values
        samples=[('upper',bank_rom(2,0x11)),('mbc5-zero',bank_rom(0,0x19)),
                 ('window-edge',edge_rom()),('unsupported-fetch',edge_rom(True))]
        for case,rom in samples:
            with self.subTest(case=case),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);source=root/'original.gb';source.write_bytes(rom)
                image=build(source,root/'out',2 if case=='unsupported-fetch' else 200)
                rc,out,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(image)],
                    'frames 120\np/x [$ff2300].b [$ff2301].b [$ff2302].b [$ff0018].l [$ff0038].l [$ff0081].b\nquit\n',20)
                self.assertFalse(timed,out);self.assertEqual(rc,0,out);v=_blastem_values(out)
                if case=='unsupported-fetch':
                    self.assertEqual(v.get('FF0018.l'),0xBADB10C0,out)
                    self.assertEqual(v.get('FF0081.b'),1,out)
                else:
                    self.assertEqual([v.get(f'FF230{i}.b') for i in range(3)],reference(rom)[0][:3],out)
                    self.assertEqual(v.get('FF0018.l'),0,out)
                    self.assertEqual(v.get('FF0081.b'),0,out)
