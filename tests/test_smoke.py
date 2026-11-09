import json, os, pathlib, subprocess, sys, tempfile, unittest

ROOT = pathlib.Path(__file__).parents[1]

def constant_far_call_diagnostic_rom(mapper=0x11,target_bank=2,reverse=False):
    """Original B/HL far call; verify callback and restored ROM data mapping."""
    rom=bytearray(0x10000);rom[0x147:0x14A]=bytes([mapper,1,0])
    setup=bytes([0x21,0,0x45,0x06,target_bank]) if reverse else bytes([0x06,target_bank,0x21,0,0x45])
    program=bytes.fromhex('3e01e090')+setup+bytes.fromhex('cd0003fa0046ea01c018fe')
    rom[0x100:0x100+len(program)]=program
    helper=bytes.fromhex('f090f578e090ea0020010e03c5e9c178e090ea0020c9')
    rom[0x300:0x300+len(helper)]=helper
    offset=target_bank*0x4000+0x500;rom[offset:offset+6]=bytes.fromhex('3e42ea00c0c9')
    rom[0x4600]=0x99;rom[0x8600]=0x55
    return bytes(rom)

def large_dispatch_diagnostic_rom():
    """Original NOP stream makes the native dispatcher exceed word-branch range."""
    rom=bytearray(0x8000);rom[0x100:0x103]=bytes.fromhex('c35001')
    rom[0x950:0x957]=bytes.fromhex('3e42ea00c018fe')
    return bytes(rom)

def inline_hl_table_diagnostic_rom(preserve_bc=True):
    """Original inline BC-indexed pointer table; optionally preserve BC."""
    rom=bytearray(0x8000)
    lookup=bytes.fromhex('c58706004f09c12a666fe9' if preserve_bc else '8706004f092a666fe9')
    program=bytes.fromhex('3e01212001')+lookup
    rom[0x100:0x100+len(program)]=program
    rom[0x120:0x126]=bytes.fromhex('40015001ffff')
    rom[0x140:0x147]=bytes.fromhex('3e11ea00c018fe')
    rom[0x150:0x157]=bytes.fromhex('3e42ea00c018fe')
    return bytes(rom)

def rom_only_upper_table_diagnostic_rom():
    """Original fixed-ROM code indexing a table in the fixed upper window."""
    rom=bytearray(inline_hl_table_diagnostic_rom());rom[0x103:0x105]=bytes.fromhex('0042')
    rom[0x4200:0x4206]=rom[0x120:0x126]
    return bytes(rom)

def bitmask_dispatch_diagnostic_rom(mask=1):
    """Original eight-button scan with separate callback/return roots."""
    rom=bytearray(0x8000)
    program=bytes([0x3E,mask])+bytes.fromhex('218001cb2738062323232318f62a5f2a572a666fd5e9')
    rom[0x100:0x100+len(program)]=program
    for index in range(8):
        target=0x200+index*8
        rom[0x180+index*4:0x184+index*4]=bytes([0xC0,1,target&255,target>>8])
        callback=bytes([0x3E,0x42 if index==7 else 0x11])+bytes.fromhex('ea00c0c9')
        rom[target:target+len(callback)]=callback
    rom[0x1C0:0x1C7]=bytes.fromhex('3e99ea01c018fe')
    return bytes(rom)

def input_sweep_diagnostic_rom():
    """Original edge counter calls a WRAM pointer after three separate A presses."""
    rom=bytearray(0x8000)
    # B=count, C=previously held. The callback address is stored in RAM;
    # neither a direct branch nor the ROM pointer-table recognizers seed it.
    code=bytearray(bytes.fromhex('f33e10e00006000e002180017dea10c07cea11c0'))
    loop=len(code);code.extend(bytes.fromhex('f000e601200079a720000e010478fe033800'))
    release_jump=loop+5;held_jump=loop+9;count_jump=loop+17
    code.extend(bytes.fromhex('2110c02a666fe9'))
    released=len(code);code.extend(bytes.fromhex('0e001800'))
    code[release_jump]=released-(release_jump+1)
    code[held_jump]=(loop-(held_jump+1))&255
    code[count_jump]=(loop-(count_jump+1))&255
    code[-1]=(loop-len(code))&255
    rom[0x100:0x100+len(code)]=code
    rom[0x180:0x187]=bytes.fromhex('3e42ea00c018fe')
    return bytes(rom)

def root_bridge_diagnostic_rom():
    """Original branchless latch: Start then A chooses a computed callback."""
    rom=bytearray(0x8000)
    rom[0x100:0x10C]=bytes.fromhex('f3afea00c03e10e000c31001')
    code=bytes.fromhex('f0002fe60847fa00c0b0ea00c0f0002fe60147fa00c00f0f0fa08787878787478780c6406f2601e9')
    rom[0x110:0x110+len(code)]=code
    rom[0x140:0x143]=bytes.fromhex('c31001')
    rom[0x1A0:0x1A7]=bytes.fromhex('3e42ea00c018fe')
    return bytes(rom)

def bank_shadow_diagnostic_rom(use_helper=True):
    """Original HRAM bank shadow and optional fixed-ROM bank setter."""
    rom=bytearray(0x10000);rom[0x147:0x14A]=bytes([1,1,0])
    program=bytes.fromhex('3e02e090cd3001c30041' if use_helper else '3e02e090ea0020c30041')
    rom[0x100:0x100+len(program)]=program
    rom[0x130:0x137]=bytes.fromhex('ea0020ea10c0c9')
    rom[0x8100:0x8107]=bytes.fromhex('3e42ea00c018fe')
    return bytes(rom)

def bank_context_diagnostic_rom():
    """Original two banked calls separated by a bank-preserving WRAM leaf."""
    rom=bytearray(0x10000);rom[0x147:0x14A]=bytes([1,1,0])
    program=bytes.fromhex('3e02ea0020cd0041cd004218fe')
    rom[0x100:0x100+len(program)]=program
    rom[0x8100:0x8105]=bytes.fromhex('2102c034c9')
    rom[0x8200:0x8207]=bytes.fromhex('3e42ea00c018fe')
    return bytes(rom)

def long_banked_table_diagnostic_rom(index=65):
    """Original banked lookup whose selected entry lies past the old64 limit."""
    rom=bytearray(banked_table_diagnostic_rom());rom[0x101]=index
    rom[0x4101:0x4103]=bytes.fromhex('0046')
    table=bytes.fromhex('010043')*index+bytes.fromhex('020044ffffff')
    rom[0x4600:0x4600+len(table)]=table
    return bytes(rom)

def banked_table_diagnostic_rom():
    """Original indexed bank/lo/hi table with distinct banked callbacks."""
    rom=bytearray(0x10000);rom[0x147:0x14A]=bytes([0x11,1,0])
    program=bytes.fromhex('3e01ea10c03e01ea0020cd0041fa11c0ea0020e9')
    rom[0x100:0x100+len(program)]=program
    helper=bytes.fromhex('210042110000fa10c05f87835f30011419545d1aea11c0131a6f131a67c9')
    rom[0x4100:0x4100+len(helper)]=helper
    rom[0x4200:0x4209]=bytes.fromhex('010043020044ffffff')
    rom[0x4300:0x4307]=bytes.fromhex('3e11ea00c018fe')
    rom[0x8400:0x8407]=bytes.fromhex('3e42ea00c018fe')
    return bytes(rom)

def constant_bank_call_diagnostic_rom():
    """Original fixed-window mapper store and untraced banked callback."""
    rom=bytearray(0x10000);rom[0x147:0x14A]=bytes([1,1,0])
    rom[0x100:0x10D]=bytes.fromhex('3e02ea0020cd0041ea00c018fe')
    rom[0x8100:0x8103]=bytes.fromhex('3e42c9')
    return bytes(rom)

def hl_dispatch_diagnostic_rom():
    """Original one-based table lookup across a forward jump and BC/DE setup."""
    rom=bytearray(0x8000)
    rom[0x100:0x118]=bytes.fromhex('3e02212001180721240100000000cd30011100c00110c0e9')
    rom[0x120:0x126]=bytes.fromhex('40015001ffff')
    rom[0x130:0x13D]=bytes.fromhex('3dcb274f0600094e23466069c9')
    rom[0x140:0x142]=bytes([0x18,0xFE])
    rom[0x150:0x157]=bytes.fromhex('3e42ea00c018fe')
    return bytes(rom)

def controller_diagnostic_rom(aggregate=False):
    """Original tight JOYP scan, recording buttons/directions/both rows."""
    rom=bytearray(0x8000)
    program=bytearray([0xF3])
    if aggregate:program.extend(bytes.fromhex('3effea10c0ea12c0ea14c0'))
    loop=len(program)
    for index,select in enumerate((0x10,0x20,0)):
        program.extend(bytes([0x3E,select,0xE0,0,0xF0,0,0xEA,index,0xC0]))
        if aggregate:
            program.extend(bytes([0x21,0x10+index*2,0xC0,0xA6,0x77,0xFA,index,0xC0,0x23,0xB6,0x77]))
    program.extend(bytes([0x18,(-(len(program)-loop+2))&255]))
    rom[0x100:0x103]=bytes.fromhex('c35001')
    rom[0x150:0x150+len(program)]=program
    return bytes(rom)

def stat_diagnostic_rom():
    """Original HBlank IRQ/HALT diagnostic; no third-party ROM data."""
    rom=bytearray(0x8000)
    rom[0x48:0x4E]=bytes.fromhex('3e77ea01c0d9')
    program=bytes.fromhex('f33e80e0403e08e041af e00f3e02eaffff fb00763e42ea00c018fe')
    rom[0x100:0x100+len(program)]=program
    return bytes(rom)

def window_diagnostic_rom(wy=0):
    """Original full-window test: BG tile 0, window tile 1, nonzero scroll."""
    rom=bytearray(0x8000)
    program=bytes.fromhex('f3afe0403e01ea009c3effea1080afea1180')+bytes([0x3E,wy,0xE0,0x4A])+bytes.fromhex('3e07e04b3e05e042e0433ee4e0473ef1e04018fe')
    rom[0x100:0x100+len(program)]=program
    return bytes(rom)

def stat_poll_diagnostic_rom():
    """Original mode-zero polling test with VBlank enabled and IME set."""
    rom=bytearray(0x8000);rom[0x40]=0xD9
    program=bytes.fromhex('f331feff3e80e0403e01eafffffb00f041e60320fa3e42ea00c018fe')
    rom[0x100:0x100+len(program)]=program
    return bytes(rom)

def memory_scan_diagnostic_rom():
    """A short ROM scan must finish before the first VBlank interrupt."""
    rom=bytearray(0x8000)
    handler=bytes.fromhex('f5fa01c03cea01c0f1d9');rom[0x40:0x40+len(handler)]=handler
    program=bytes.fromhex('f331feff3e80e0403e01eafffffb002100202afe5020fbf33e42ea00c018fe')
    rom[0x100:0x100+len(program)]=program;rom[0x2000:0x2010]=bytes([1]*15+[0x50])
    return bytes(rom)

def rst_dispatch_diagnostic_rom():
    """Original trampoline/16-bit-index dispatch test with two inline targets."""
    rom=bytearray([0xFF])*0x8000;rom[0x147:0x14A]=bytes(3)
    rom[:3]=bytes([0xC3,0x30,0x01])
    rom[0x130:0x13F]=bytes.fromhex('5f1600cb23cb12e1195e2356d5e1e9')
    rom[0x100:0x109]=bytes.fromhex('3e01c740015001ffff')
    rom[0x140:0x142]=bytes([0x18,0xFE])
    rom[0x150:0x157]=bytes.fromhex('3e42ea00c018fe')
    return bytes(rom)

def bank_switch_diagnostic_rom(mapper=1,bank=2):
    """A mapper store changes the very next upper-window instruction."""
    rom=bytearray(0x10000);rom[0x147:0x14A]=bytes([mapper,1,0])
    rom[0x100:0x103]=bytes.fromhex('c30040')
    rom[0x4000:0x4005]=bytes([0x3E,bank,0xEA,0,0x20])
    rom[0x4005:0x400C]=bytes.fromhex('3e11ea00c018fe')
    offset=bank*0x4000+5
    rom[offset:offset+7]=bytes.fromhex('3e42ea00c018fe')
    return bytes(rom)

def banked_rst_dispatch_diagnostic_rom():
    """RST table entries tail-jump into the observed caller ROM bank."""
    rom=bytearray(rst_dispatch_diagnostic_rom());rom.extend(bytes([0xFF])*0x8000)
    rom[0x147:0x14A]=bytes([1,1,0])
    rom[0x140:0x143]=bytes.fromhex('c30040')
    rom[0x150:0x153]=bytes.fromhex('c30041')
    rom[0x4000:0x4002]=bytes([0x18,0xFE])
    rom[0x4100:0x4107]=bytes.fromhex('3e42ea00c018fe')
    return bytes(rom)

class SmokeTest(unittest.TestCase):
    def test_constant_far_call_closure_and_bank_restore(self):
        import trace_recompiler as trace
        from gb_cpu import CPU,Memory
        for mapper,bank,reverse in ((0x11,2,False),(0x11,2,True),(0,1,False)):
            with self.subTest(mapper=mapper,reverse=reverse),tempfile.TemporaryDirectory() as d:
                rom=constant_far_call_diagnostic_rom(mapper,bank,reverse);m=Memory(rom);c=CPU(m)
                for _ in range(80):c.step()
                self.assertEqual(m.wram[:2],bytes([0x42,0x99]));self.assertEqual(m.rom_bank,1)
                root=pathlib.Path(d);source=root/'far-call.gb';source.write_bytes(rom)
                blocks=trace.compile_trace(source,root/'out',2)
                self.assertIn((bank,0x4500),{(b['bank'],b['pc']) for b in blocks})
                self.assertIn((0,0x30E),{(b['bank'],b['pc']) for b in blocks})
                self.assertEqual(json.loads((root/'out'/'trace-profile.json').read_text())['constant_far_call_targets'],1)

    def test_constant_far_call_rejects_unverified_trampolines(self):
        from trace_recompiler import constant_far_call_targets
        original=constant_far_call_diagnostic_rom()
        self.assertEqual(constant_far_call_targets(original,0,0x104),[(2,0x4500)])
        for address,value in ((0x301,0x04),(0x305,0x91),(0x30A,0x0F),(0x30D,0xE1)):
            rom=bytearray(original);rom[address]=value
            self.assertEqual(constant_far_call_targets(rom,0,0x104),[])
        rom=bytearray(original);rom[0x308]=rom[0x314]=0x40
        self.assertEqual(constant_far_call_targets(rom,0,0x104),[])
        self.assertEqual(constant_far_call_targets(original,0,0x3FFC),[])

    def test_constant_far_call_aliases_and_bank_identity(self):
        from trace_recompiler import constant_far_call_targets
        original=constant_far_call_diagnostic_rom();rom=bytearray(original)
        rom[0xC104:0xC10C]=original[0x104:0x10C]
        self.assertEqual(constant_far_call_targets(rom,3,0x4104),[(2,0x4500)])
        self.assertEqual(constant_far_call_targets(rom,1,0x4104),[])
        helper=bytearray(original[0x300:0x316]);helper[10:12]=bytes.fromhex('2e03')
        rom[0x320:0x336]=helper;rom[0x300:0x303]=bytes.fromhex('c32003')
        self.assertEqual(constant_far_call_targets(rom,0,0x104),[(2,0x4500)])
        rom[0x320:0x323]=bytes.fromhex('c30003')
        self.assertEqual(constant_far_call_targets(rom,0,0x104),[])
        self.assertEqual(constant_far_call_targets(constant_far_call_diagnostic_rom(0x19,0),0,0x104),[(0,0x4500)])

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_constant_far_call_bank_restore(self):
        from build_recompiled import build
        from run_compat_tests import _run_in_pty,_blastem_values
        for mapper,bank in ((0x11,2),(0x19,0),(0,1)):
            with self.subTest(mapper=mapper,bank=bank),tempfile.TemporaryDirectory() as d:
                root=pathlib.Path(d);source=root/'original.gb';source.write_bytes(constant_far_call_diagnostic_rom(mapper,bank))
                build(source,root/'out',2)
                commands='frames 600\np/x [$ff2300].b [$ff2301].b [$ff001e].w [$ff0018].l\nquit\n'
                code,output,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(root/'out'/'recompiled.md')],commands,30)
                self.assertFalse(timed,output);self.assertEqual(code,0,output)
                values=_blastem_values(output)
                self.assertEqual([values.get(a) for a in ('FF2300.b','FF2301.b','FF001E.w','FF0018.l')],[0x42,0x99,1,0],output)

    def test_banked_table_discovers_indices_beyond_64(self):
        import trace_recompiler as trace
        from gb_cpu import CPU,Memory
        for index in (65,127):
            with self.subTest(index=index),tempfile.TemporaryDirectory() as d:
                rom=long_banked_table_diagnostic_rom(index);m=Memory(rom);c=CPU(m)
                for _ in range(70):c.step()
                self.assertEqual(m.wram[0],0x42)
                root=pathlib.Path(d);source=root/'long-table.gb';source.write_bytes(rom)
                blocks=trace.compile_trace(source,root/'out',2)
                self.assertIn((2,0x4400),{(b['bank'],b['pc']) for b in blocks})
                report=json.loads((root/'out'/'trace-profile.json').read_text())['banked_pointer_tables'][0]
                self.assertEqual(report['entries'],index+1)
                self.assertEqual(report['stop_reason'],'entry_limit' if index==127 else 'non_code_pointer')

    def test_banked_table_reports_budget_and_retains_hard_bound(self):
        from trace_recompiler import banked_pointer_table_targets
        rom=long_banked_table_diagnostic_rom(127);diagnostic={}
        targets=banked_pointer_table_targets(rom,1,0x4100,64,diagnostic)
        self.assertNotIn((2,0x4400),targets)
        self.assertEqual((diagnostic['entries'],diagnostic['stop_reason']),(64,'entry_limit'))
        diagnostic={}
        targets=banked_pointer_table_targets(rom,1,0x4100,1000000,diagnostic)
        self.assertIn((2,0x4400),targets)
        self.assertEqual(diagnostic['entry_limit'],128)

    def test_inline_hl_table_closure_and_validation(self):
        import trace_recompiler as trace
        from gb_cpu import CPU,Memory
        for preserve_bc in (False,True):
            with self.subTest(preserve_bc=preserve_bc),tempfile.TemporaryDirectory() as d:
                rom=inline_hl_table_diagnostic_rom(preserve_bc);m=Memory(rom);c=CPU(m)
                for _ in range(40):c.step()
                self.assertEqual(m.wram[0],0x42)
                root=pathlib.Path(d);source=root/'inline-table.gb';source.write_bytes(rom)
                blocks=trace.compile_trace(source,root/'out',2)
                self.assertIn((0,0x150),{(b['bank'],b['pc']) for b in blocks})
                altered=bytearray(rom);altered[0x105]=0xF3
                self.assertIsNone(trace.hl_dispatch_table(altered,0,0x102))

    def test_rom_only_upper_table_needs_no_bank_inference(self):
        import trace_recompiler as trace
        from gb_cpu import CPU,Memory
        rom=rom_only_upper_table_diagnostic_rom();m=Memory(rom);c=CPU(m)
        for _ in range(40):c.step()
        self.assertEqual(m.wram[0],0x42)
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);source=root/'upper-table.gb';source.write_bytes(rom)
            blocks=trace.compile_trace(source,root/'out',2)
            self.assertIn((0,0x150),{(b['bank'],b['pc']) for b in blocks})

    def test_bitmask_dispatch_closes_callback_and_return(self):
        import trace_recompiler as trace
        from gb_cpu import CPU,Memory
        for mask,expected in ((1,0x42),(0x80,0x11),(0x81,0x11)):
            rom=bitmask_dispatch_diagnostic_rom(mask);m=Memory(rom);c=CPU(m)
            for _ in range(100):c.step()
            self.assertEqual(list(m.wram[:2]),[expected,0x99])
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);source=root/'bitmask.gb';source.write_bytes(rom)
            blocks=trace.compile_trace(source,root/'out',2)
            keys={(b['bank'],b['pc']) for b in blocks}
            self.assertTrue({(0,0x1C0),(0,0x238)}<=keys)
            report=json.loads((root/'out'/'trace-profile.json').read_text())
            self.assertEqual(report['bitmask_dispatch_targets'],9)

    def test_bitmask_dispatch_rejects_changed_loop_and_unknown_bank(self):
        from trace_recompiler import bitmask_dispatch_targets
        rom=bytearray(bitmask_dispatch_diagnostic_rom())
        for offset in (0x106,0x10E,0x117):
            altered=bytearray(rom);altered[offset]^=1
            self.assertEqual(bitmask_dispatch_targets(altered,0,0x102),[])
        altered=bytearray(rom);altered[0x180:0x182]=b'\xff\xff'
        self.assertEqual(bitmask_dispatch_targets(altered,0,0x102),[])
        # A ninth valid pair must not widen an eight-bit dispatch table.
        altered=bytearray(rom);altered[0x1A0:0x1A4]=bytes.fromhex('c0010003')
        self.assertNotIn((0,0x300),bitmask_dispatch_targets(altered,0,0x102))
        rom[0x103:0x105]=bytes.fromhex('0042');rom[0x4200:0x4220]=rom[0x180:0x1A0]
        self.assertEqual(len(bitmask_dispatch_targets(rom,0,0x102)),9)
        rom[0x147]=1
        self.assertEqual(bitmask_dispatch_targets(rom,0,0x102),[])

    def test_constant_bank_shadow_and_setter_closure(self):
        import trace_recompiler as trace
        from gb_cpu import CPU,Memory
        for use_helper in (False,True):
            with self.subTest(use_helper=use_helper),tempfile.TemporaryDirectory() as d:
                rom=bank_shadow_diagnostic_rom(use_helper);m=Memory(rom);c=CPU(m)
                for _ in range(30):c.step()
                self.assertEqual(m.wram[0],0x42)
                root=pathlib.Path(d);source=root/'bank-shadow.gb';source.write_bytes(rom)
                blocks=trace.compile_trace(source,root/'out',2)
                self.assertIn((2,0x4100),{(b['bank'],b['pc']) for b in blocks})

    def test_constant_bank_setter_rejects_unknown_effects(self):
        from trace_recompiler import constant_bank_call_targets
        original=bank_shadow_diagnostic_rom()
        for address,data in ((0x103,b'\x46'),(0x133,b'\xaf'),(0x130,bytes.fromhex('cd4001')),
                             (0x136,b'\xe9')):
            rom=bytearray(original);rom[address:address+len(data)]=data
            self.assertEqual(constant_bank_call_targets(rom,0x100),[])
        rom=bytearray(original);rom[0x147]=0x19;rom[0x132]=0x30
        self.assertEqual(constant_bank_call_targets(rom,0x100),[])

    def test_oversized_native_output_preserves_previous_rom(self):
        from unittest.mock import patch
        import build_recompiled as compiler
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);source=root/'original.gb';source.write_bytes(controller_diagnostic_rom())
            assembler=root/'assembler';assembler.touch()
            out=root/'out';out.mkdir();binary=out/'recompiled.md';binary.write_bytes(b'previous known build')
            def assemble(command,**kwargs):
                pathlib.Path(command[-1]).write_bytes(bytes(0x400002))
            with patch.object(compiler,'compile_trace',return_value=[{'family':'NOP','native_lowered':True}]),patch.object(compiler.subprocess,'run',side_effect=assemble):
                with self.assertRaisesRegex(ValueError,'4 MiB'):
                    compiler.build(source,out,2,assembler=assembler)
            self.assertEqual(binary.read_bytes(),b'previous known build')

    def test_profiled_hot_chain_quota_retains_every_native_entry(self):
        import trace_recompiler as trace
        rom=bytearray(0x8000);rom[0x100:0x104]=bytes.fromhex('040d18fc')
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);source=root/'quota.gb';source.write_bytes(rom)
            blocks=trace.compile_trace(source,root/'out',15)
            for block,hits in zip(blocks,(1,100,10)):block['hits']=hits
            trace.emit_native_blocks(blocks,root/'out')
            original=(root/'out'/'translated_trace.s').read_text()
            trace.emit_native_blocks(blocks,root/'out',max_hot_chains=3)
            self.assertEqual(original,(root/'out'/'translated_trace.s').read_text())
            trace.emit_native_blocks(blocks,root/'out',max_hot_chains=1)
            text=(root/'out'/'translated_trace.s').read_text()
            report=json.loads((root/'out'/'native-codegen-report.json').read_text())
            self.assertEqual((report['blocks'],report['hot_chain_targets'],report['compact_chain_targets']),(3,1,2))
            hot=text.split('gb_chain_B000_0101:\n',1)[1].split('\n\ngb_chain_',1)[0]
            self.assertIn('tst.b gb_force_tick',hot)
            for pc in (0x100,0x101,0x102):self.assertIn(f'L_gb_B000_{pc:04X}:',text)
            trace.emit_native_blocks(blocks,root/'out',max_hot_chains=1)
            self.assertEqual(text,(root/'out'/'translated_trace.s').read_text())
            with self.assertRaises(ValueError):trace.emit_native_blocks(blocks,root/'out',max_hot_chains=-1)

    def test_native_layout_retries_without_retracing(self):
        from unittest.mock import patch
        import build_recompiled as compiler
        rom=bytearray(0x8000);rom[0x100:0x104]=bytes.fromhex('040d18fc')
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);source=root/'quota.gb';source.write_bytes(rom)
            assembler=root/'assembler';assembler.touch();calls=[]
            def assemble(command,**kwargs):
                calls.append(command)
                pathlib.Path(command[-1]).write_bytes(bytes(0x400002 if len(calls)==1 else 0x80000))
            discover=compiler.compile_trace
            with patch.object(compiler,'compile_trace',wraps=discover) as traced,patch.object(compiler.subprocess,'run',side_effect=assemble):
                binary=compiler.build(source,root/'out',15,assembler=assembler)
            self.assertEqual(traced.call_count,1)
            self.assertEqual(len(calls),2)
            self.assertEqual(binary.stat().st_size,0x80000)
            report=json.loads((root/'out'/'build-report.json').read_text())
            self.assertEqual([a['hot_chain_targets'] for a in report['native_layout_attempts']],[3,3])
            self.assertEqual([a['block_catalog_included'] for a in report['native_layout_attempts']],[True,False])
            self.assertEqual(report['blocks'],3)

    def test_catalog_omission_preserves_native_code_and_dispatch(self):
        import trace_recompiler as trace
        rom=bytearray(0x8000);rom[0x100:0x104]=bytes.fromhex('040d18fc')
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);source=root/'catalog.gb';source.write_bytes(rom)
            blocks=trace.compile_trace(source,root/'out',15)
            original=(root/'out'/'translated_trace.s').read_text()
            trace.emit_native_blocks(blocks,root/'out',include_block_table=False)
            omitted=(root/'out'/'translated_trace.s').read_text()
            self.assertEqual(original.split('gb_compiled_block_table:')[0],omitted.split('gb_compiled_block_table:')[0])
            self.assertEqual(omitted.split('gb_compiled_block_table:')[1],'\n\tdc.w $FFFF,$FFFF\n\tdc.l 0')
            report=json.loads((root/'out'/'native-codegen-report.json').read_text())
            self.assertFalse(report['block_catalog_included'])
            self.assertEqual(report['block_catalog_bytes'],8)
            self.assertEqual(report['blocks'],len(blocks))

    def test_require_catalog_keeps_previous_quota_retry_behavior(self):
        from unittest.mock import patch
        import build_recompiled as compiler
        rom=bytearray(0x8000);rom[0x100:0x104]=bytes.fromhex('040d18fc')
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);source=root/'catalog.gb';source.write_bytes(rom)
            assembler=root/'assembler';assembler.touch();calls=[]
            def assemble(command,**kwargs):
                calls.append(command)
                pathlib.Path(command[-1]).write_bytes(bytes(0x400002 if len(calls)==1 else 0x80000))
            with patch.object(compiler.subprocess,'run',side_effect=assemble):
                compiler.build(source,root/'out',15,assembler=assembler,keep_rom_catalog=True)
            report=json.loads((root/'out'/'build-report.json').read_text())
            self.assertEqual([a['hot_chain_targets'] for a in report['native_layout_attempts']],[3,1])
            self.assertEqual([a['block_catalog_included'] for a in report['native_layout_attempts']],[True,True])

    def test_native_layout_all_compact_failure_preserves_rom(self):
        from unittest.mock import patch
        import build_recompiled as compiler
        rom=bytearray(0x8000);rom[0x100:0x104]=bytes.fromhex('040d18fc')
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);source=root/'quota.gb';source.write_bytes(rom)
            assembler=root/'assembler';assembler.touch();out=root/'out';out.mkdir()
            binary=out/'recompiled.md';binary.write_bytes(b'preserved');calls=[]
            def assemble(command,**kwargs):
                calls.append(command);pathlib.Path(command[-1]).write_bytes(bytes(0x400002))
            with patch.object(compiler.subprocess,'run',side_effect=assemble):
                with self.assertRaisesRegex(ValueError,'4 MiB'):compiler.build(source,out,15,assembler=assembler)
            self.assertEqual(len(calls),4) #catalog omission, then3 ->1 ->0 scheduler stubs
            self.assertEqual(binary.read_bytes(),b'preserved')

    def test_bank_context_closure_discovers_following_call(self):
        import trace_recompiler as trace
        from gb_cpu import CPU,Memory
        rom=bank_context_diagnostic_rom();m=Memory(rom);c=CPU(m)
        for _ in range(40):c.step()
        self.assertEqual(m.wram[0],0x42);self.assertEqual(m.wram[2],1)
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);source=root/'context.gb';source.write_bytes(rom)
            blocks=trace.compile_trace(source,root/'out',2)
            self.assertIn((2,0x4200),{(b['bank'],b['pc']) for b in blocks})
            self.assertEqual(json.loads((root/'out'/'trace-profile.json').read_text())['bank_context_targets'],2)

    def test_banked_table_closure_discovers_untraced_callback(self):
        import trace_recompiler as trace
        from gb_cpu import CPU,Memory
        rom=banked_table_diagnostic_rom();m=Memory(rom);c=CPU(m)
        for _ in range(70):c.step()
        self.assertEqual(m.wram[0],0x42)
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);source=root/'far-table.gb';source.write_bytes(rom)
            blocks=trace.compile_trace(source,root/'out',2)
            self.assertIn((2,0x4400),{(b['bank'],b['pc']) for b in blocks})
            self.assertEqual(json.loads((root/'out'/'trace-profile.json').read_text())['banked_pointer_table_targets'],2)

    def test_banked_table_rejects_unverified_code_and_io_state(self):
        from trace_recompiler import banked_pointer_table_targets
        original=banked_table_diagnostic_rom()
        for address,replacement in ((0x4109,b'\x00'),(0x4107,bytes.fromhex('00ff')),(0x4115,bytes.fromhex('0020'))):
            rom=bytearray(original);rom[address:address+len(replacement)]=replacement
            self.assertEqual(banked_pointer_table_targets(rom,1,0x4100),[])
        rom=bytearray(original);rom[0x4204:0x4206]=bytes.fromhex('0080')
        self.assertEqual(banked_pointer_table_targets(rom,1,0x4100),[])

    def test_banked_table_respects_banks_limits_and_windows(self):
        from trace_recompiler import banked_pointer_table_targets
        original=banked_table_diagnostic_rom()
        self.assertEqual(banked_pointer_table_targets(original,1,0x4100),[(1,0x4300),(2,0x4400)])
        self.assertEqual(banked_pointer_table_targets(original,2,0x4100),[])
        self.assertEqual(banked_pointer_table_targets(original,1,0x4100,1),[])
        rom=bytearray(original);rom[0x4101:0x4103]=bytes.fromhex('fe7f')
        self.assertEqual(banked_pointer_table_targets(rom,1,0x4100),[])
        rom=bytearray(original);rom[0x100:0x11E]=original[0x4100:0x411E]
        self.assertEqual(banked_pointer_table_targets(rom,0,0x100),[])

    def test_banked_table_mapper_and_fixed_target_validation(self):
        from trace_recompiler import banked_pointer_table_targets
        rom=bytearray(banked_table_diagnostic_rom());rom[0x147]=0x19
        rom[0x4200:0x4203]=bytes.fromhex('000045');rom[0x500]=0xC9
        self.assertEqual(banked_pointer_table_targets(rom,1,0x4100),[(0,0x4500),(2,0x4400)])
        rom[0x147]=0x11;rom[0x4200:0x4203]=bytes.fromhex('800045')
        self.assertEqual(banked_pointer_table_targets(rom,1,0x4100),[(1,0x4500),(2,0x4400)])
        rom[0x4200:0x4203]=bytes.fromhex('010003')
        self.assertEqual(banked_pointer_table_targets(rom,1,0x4100),[(0,0x300),(2,0x4400)])
        rom[0x147]=0
        self.assertEqual(banked_pointer_table_targets(rom,1,0x4100),[])

    def test_constant_bank_call_closure(self):
        import trace_recompiler as trace
        from gb_cpu import CPU,Memory
        rom=constant_bank_call_diagnostic_rom();m=Memory(rom);c=CPU(m)
        for _ in range(30):c.step()
        self.assertEqual(m.wram[0],0x42)
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);source=root/'bank-call.gb';source.write_bytes(rom)
            blocks=trace.compile_trace(source,root/'out',2)
            self.assertIn((2,0x4100),{(b['bank'],b['pc']) for b in blocks})
            self.assertEqual(json.loads((root/'out'/'trace-profile.json').read_text())['constant_bank_call_targets'],1)

    def test_constant_bank_call_mapper_candidates(self):
        from trace_recompiler import constant_bank_call_targets
        rom=bytearray(0x200000);rom[:0x10000]=constant_bank_call_diagnostic_rom()
        self.assertEqual(constant_bank_call_targets(rom,0x100),[(b,0x4100) for b in (2,34,66,98)])
        rom[0x101]=0
        self.assertEqual(constant_bank_call_targets(rom,0x100),[(b,0x4100) for b in (1,33,65,97)])
        rom[0x147]=0x13
        self.assertEqual(constant_bank_call_targets(rom,0x100),[(1,0x4100)])
        rom.extend(bytes(0x600000));rom[0x147]=0x19
        self.assertEqual(constant_bank_call_targets(rom,0x100),[(0,0x4100),(256,0x4100)])

    def test_constant_bank_call_rejects_ambiguous_stores(self):
        from trace_recompiler import constant_bank_call_targets
        original=constant_bank_call_diagnostic_rom()
        for address,value in ((0x104,0x00),(0x104,0x40),(0x104,0xC0),(0x105,0xC4),(0x107,0x80)):
            rom=bytearray(original);rom[address]=value
            self.assertEqual(constant_bank_call_targets(rom,0x100),[])
        rom=bytearray(original);rom[0x147]=0x19;rom[0x104]=0x30
        self.assertEqual(constant_bank_call_targets(rom,0x100),[])
        self.assertEqual(constant_bank_call_targets(original,0x4000),[])
        self.assertEqual(constant_bank_call_targets(original,0x3FF9),[])

    def test_hl_dispatch_through_jump_and_register_setup(self):
        import trace_recompiler as trace
        from gb_cpu import CPU,Memory
        rom=hl_dispatch_diagnostic_rom();m=Memory(rom);c=CPU(m)
        for _ in range(60):c.step()
        self.assertEqual(m.wram[0],0x42)
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);source=root/'dispatch.gb';source.write_bytes(rom)
            blocks=trace.compile_trace(source,root/'out',2)
            self.assertIn((0,0x150),{(b['bank'],b['pc']) for b in blocks})
            report=json.loads((root/'out'/'trace-profile.json').read_text())
            self.assertEqual(report['hl_pointer_table_targets'],2)

    def test_hl_dispatch_rejects_unknown_helpers_hl_writes_and_backward_jumps(self):
        from trace_recompiler import hl_dispatch_table
        original=hl_dispatch_diagnostic_rom()
        self.assertEqual(hl_dispatch_table(original,0,0x102),0x120)
        for address,replacement in ((0x130,bytes([0x77])),(0x111,bytes([0x21])),(0x106,bytes([0xFE]))):
            rom=bytearray(original);rom[address:address+len(replacement)]=replacement
            self.assertIsNone(hl_dispatch_table(rom,0,0x102))

    def test_hl_dispatch_uses_selected_rom_bank(self):
        from trace_recompiler import hl_dispatch_table
        original=hl_dispatch_diagnostic_rom();rom=bytearray(0x10000)
        rom[0x147:0x14A]=bytes([1,1,0])
        rom[0x4100:0x4118]=original[0x100:0x118]
        rom[0x4104]=0x41;rom[0x4110]=0x41
        rom[0x4130:0x413D]=original[0x130:0x13D]
        self.assertEqual(hl_dispatch_table(rom,1,0x4102),0x4120)
        self.assertIsNone(hl_dispatch_table(rom,2,0x4102))
        rom[0x100:0x118]=original[0x100:0x118]
        rom[0x110]=0x41
        self.assertIsNone(hl_dispatch_table(rom,0,0x102))
    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_compact_scheduler_irq_and_mapper_changes(self):
        import build_recompiled as compiler
        from trace_recompiler import emit_native_blocks
        from run_compat_tests import _run_in_pty,_blastem_values
        from unittest.mock import patch
        discover=compiler.compile_trace
        def force_compact(*args,**kwargs):
            blocks=discover(*args,**kwargs)
            # Exercise the compact edges even for paths the reference ran.
            emit_native_blocks(blocks,args[1],dispatch_format='paged',max_hot_chains=2 if name=='mixed-irq' else 0);return blocks
        for name,fixture,expected in (('irq',stat_diagnostic_rom,[0x42,0x77,0]),
                                      ('mixed-irq',stat_diagnostic_rom,[0x42,0x77,0]),
                                      ('mapper',bank_switch_diagnostic_rom,[0x42,0,0]),
                                      ('mbc5-zero',lambda:bank_switch_diagnostic_rom(0x19,0),[0x42,0,0])):
            with self.subTest(name=name),tempfile.TemporaryDirectory() as d:
                root=pathlib.Path(d);source=root/'original.gb';source.write_bytes(fixture())
                with patch.object(compiler,'compile_trace',side_effect=force_compact):
                    compiler.build(source,root/'out',500)
                commands='frames 600\np/x [$ff2300].b [$ff2301].b [$ff0018].l\nquit\n'
                code,output,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(root/'out'/'recompiled.md')],commands,30)
                self.assertFalse(timed,output);self.assertEqual(code,0,output)
                values=_blastem_values(output)
                self.assertEqual([values.get(a) for a in ('FF2300.b','FF2301.b','FF0018.l')],expected,output)

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_dispatch_missing_slots_pages_and_banks(self):
        import build_recompiled as compiler
        from trace_recompiler import emit_native_blocks
        from unittest.mock import patch
        from run_compat_tests import _run_in_pty,_blastem_values
        discover=compiler.compile_trace
        def force_pages(*args,**kwargs):
            blocks=discover(*args,**kwargs);emit_native_blocks(blocks,args[1],dispatch_format='paged');return blocks
        cases=(('slot','218001e9',0,0x180),('page','21b6ffe9',0,0xFFB6),
               ('bank-limit','3e03ea0020210041e9',3,0x4100),
               ('bank-hole','3e02ea0020cd00413e01ea0020210041e9',1,0x4100))
        for name,program,bank,pc in cases:
            with self.subTest(name=name),tempfile.TemporaryDirectory() as d:
                root=pathlib.Path(d);rom=bytearray(0x10000)
                rom[0x147:0x14A]=bytes([1,1,0]);rom[0x8100]=0xC9
                raw=bytes.fromhex(program);rom[0x100:0x100+len(raw)]=raw
                source=root/'original.gb';source.write_bytes(rom)
                with patch.object(compiler,'compile_trace',side_effect=force_pages):compiler.build(source,root/'out',2)
                commands='frames 600\np/x [$ff0000].w [$ff0002].w [$ff0018].l [$ff0038].l\nquit\n'
                code,output,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(root/'out'/'recompiled.md')],commands,30)
                self.assertFalse(timed,output);self.assertEqual(code,0,output)
                values=_blastem_values(output)
                self.assertEqual([values.get(a) for a in ('FF0000.w','FF0002.w','FF0018.l','FF0038.l')],
                                 [bank,pc,0xBADB10C0,1],output)

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_static_dispatch_discovery(self):
        from build_recompiled import build
        from run_compat_tests import _run_in_pty,_blastem_values
        for name,fixture in (('hl-table',hl_dispatch_diagnostic_rom),('bank-call',constant_bank_call_diagnostic_rom),('bank-table',banked_table_diagnostic_rom),('bank-context',bank_context_diagnostic_rom),('bank-shadow',bank_shadow_diagnostic_rom),('inline-hl',inline_hl_table_diagnostic_rom),('upper-rom-table',rom_only_upper_table_diagnostic_rom),('bitmask',bitmask_dispatch_diagnostic_rom),('input-sweep',input_sweep_diagnostic_rom),('root-bridge',root_bridge_diagnostic_rom),('large-static',large_dispatch_diagnostic_rom),('long-table',long_banked_table_diagnostic_rom),('last-table-entry',lambda:long_banked_table_diagnostic_rom(127))):
            with self.subTest(name=name),tempfile.TemporaryDirectory() as d:
                root=pathlib.Path(d);source=root/'original.gb';source.write_bytes(fixture())
                options=dict(auto_inputs=True,input_max_branches=1,input_max_steps=600_000,input_sweep_steps=600_000,input_hold_frames=1) if name=='input-sweep' else {}
                if name=='root-bridge':options=dict(auto_inputs=True,input_max_branches=192,input_max_depth=2,input_branch_steps=12000,input_max_steps=2_304_000,input_hold_frames=1,input_snapshot_interval_frames=1,input_max_snapshots=8)
                build(source,root/'out',500 if name=='root-bridge' else 2,**options)
                commands='frames 600\np/x [$ff2300].b [$ff2301].b [$ff0018].l\nquit\n'
                if name in ('input-sweep','root-bridge'):
                    # Wait for live input: discovery pulses are never playback.
                    buttons=('start','b') if name=='root-bridge' else ('b',)*3
                    pulses=''.join(f'binddown "gamepads.1.{button}"\nframes 10\nbindup "gamepads.1.{button}"\nframes 10\n' for button in buttons)
                    commands=('frames 600\np/x [$ff2300].b\n'+pulses+
                        'frames 30\np/x [$ff2300].b [$ff2301].b [$ff0018].l\nquit\n')
                code,output,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(root/'out'/'recompiled.md')],commands,30)
                values=_blastem_values(output)
                self.assertFalse(timed,output);self.assertEqual(code,0,output)
                self.assertEqual([values.get(a) for a in ('FF2300.b','FF0018.l')],[0x42,0],output)
                if name=='bitmask':self.assertEqual(values.get('FF2301.b'),0x99,output)
                if name in ('input-sweep','root-bridge'):self.assertRegex(output,r'(?i)\[\$ff2300\]\.b:\s+0\b')

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_joypad_selected_rows(self):
        from build_recompiled import build
        from run_compat_tests import _run_in_pty,_blastem_values
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);source=root/'original.gb'
            source.write_bytes(controller_diagnostic_rom())
            build(source,root/'out',500)
            commands=('frames 600\nbinddown "gamepads.1.start"\n'
                      'binddown "gamepads.1.right"\nframes 4\n'
                      'p/x [$ff2300].b [$ff2301].b [$ff2302].b [$ff0018].l\nquit\n')
            code,output,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(root/'out'/'recompiled.md')],commands,30)
            values=_blastem_values(output)
            self.assertFalse(timed,output);self.assertEqual(code,0,output)
            self.assertEqual([values.get(a) for a in ('FF2300.b','FF2301.b','FF2302.b','FF0018.l')],[0xD7,0xEE,0xC6,0],output)

    def test_controller_diagnostic_combines_selected_rows(self):
        from gb_cpu import CPU,Memory
        m=Memory(controller_diagnostic_rom());c=CPU(m);m.joypad_state=0x7E
        for _ in range(100):c.step()
        self.assertEqual(m.wram[:3],bytes([0xD7,0xEE,0xC6]))

    def test_controller_diagnostic_records_all_reads(self):
        from gb_cpu import CPU,Memory
        m=Memory(controller_diagnostic_rom(True));c=CPU(m);m.joypad_state=0x7E
        for _ in range(300):c.step()
        self.assertEqual(m.wram[0x10:0x16],bytes([0xD7,0xD7,0xEE,0xEE,0xC6,0xC6]))

    def test_rst_thunks_require_proven_caller_mapping(self):
        import trace_recompiler as trace
        for steps,expected in ((1,False),(2,True)):
            with self.subTest(steps=steps),tempfile.TemporaryDirectory() as d:
                root=pathlib.Path(d);source=root/'banked-dispatch.gb'
                source.write_bytes(banked_rst_dispatch_diagnostic_rom())
                blocks=trace.compile_trace(source,root/'out',steps)
                self.assertEqual((1,0x4100) in {(b['bank'],b['pc']) for b in blocks},expected)
    def test_mapper_store_changes_next_instruction_bank(self):
        from gb_cpu import CPU,Memory
        for mapper,bank in ((1,2),(0x19,0)):
            m=Memory(bank_switch_diagnostic_rom(mapper,bank));c=CPU(m)
            for _ in range(20):c.step()
            self.assertEqual(m.wram[0],0x42)
            self.assertEqual(m.rom_bank,bank)

    def test_mbc5_bank_zero_upper_window_static_fallthrough(self):
        import trace_recompiler as trace
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);source=root/'bank-zero.gb'
            source.write_bytes(bank_switch_diagnostic_rom(0x19,0))
            blocks=trace.compile_trace(source,root/'out',4)
            self.assertIn((0,0x4007),{(b['bank'],b['pc']) for b in blocks})

    def test_fixed_window_jump_does_not_assume_unique_observed_bank(self):
        import trace_recompiler as trace
        rom=bytearray(0x10000);rom[0x147:0x14A]=bytes([1,1,0])
        rom[0x100:0x103]=bytes.fromhex('c36001')
        rom[0x160:0x163]=bytes.fromhex('c30040')
        rom[0x4000:0x4002]=bytes([0x18,0xFE])
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);source=root/'bank.gb';source.write_bytes(rom)
            trace.compile_trace(source,root/'out',3)
            assembly=(root/'out'/'translated_trace.s').read_text()
            body=assembly.split('L_gb_B000_0160:',1)[1].split('L_gb_B001_4000:',1)[0]
            self.assertIn('jmp gb_dispatch',body)
            self.assertNotIn('jmp gb_chain_B001_4000',body)
            self.assertIn('gb_dispatch_tree:\n\tjsr gb_normalize_bank',assembly)
    def test_rst_dispatch_trampoline_closes_untraced_target(self):
        from gb_cpu import CPU,Memory
        import trace_recompiler as trace
        rom=rst_dispatch_diagnostic_rom();m=Memory(rom);c=CPU(m)
        for _ in range(50):c.step()
        self.assertEqual(m.wram[0],0x42)
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);source=root/'dispatch.gb';source.write_bytes(rom)
            blocks=trace.compile_trace(source,root/'out',1)
            keys={(b['bank'],b['pc']) for b in blocks}
            self.assertIn((0,0x150),keys)
            self.assertNotIn((0,0x103),keys)
            report=json.loads((root/'out'/'trace-profile.json').read_text())
            self.assertEqual(report['rst_inline_table_targets'],2)

    def test_rst_dispatch_rejects_unknown_banks_cycles_and_near_matches(self):
        from trace_recompiler import is_inline_rst_dispatch
        rom=bytearray(rst_dispatch_diagnostic_rom())
        self.assertTrue(is_inline_rst_dispatch(rom,0))
        rom[0x136]=0x13
        self.assertFalse(is_inline_rst_dispatch(rom,0))
        rom[:3]=bytes([0xC3,0,0])
        self.assertFalse(is_inline_rst_dispatch(rom,0))
        rom[:3]=bytes([0xC3,0,0x40])
        rom[0x4000:0x400F]=bytes.fromhex('5f1600cb23cb12e1195e2356d5e1e9')
        self.assertFalse(is_inline_rst_dispatch(rom,0))
    def test_memory_scan_does_not_advance_to_vblank(self):
        from gb_cpu import CPU,Memory
        m=Memory(memory_scan_diagnostic_rom());c=CPU(m)
        for _ in range(500):
            c.step()
            if m.wram[0]==0x42:break
        self.assertEqual(m.wram[:2],bytes([0x42,0]))
        self.assertLess(m.cycles,144*456)

    def test_stat_poll_exits_in_hblank_without_vblank_skip(self):
        from gb_cpu import CPU,Memory
        import trace_recompiler as trace
        rom=stat_poll_diagnostic_rom();m=Memory(rom);c=CPU(m)
        for _ in range(500):
            c.step()
            if m.wram[0]==0x42:break
        self.assertEqual(m.wram[0],0x42)
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);source=root/'stat-poll.gb';source.write_bytes(rom)
            blocks=trace.compile_trace(source,root/'out',500)
            self.assertFalse(any(b.get('idle_wait') for b in blocks))

    def test_idle_skip_requires_known_memory_or_exact_ly_equality(self):
        import trace_recompiler as trace
        cases=[('f041e60320fa',False),('fa41ffe60320f9',False),
               ('f044bd20fb',False),('f044bc28fb',False),
               ('f044fe9030fa',False),('f044fe9028fa',False),
               ('f044feff20fa',False),('2aa720fc',False),
               ('f0d1a728fb',True),('fa00c0a728fa',True)]
        for code,expected in cases:
            with self.subTest(code=code),tempfile.TemporaryDirectory() as d:
                root=pathlib.Path(d);rom=bytearray(0x8000);raw=bytes.fromhex(code)
                rom[0x100:0x100+len(raw)]=raw
                rom[0x100+len(raw):0x102+len(raw)]=bytes([0x18,0xFE])
                source=root/'poll.gb';source.write_bytes(rom)
                blocks=trace.compile_trace(source,root/'out',100)
                branch=next(b for b in blocks if b['pc']==0x100+len(raw)-2)
                self.assertEqual(bool(branch.get('idle_wait')),expected)

    def test_full_window_fixture_ignores_background_scroll(self):
        from gb_cpu import CPU,Memory
        from gb_render import frame_ppm
        m=Memory(window_diagnostic_rom());c=CPU(m)
        for _ in range(100):c.step()
        self.assertEqual(frame_ppm(m).split(b'\n',3)[3][:3],bytes([136,192,112]))

    def test_partial_window_fixture_starts_at_wy(self):
        from gb_cpu import CPU,Memory
        from gb_render import frame_ppm
        m=Memory(window_diagnostic_rom(128));c=CPU(m)
        for _ in range(100):c.step()
        pixels=frame_ppm(m).split(b'\n',3)[3]
        self.assertEqual(pixels[:3],bytes([224,248,208]))
        self.assertEqual(pixels[128*160*3:128*160*3+3],bytes([136,192,112]))

    def test_reference_window_origin_map_and_clipping(self):
        from gb_cpu import Memory
        from gb_render import frame_ppm
        m=Memory(bytes(0x8000));m.io[0x40]=0xF1;m.io[0x47]=0xE4
        m.io[0x4A]=8;m.io[0x4B]=15
        m.vram[0x1C00]=1
        m.vram[16:32]=bytes([0xFF,0]*8)
        pixels=frame_ppm(m).split(b'\n',3)[3]
        pixel=lambda x,y:pixels[(y*160+x)*3:(y*160+x+1)*3]
        self.assertEqual(pixel(8,7),bytes([224,248,208]))
        self.assertEqual(pixel(7,8),bytes([224,248,208]))
        self.assertEqual(pixel(8,8),bytes([136,192,112]))
        m.io[0x4B]=167
        self.assertNotIn(bytes([136,192,112]),frame_ppm(m).split(b'\n',3)[3])

    def test_stat_interrupt_wakes_halt(self):
        from gb_cpu import CPU,Memory
        m=Memory(stat_diagnostic_rom());c=CPU(m)
        for _ in range(500):
            c.step()
            if m.wram[0]==0x42:break
        self.assertEqual(m.wram[:2],bytes([0x42,0x77]))

    def test_input_snapshot_key_retains_stat_edge_latch(self):
        from gb_cpu import CPU,Memory
        from trace_recompiler import exploration_state_key
        c=CPU(Memory(bytes(0x8000)));before=exploration_state_key(c)
        c.m.stat_line=True
        self.assertNotEqual(before,exploration_state_key(c))

    def test_stat_hblank_edges_and_combined_line(self):
        from gb_cpu import Memory
        m=Memory(bytes(0x8000));m.write(0xFF40,0x80);m.write(0xFF41,8)
        m.tick(251);self.assertFalse(m.io[15]&2)
        m.tick(1);self.assertTrue(m.io[15]&2)
        m.write(0xFF0F,0);m.tick(4);self.assertFalse(m.io[15]&2)
        m.tick(456);self.assertTrue(m.io[15]&2)
        # Coincidence and mode sources share one edge-triggered OR line.
        m=Memory(bytes(0x8000));m.write(0xFF40,0x80);m.write(0xFF41,0x48)
        m.write(0xFF0F,0);m.tick(252);self.assertFalse(m.io[15]&2)
        m.write(0xFF45,1)
        m.write(0xFF0F,0);m.tick(204);self.assertFalse(m.io[15]&2)

    def test_stat_modes_masks_and_lcd_off(self):
        from gb_cpu import Memory
        m=Memory(bytes(0x8000));m.write(0xFF40,0x80)
        self.assertEqual(m.read(0xFF41)&0x87,0x86)
        m.tick(80);self.assertEqual(m.read(0xFF41)&3,3)
        m.tick(172);self.assertEqual(m.read(0xFF41)&3,0)
        m.tick(456*144-252);self.assertEqual(m.read(0xFF41)&3,1)
        m.write(0xFF41,0xFF);self.assertEqual(m.read(0xFF41)&3,1)
        m.write(0xFF40,0);m.write(0xFF0F,0);m.tick(70224)
        self.assertEqual(m.read(0xFF41)&3,0);self.assertFalse(m.io[15]&2)

    def test_external_assembler_resolution(self):
        import build_recompiled
        with tempfile.TemporaryDirectory() as d:
            assembler=pathlib.Path(d)/"vasmm68k_mot"
            assembler.write_bytes(b"")
            self.assertEqual(build_recompiled.find_assembler(assembler),assembler.resolve())

    def test_minimal_rom_translation(self):
        rom = bytearray(0x150); rom[0x134:0x138] = b"TEST"
        rom[0x100:0x106] = bytes([0x3E, 0x12, 0xEA, 0x00, 0xC0, 0xC9])
        with tempfile.TemporaryDirectory() as d:
            src, out = pathlib.Path(d)/"test.gb", pathlib.Path(d)/"out"; src.write_bytes(rom)
            subprocess.run([sys.executable, ROOT/"gb2md.py", src, "--out", out, "--emit-title-rom"], check=True)
            self.assertIn("L_gb_0100", (out/"translated_bank0.s").read_text())
            self.assertEqual(json.loads((out/"memory-plan.json").read_text())["title"], "TEST")
            self.assertEqual((out/"title_screen.md").read_bytes()[0x100:0x104], b"SEGA")

    def test_mbc3_profile(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("gb2md", ROOT / "gb2md.py")
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        rom = bytearray(64 * 0x4000); rom[0x147:0x14A] = bytes([0x13, 0x05, 0x03])
        profile = module.cartridge_profile(rom)
        self.assertEqual(profile["mapper"], "mbc3")
        self.assertEqual(profile["external_ram_bytes"], 32 * 1024)

    def test_full_instruction_length_table(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("gb2md", ROOT / "gb2md.py")
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        self.assertEqual(module.instruction_length(0xCB), 2)
        self.assertEqual(module.instruction_length(0xEA), 3)
        self.assertEqual(module.instruction_length(0x36), 2)
        self.assertEqual(module.instruction_length(0xAF), 1)

    def test_genesis_title_rom_header(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("title", ROOT / "build_title_demo.py")
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as d:
            out = pathlib.Path(d) / "title.md"; result = module.emit_title_rom(out); image = out.read_bytes()
            self.assertEqual(image[0x100:0x104], b"SEGA")
            self.assertEqual(int.from_bytes(image[4:8], "big"), 0x200)
            self.assertEqual(len(image), result["size"])
            self.assertNotEqual(int.from_bytes(image[0x18E:0x190], "big"), 0)
            # The first DBF is at $27C. Its -6 displacement returns to $278,
            # the start of the VRAM-clear store; -8 would jump into an operand.
            self.assertEqual(int.from_bytes(image[0x27E:0x280], "big", signed=True), -6)

    def test_mbc3_bank_ram_and_rtc_latch(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("memory", ROOT / "gb_memory.py")
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        rom = bytearray(64 * 0x4000)
        for bank in range(64): rom[bank * 0x4000] = bank
        m = module.MBC3(bytes(rom))
        self.assertEqual(m.read(0x4000), 1)
        m.write(0x2000, 0); self.assertEqual(m.read(0x4000), 1)
        m.write(0x2000, 42); self.assertEqual(m.read(0x4000), 42)
        m.write(0xA000, 7); self.assertEqual(m.read(0xA000), 0xFF)
        m.write(0x0000, 0x0A); m.write(0x4000, 3); m.write(0xA000, 7)
        self.assertEqual(m.read(0xA000), 7)
        m.write(0x4000, 0x08); m.write(0xA000, 9); m.write(0x6000, 0); m.write(0x6000, 1)
        m.write(0xA000, 10); self.assertEqual(m.read(0xA000), 9)

    def test_synthetic_reference_program_updates_vram(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("cpu", ROOT / "gb_cpu.py")
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        rom=bytearray(0x8000)
        rom[0x100:0x108]=bytes([0x3E,0x12,0xEA,0x00,0x80,0xC3,0x00,0x01])
        memory = module.Memory(rom); cpu = module.CPU(memory)
        for _ in range(4): cpu.step()
        self.assertNotEqual(sum(memory.vram), 0)
        self.assertNotEqual(cpu.pc, 0x100)

    def test_dmg_tile_to_genesis_4bpp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("vdp", ROOT / "gb_vdp.py")
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        # Pixel colours 0,1,2,3 repeated twice in the first source row.
        source = bytes([0x55,0x33]) + bytes(14)
        self.assertEqual(module.md_tile(source)[:4], bytes([0x01,0x23,0x01,0x23]))

    def test_ei_is_delayed_by_one_instruction(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("cpu", ROOT / "gb_cpu.py")
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        rom=bytearray(0x8000); rom[0x100:0x104]=bytes([0xFB,0x00,0x00,0x76]); rom[0x40]=0xD9
        m=module.Memory(rom); c=module.CPU(m); m.io[0x0F]=m.ie=1
        c.step(); self.assertFalse(c.ime)
        c.step(); self.assertFalse(c.ime)
        c.step(); self.assertEqual(c.pc,0x40)

    def test_lr35902_cycle_costs_include_taken_branches_and_cb_memory(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location("cpu_cycles",ROOT/"gb_cpu.py");module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        self.assertEqual(module.instruction_cycles(0x00),4)
        self.assertEqual(module.instruction_cycles(0x20,taken=False),8)
        self.assertEqual(module.instruction_cycles(0x20,taken=True),12)
        self.assertEqual(module.instruction_cycles(0xCB,0x46),12) # BIT 0,(HL)
        self.assertEqual(module.instruction_cycles(0xCB,0x06),16) # RLC (HL)

    def test_input_scripts_are_frame_based_and_composable(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location("trace_inputs",ROOT/"trace_recompiler.py");module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        scenario=module.parse_input_script("start@512:8,a|right@700:4")
        self.assertEqual(scenario["events"],[(512,520,0x7F),(700,704,0xEE)])
        scenario=module.parse_input_script("start@512:8,poke:0xCA22-0xCA2B=0x8C@850")
        self.assertEqual(scenario["memory_events"],[(850,0xCA22,0xCA2B,0x8C)])
        with self.assertRaises(ValueError):module.parse_input_script("fire@1:2")

    def test_wram_echo_addresses_share_backing_storage(self):
        from gb_cpu import Memory
        memory=Memory(bytes(0x8000))
        memory.write(0xC802,0x8C)
        self.assertEqual(memory.read(0xE802),0x8C)
        memory.write(0xE123,0x42)
        self.assertEqual(memory.read(0xC123),0x42)

    def test_oam_dma_has_two_cycle_startup_and_progressive_copy(self):
        from gb_cpu import Memory
        memory=Memory(bytes(0x8000));memory.wram[:0xA0]=bytes(range(0xA0))
        memory.oam[:]=b"\xCC"*0xA0;memory.write(0xFF46,0xC0)
        self.assertEqual(memory.oam[0],0xCC)
        memory.tick(4)  # Request is armed; OAM remains accessible this cycle.
        self.assertFalse(memory.dma_active);self.assertEqual(memory.read(0xFE00),0xCC)
        memory.tick(4)  # DMA becomes active, but has not copied byte zero yet.
        self.assertTrue(memory.dma_active);self.assertEqual(memory.read(0xFE00),0xFF)
        self.assertEqual(memory.oam[0],0xCC)
        memory.tick(4);self.assertEqual(memory.oam[0],0)
        self.assertEqual(memory.oam[1],0xCC)
        memory.tick(4*159)
        self.assertFalse(memory.dma_active);self.assertEqual(memory.read(0xFE9F),0x9F)

    def test_oam_dma_restart_keeps_old_transfer_running_until_new_start(self):
        from gb_cpu import Memory
        memory=Memory(bytes(0x8000))
        memory.wram[:0xA0]=b"\x11"*0xA0
        memory.wram[0x1000:0x10A0]=b"\x22"*0xA0
        memory.write(0xFF46,0xC0);memory.tick(12)
        self.assertEqual(memory.oam[0],0x11)
        memory.write(0xFF46,0xD0)
        memory.tick(4);self.assertEqual(memory.oam[1],0x11)
        memory.tick(4);self.assertEqual(memory.oam[2],0x11);self.assertEqual(memory.dma_index,0)
        memory.tick(4);self.assertEqual(memory.oam[0],0x22);self.assertEqual(memory.dma_index,1)

    def test_oam_dma_high_source_pages_mirror_wram_not_io(self):
        from gb_cpu import Memory
        memory=Memory(bytes(0x8000));memory.wram[0x1F00:0x1FA0]=bytes(range(0xA0))
        memory.io[:]=b"\xEE"*0x80
        memory.write(0xFF46,0xFF);memory.tick(4*(2+160))
        self.assertEqual(memory.oam,bytes(range(0xA0)))

    def test_cpu_records_bytes_fetched_after_dma_bus_transition(self):
        from gb_cpu import CPU, Memory
        memory=Memory(bytes(0x8000));memory.oam[1]=0x04
        cpu=CPU(memory);cpu.pc=0xFE01
        memory.write(0xFF46,0xC0);memory.tick(4)  # DMA is in startup.
        cpu.step()
        self.assertEqual(cpu.last_pc,0xFE01)
        self.assertEqual(cpu.last_instruction,b"\xFF")
        self.assertEqual(cpu.pc,0x0038)

    def test_native_oam_dma_is_progressive_and_blocks_cpu_oam_access(self):
        runtime=(ROOT/"runtime_68000.s").read_text()
        self.assertIn("gb_dma_advance:",runtime)
        self.assertIn("move.b #1,gb_dma_requested",runtime)
        self.assertIn("tst.b gb_dma_active\n\tbne.s .oam_unchanged",runtime)
        self.assertNotIn(".dma_direct_loop:",runtime)

    def test_joypad_matrix_selects_active_low_rows(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("cpu", ROOT / "gb_cpu.py")
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        m=module.Memory(bytearray(0x8000)); m.joypad_state=0x7E
        m.write(0xFF00,0x20)  # Direction row: Right is pressed.
        self.assertEqual(m.read(0xFF00)&0x0F,0x0E)
        m.write(0xFF00,0x10)  # Button row: Start is pressed.
        self.assertEqual(m.read(0xFF00)&0x0F,0x07)

    def test_ie_does_not_alias_ff7f(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location("cpu_ie",ROOT/"gb_cpu.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        m=module.Memory(bytearray(0x8000));m.write(0xFFFF,0x1F);m.write(0xFF7F,0)
        self.assertEqual(m.read(0xFFFF),0x1F)
        self.assertEqual(m.read(0xFF7F),0)

    def test_timer_falling_edge_reload_and_interrupt(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location("cpu_timer",ROOT/"gb_cpu.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        m=module.Memory(bytearray(0x8000));m.write(0xFF06,0xA5);m.write(0xFF05,0xFF);m.write(0xFF07,0x05)
        m.tick(16);self.assertEqual(m.read(0xFF05),0);self.assertEqual(m.read(0xFF0F)&4,0)
        m.tick(4);self.assertEqual(m.read(0xFF05),0xA5);self.assertEqual(m.read(0xFF0F)&4,4)

    def test_div_write_can_clock_tima(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location("cpu_div",ROOT/"gb_cpu.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        m=module.Memory(bytearray(0x8000));m.write(0xFF07,0x05);m.tick(8)
        self.assertEqual(m.read(0xFF05),0);m.write(0xFF04,0);self.assertEqual(m.read(0xFF05),1)

    def test_if_unused_bits_read_high_and_ei_sequence_is_not_postponed(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location("cpu_if_ei",ROOT/"gb_cpu.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        rom=bytearray(0x8000);rom[0x100:0x103]=bytes((0xFB,0xFB,0x00))
        m=module.Memory(rom);m.write(0xFF0F,0xFF);self.assertEqual(m.read(0xFF0F),0xFF)
        self.assertEqual(m.io[0x0F],0x1F);m.io[0x0F]=0
        c=module.CPU(m);c.step();self.assertFalse(c.ime);c.step();self.assertFalse(c.ime)
        c.step();self.assertTrue(c.ime)

    def test_io_write_occurs_at_final_instruction_boundary(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location("cpu_io_timing",ROOT/"gb_cpu.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        rom=bytearray(0x8000);rom[0x100:0x102]=bytes((0xE0,0x04))
        m=module.Memory(rom);c=module.CPU(m);c.step()
        self.assertEqual(m.cycles,12);self.assertEqual(m.div_counter,0)

    def test_timer_reload_cycle_write_rules_and_tac_mask(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location("cpu_reload",ROOT/"gb_cpu.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        m=module.Memory(bytearray(0x8000));m.write(0xFF07,0xFF);self.assertEqual(m.read(0xFF07),0xFF);m.write(0xFF07,0x05)
        m.write(0xFF06,0xA5);m.write(0xFF05,0xFF);m.div_counter=15;m.tick(1);m.tick(4)
        self.assertTrue(m.timer_reloaded_this_cycle);m.write(0xFF05,0x11);self.assertEqual(m.read(0xFF05),0xA5)
        m.write(0xFF06,0x77);self.assertEqual(m.read(0xFF05),0x77)

    def test_halt_bug_suppresses_one_opcode_fetch_increment(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location("cpu_halt_bug",ROOT/"gb_cpu.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        rom=bytearray(0x8000);rom[0x100:0x103]=bytes((0x76,0x04,0x00))
        m=module.Memory(rom);m.ie=1;m.io[0x0F]=1;c=module.CPU(m)
        c.step();self.assertFalse(c.halted);self.assertTrue(c.halt_bug);self.assertEqual(c.pc,0x101)
        c.step();self.assertEqual(c.b,1);self.assertEqual(c.pc,0x101)
        c.step();self.assertEqual(c.b,2);self.assertEqual(c.pc,0x102)

    def test_native_runtime_contains_timing_video_and_input_services(self):
        runtime=(ROOT/"runtime_68000.s").read_text()
        for label in ("gb_tick:","gb_render_frame:","gb_read_joypad:","gb_ei_delay",".sprite:","gb_video_dirty"):
            self.assertIn(label,runtime)
        # CLR is a read-modify-write instruction on 68000. Reading the VDP
        # data port while it is configured for writes freezes BlastEm/hardware.
        self.assertNotIn("clr.w $C00000",runtime)
        self.assertIn(".io_timing_synced:",runtime)
        self.assertIn(".plain_io_synced:",runtime)
        self.assertIn("gb_force_tick",runtime)

    def test_native_memory_dispatch_prioritizes_writable_high_memory(self):
        runtime=(ROOT/"runtime_68000.s").read_text()
        read=runtime.split("gb_read8:",1)[1].split("gb_write8:",1)[0]
        write=runtime.split("gb_write8:",1)[1].split("gb_idle_wait:",1)[0]
        self.assertLess(read.index("cmpi.w #$C000,d1"),read.index("cmpi.w #$4000,d1"))
        self.assertLess(read.index("cmpi.w #$FF00,d1"),read.index(".read_low:"))
        self.assertLess(write.index("cmpi.w #$C000,d1"),write.index("cmpi.w #$8000,d1"))
        self.assertLess(write.index("cmpi.w #$FF00,d1"),write.index(".write_low:"))
        # Native external RAM must not silently alias every mapper bank to
        # bank zero. MBC1 mode/upper writes and MBC3 RAM/RTC selection have
        # distinct handlers, while unsupported RTC selectors stay inaccessible.
        self.assertIn("gb_mbc1_mode equ",runtime)
        self.assertIn(".mapper_mbc1:",write)
        self.assertIn(".mapper_mbc3:",write)
        self.assertIn("move.b d0,gb_ram_bank",write)
        self.assertIn("cmpi.b #4,gb_ram_bank",read)

    def test_native_scf_and_ccf_preserve_z_and_update_carry(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location("trace_flags",ROOT/"trace_recompiler.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        base={"operand":0,"pc":0x100,"bank":0,"bytes":"37"}
        scf=module.native_body({**base,"opcode":0x37,"family":"SCF"})
        ccf=module.native_body({**base,"opcode":0x3F,"family":"CCF","bytes":"3f"})
        self.assertIn("andi.b #$80,d0",scf);self.assertIn("ori.b #$10,d0",scf)
        self.assertIn("eori.b #$10,d1",ccf);self.assertIn("andi.b #$80,d0",ccf)

    def test_background_transparency_preserves_gb_sprite_priority(self):
        runtime=(ROOT/"runtime_68000.s").read_text()
        build=(ROOT/"build_recompiled.py").read_text()
        self.assertNotIn("addi.w #$1111,d4",runtime)
        self.assertIn("ori.w #$8000,d0",runtime)
        self.assertIn("word=643",build)
        self.assertIn("$44444444",build)

    def test_oam_only_frames_skip_full_background_conversion(self):
        runtime=(ROOT/"runtime_68000.s").read_text()
        for symbol in ("gb_vram_dirty", "gb_oam_dirty", "gb_bg_dirty",
                       "gb_plane_initialized", ".render_tilemap:", ".sprite_section:"):
            self.assertIn(symbol,runtime)
        self.assertIn("beq.w .sprite_section",runtime)
        background=runtime.split(".render_background:",1)[1].split(".sprite_section:",1)[0]
        self.assertIn("tst.b gb_vram_dirty",background)
        self.assertIn("beq.w .render_tilemap",background)
        self.assertIn("tst.b gb_plane_initialized",background)
        self.assertIn("gb_tile_dirty equ",runtime)
        self.assertIn(".dirty_tile:",background)
        self.assertIn(".upload_dirty_tile:",background)
        self.assertNotIn("move.w #3071,d7",background)
        self.assertNotIn("move.w #2047,d7                 ; 256 tiles",background)
        vram_write=runtime.split(".vram:",1)[1].split(".wram:",1)[0]
        self.assertIn("cmpi.w #$1800,d1",vram_write)
        self.assertIn("lea gb_tile_dirty,a0",vram_write)
        self.assertIn(".vram_map_dirty:",vram_write)
        self.assertIn("move.b #1,gb_bg_dirty",vram_write)

    def test_daa_has_a_native_lowering(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location("trace_daa",ROOT/"trace_recompiler.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        block={"bank":0,"pc":0x100,"opcode":0x27,"operand":0,"bytes":"27","family":"DAA"}
        body=module.native_body(block)
        self.assertIsNotNone(body)
        self.assertIn("move.b d0,gb_a",body)
        self.assertIn("move.b d1,gb_f",body)

    def test_signed_sp_offset_families_have_native_lowerings(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location("trace_sp",ROOT/"trace_recompiler.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        for opcode,family,target in ((0xE8,"ADD_SP_R8","gb_sp"),(0xF8,"LD_HL_SP_R8","gb_h")):
            block={"bank":0,"pc":0x100,"opcode":opcode,"operand":0xF8,"bytes":f"{opcode:02x}f8","family":family}
            body=module.native_body(block)
            self.assertIsNotNone(body)
            self.assertIn("ext.w d3",body)
            self.assertIn(f"move.w d0,{target}",body)

    def test_store_sp_absolute_has_native_lowering(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location("trace_store_sp",ROOT/"trace_recompiler.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        block={"bank":0,"pc":0x100,"opcode":0x08,"operand":0xC123,"bytes":"0823c1","family":"LD_A16_SP"}
        body=module.native_body(block)
        self.assertIsNotNone(body)
        self.assertIn("move.l #$C123,d1",body)
        self.assertIn("move.l #$C124,d1",body)

    def test_color_profiles_expose_sgb_ready_palette_boundary(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location("colors",ROOT/"color_profiles.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        self.assertEqual(set(module.COLOR_PROFILES),{"amber","dmg","green","pocket"})
        self.assertTrue(all(len(p["shades"])==4 for p in module.COLOR_PROFILES.values()))

    def test_cpu_memory_mbc3_rom_window(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location("cpu",ROOT/"gb_cpu.py"); module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        rom=bytearray(64*0x4000); rom[0x147:0x14A]=bytes([0x13,0x05,0x03])
        for bank in range(64):rom[bank*0x4000]=bank
        m=module.Memory(rom); self.assertEqual(m.read(0x4000),1);m.write(0x2000,37);self.assertEqual(m.read(0x4000),37)

    def test_synthetic_executed_opcodes_have_lowering_families(self):
        import importlib.util
        def load(name):
            spec=importlib.util.spec_from_file_location(name,ROOT/(name+".py"));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
        cpu,lower=load("gb_cpu"),load("lr35902_lowering")
        rom=bytearray(0x8000);rom[0x100:0x108]=bytes([0x3E,0x12,0x06,0x34,0x80,0xAF,0x00,0x76])
        c=cpu.CPU(cpu.Memory(rom))
        for _ in range(8):c.step()
        self.assertNotIn("UNCLASSIFIED",{lower.family(op) for op in c.opcode_count})
        self.assertNotIn("INVALID",{lower.family(op) for op in c.opcode_count})

    def test_trace_recompiler_emits_synthetic_blocks(self):
        import importlib.util
        sys.path.insert(0,str(ROOT))
        spec=importlib.util.spec_from_file_location("trace",ROOT/"trace_recompiler.py");module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as d:
            temp=pathlib.Path(d);rom=temp/"original-test.gb";data=bytearray(0x8000)
            data[0x100:0x10C]=bytes([0x00])*12;data[0x10C:0x10F]=bytes([0xC3,0x00,0x01]);rom.write_bytes(data)
            blocks=module.compile_trace(rom,temp,5000)
            assembly=(temp/"translated_trace.s").read_text()
            self.assertGreater(len(blocks),10);self.assertIn("gb_dispatch",assembly)
            self.assertIn("bra.w L_gb_B000_0100",assembly)
            self.assertIn("jmp gb_dispatch",assembly)
            self.assertIn(".dispatch_not_equal_",assembly)
            self.assertIn("gb_chain_B000_",assembly)
            self.assertIn("cmpi.w #200,d1",assembly)
            self.assertIn("move.w d7,d1",assembly)
            self.assertNotIn("move.w gb_cycle_batch,d1",assembly)
            self.assertRegex(assembly,r"\.chain_flush_B000_[0-9A-F]{4}:\n\tclr\.b gb_force_tick\n\tmove\.w #\$[0-9A-F]{4},gb_pc\n\tjsr gb_tick")
            self.assertTrue(all("bytes" in block and "operand" in block and "bank" in block for block in blocks))
            self.assertTrue(any(block["native_lowered"] for block in blocks))

    def test_input_snapshot_key_distinguishes_dma_and_held_input(self):
        import copy
        from gb_cpu import CPU,Memory
        from trace_recompiler import exploration_state_key
        cpu=CPU(Memory(bytes(0x8000)));baseline=exploration_state_key(cpu)
        # Identical memory bytes can have different next bus reads or JOYP
        # results because DMA and held buttons are state outside those bytes.
        for name,value in (('dma_requested',0),('dma_starting',0),
                           ('dma_active',True),('dma_source',0xC0),
                           ('dma_index',1),('dma_phase',1),('joypad_state',0x7F)):
            changed=copy.deepcopy(cpu);setattr(changed.m,name,value)
            with self.subTest(field=name):
                self.assertNotEqual(baseline,exploration_state_key(changed))
        self.assertEqual(baseline,exploration_state_key(copy.deepcopy(cpu)))

    def test_input_sweep_varies_holds_and_releases_deterministically(self):
        from trace_recompiler import InputSweep
        one=InputSweep(10,1);two=InputSweep(10,1)
        states=[one.state(frame) for frame in range(250)]
        self.assertEqual(states,[two.state(frame) for frame in range(250)])
        self.assertEqual(states[:10],[255]*10)
        self.assertEqual(set(states),{0x7F,0xEF,255})
        lengths=[];length=1
        for previous,current in zip(states[10:],states[11:]):
            if previous==current:length+=1
            else:lengths.append(length);length=1
        self.assertGreater(len(set(lengths)),3)
        for args in ((-1,1),(0,0)):
            with self.assertRaises(ValueError):InputSweep(*args)

    def test_input_sweep_discovers_ram_callback_and_obeys_total_budget(self):
        import trace_recompiler as trace
        rom=input_sweep_diagnostic_rom()
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);source=root/'sweep.gb';source.write_bytes(rom)
            plain=trace.compile_trace(source,root/'plain',200)
            self.assertNotIn((0,0x180),{(b['bank'],b['pc']) for b in plain})
            blocks=trace.compile_trace(source,root/'sweep',200,auto_inputs=True,
                input_max_branches=1,input_sweep_steps=600_000,
                input_max_steps=600_000,input_hold_frames=1,input_max_snapshots=8)
            self.assertIn((0,0x180),{(b['bank'],b['pc']) for b in blocks})
            report=json.loads((root/'sweep'/'trace-profile.json').read_text())
            self.assertEqual(report['total_steps_executed'],600_200)
            exploration=report['input_exploration']
            self.assertEqual(exploration['branches_executed'],1)
            self.assertEqual(exploration['sweep_steps_executed'],600_000)
            self.assertIn('instruction limit',exploration['stop_reason'])
            trace.compile_trace(source,root/'capped',200,auto_inputs=True,
                input_sweep_steps=600_000,input_max_steps=50,input_max_branches=1)
            capped=json.loads((root/'capped'/'trace-profile.json').read_text())
            self.assertEqual(capped['input_exploration']['steps_executed'],50)
            with self.assertRaises(ValueError):
                trace.compile_trace(source,root/'invalid',200,input_sweep_steps=1)

    def test_auto_step_stop_policy(self):
        import trace_recompiler as trace
        self.assertIsNone(trace.auto_stop_reason(200,1000,[4,0,0],3,1))
        self.assertIn("plateau",trace.auto_stop_reason(300,1000,[4,0,0,0],3,1))
        self.assertIsNone(trace.auto_stop_reason(300,1000,[0,0,0],3,1,events_pending=True))
        self.assertIn("maximum",trace.auto_stop_reason(1000,1000,[5],3,1))

    def test_auto_steps_reports_execution_and_plateau(self):
        import trace_recompiler as trace
        rom=bytearray(0x8000);rom[0x100:0x102]=bytes([0x18,0xFE])
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);source=root/"loop.gb";source.write_bytes(rom)
            trace.compile_trace(source,root/"out",10,auto_steps=True,auto_max_steps=100,auto_chunk_steps=10,auto_plateau_chunks=2)
            report=json.loads((root/"out"/"trace-profile.json").read_text())
            self.assertEqual(report["total_steps_executed"],30)
            self.assertEqual(report["dynamic_unique_blocks"],1)
            self.assertIn("plateau",report["scenarios"][0]["stop_reason"])

    def test_auto_inputs_discovers_indirect_joypad_path(self):
        import trace_recompiler as trace
        rom=bytearray(0x8000)
        # Select buttons, wait for Start, then reach $0120 through JP (HL),
        # which direct static closure deliberately cannot infer.
        rom[0x100:0x10E]=bytes([0x3E,0x10,0xE0,0x00,0xF0,0x00,0xE6,0x08,
                                0x20,0xFA,0x21,0x20,0x01,0xE9])
        rom[0x120:0x124]=bytes([0x3E,0x42,0x18,0xFE])
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);source=root/"input.gb";source.write_bytes(rom)
            plain=trace.compile_trace(source,root/"plain",30)
            self.assertNotIn((0,0x120),{(b["bank"],b["pc"]) for b in plain})
            explored=trace.compile_trace(source,root/"explored",30,auto_inputs=True,
                input_max_branches=10,input_max_depth=2,input_branch_steps=50,
                input_max_steps=500,input_hold_frames=1,input_snapshot_interval_frames=1,
                input_max_snapshots=8)
            self.assertIn((0,0x120),{(b["bank"],b["pc"]) for b in explored})
            report=json.loads((root/"explored"/"trace-profile.json").read_text())
            self.assertGreater(report["input_exploration"]["new_blocks"],0)
            self.assertEqual(report["input_exploration"]["limits"]["max_branches"],10)
            self.assertEqual(report["input_exploration"]["limits"]["max_depth"],2)
            self.assertTrue(any(branch["action"]=="start" and branch["new_blocks"]
                                for branch in report["input_exploration"]["branches"]))

    def test_missing_block_trap_has_machine_readable_diagnostics(self):
        runtime=(ROOT/"runtime_68000.s").read_text()
        self.assertIn("gb_missing_count equ $FF0038",runtime)
        self.assertIn("gb_render_count equ $FF003C",runtime)
        self.assertIn("gb_full_render_count equ $FF0040",runtime)
        self.assertIn("gb_halt_fast_forward_count equ $FF0044",runtime)
        self.assertIn("gb_halt_wait:",runtime)
        self.assertIn("bsr.w gb_halt_wait",runtime)
        self.assertIn("move.l #$BADB10C0,$FF0018",runtime)
        self.assertIn("addq.l #1,gb_missing_count",runtime)

    def test_halt_wait_batches_to_earliest_timer_or_vblank_wake_event(self):
        runtime=(ROOT/"runtime_68000.s").read_text()
        section=runtime.split("gb_halt_wait:",1)[1].split("gb_idle_ly:",1)[0]
        self.assertIn("btst #2,gb_io+$07",section)
        self.assertIn("btst #2,gb_ie",section)
        self.assertIn(".halt_timer_batch:",section)
        self.assertIn("move.w gb_timer_accum,d2",section)
        self.assertIn("sub.w d3,d5",section)
        self.assertIn("addq.l #4,d2",section)
        self.assertIn("cmp.l d1,d2",section)
        self.assertIn("cmpi.l #32760,d1",section)
        self.assertIn("move.w #32760,d7",section)
        self.assertIn("sub.l d0,d1",section)
        self.assertIn("bsr.w gb_tick",section)
        self.assertIn("tst.b gb_halted",section)

    def test_tick_consumes_all_div_and_scanline_boundaries_in_large_batches(self):
        runtime=(ROOT/"runtime_68000.s").read_text()
        section=runtime.split("gb_tick:",1)[1].split("gb_render_frame:",1)[0]
        self.assertIn("andi.w #$00FF,d0",section)
        self.assertIn("lsr.w #8,d1",section)
        self.assertIn(".scanline_loop:",section)
        self.assertIn("subi.w #456,d0",section)
        self.assertIn(".scanlines_done:",section)
        self.assertIn("move.w d0,gb_ly_accum",section)

    def test_auto_inputs_can_cross_non_novel_bridge_state(self):
        import trace_recompiler as trace
        rom=bytearray(0x8000)
        # Start is latched into C000 without changing control flow. A later A
        # press can reach the indirect target only if that non-novel state is
        # retained for another input branch.
        rom[0x100:0x122]=bytes([
            0x3E,0x10,0xE0,0x00,0xF0,0x00,0x2F,0xE6,0x08,0x47,
            0xFA,0x00,0xC0,0xB0,0xEA,0x00,0xC0,0xF0,0x00,0x2F,
            0xE6,0x01,0x28,0xEC,0xFA,0x00,0xC0,0xA7,0x28,0xE6,
            0x21,0x28,0x01,0xE9])
        rom[0x128:0x12C]=bytes([0x3E,0x77,0x18,0xFE])
        old_actions=trace.AUTO_INPUT_ACTIONS
        trace.AUTO_INPUT_ACTIONS=[("start",trace.BUTTON_STATES["start"]),("a",trace.BUTTON_STATES["a"])]
        try:
            with tempfile.TemporaryDirectory() as d:
                root=pathlib.Path(d);source=root/"bridge.gb";source.write_bytes(rom)
                blocks=trace.compile_trace(source,root/"out",200,auto_inputs=True,
                    input_max_branches=12,input_max_depth=3,input_branch_steps=12000,
                    input_max_steps=144000,input_hold_frames=1,
                    input_snapshot_interval_frames=1,input_max_snapshots=8,
                    input_bridge_states_per_depth=4)
                report=json.loads((root/"out"/"trace-profile.json").read_text())
                self.assertGreater(report["input_exploration"]["bridge_states_expanded"],0)
                self.assertIn((0,0x128),{(b["bank"],b["pc"]) for b in blocks})
        finally:
            trace.AUTO_INPUT_ACTIONS=old_actions

    def test_auto_inputs_keeps_non_novel_initial_root_bridges(self):
        from unittest.mock import patch
        import trace_recompiler as trace
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);source=root/'root-bridge.gb';source.write_bytes(root_bridge_diagnostic_rom())
            plain=trace.compile_trace(source,root/'plain',500)
            self.assertNotIn((0,0x1A0),{(b['bank'],b['pc']) for b in plain})
            # Neither individual input executes a novel PC from the initial
            # state. Dropping root bridges loses their useful RAM-state change.
            actions=[('start',trace.BUTTON_STATES['start']),('a',trace.BUTTON_STATES['a'])]
            with patch.object(trace,'AUTO_INPUT_ACTIONS',actions):
                blocks=trace.compile_trace(source,root/'explored',500,auto_inputs=True,
                    input_max_branches=12,input_max_depth=2,input_branch_steps=12000,
                    input_max_steps=144000,input_hold_frames=1,
                    input_snapshot_interval_frames=1,input_max_snapshots=8)
            report=json.loads((root/'explored'/'trace-profile.json').read_text())['input_exploration']
            self.assertEqual(report['branches'][0]['new_blocks'],0)
            self.assertGreater(report['bridge_states_expanded'],0)
            self.assertIn((0,0x1A0),{(b['bank'],b['pc']) for b in blocks})

    def test_static_closure_resolves_bounded_rom_pointer_table(self):
        import trace_recompiler as trace
        rom=bytearray([0xFF])*0x8000
        rom[0x100:0x107]=bytes([0x21,0x20,0x01,0xCD,0x30,0x01,0xE9])
        rom[0x120:0x126]=bytes([0x40,0x01,0x50,0x01,0xFF,0xFF])
        rom[0x130]=0xC9;rom[0x140]=0xC9;rom[0x150]=0xC9
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);source=root/"table.gb";source.write_bytes(rom)
            blocks=trace.compile_trace(source,root/"out",1)
            keys={(b["bank"],b["pc"]) for b in blocks}
            self.assertIn((0,0x140),keys);self.assertIn((0,0x150),keys)
            report=json.loads((root/"out"/"trace-profile.json").read_text())
            self.assertEqual(report["indirect_table_targets"],2)

    def test_static_closure_resolves_rst_inline_pointer_table(self):
        import trace_recompiler as trace
        rom=bytearray([0xFF])*0x8000
        # RST $28 handler: use A*2 to index the little-endian pointer table
        # placed at the stacked return address, then jump to that routine.
        rom[0x28:0x34]=bytes.fromhex("87e15f1600195e2356d5e1e9")
        rom[0x100:0x103]=bytes([0x3E,0x01,0xEF])
        rom[0x103:0x109]=bytes([0x40,0x01,0x50,0x01,0xFF,0xFF])
        rom[0x140]=0xC9;rom[0x150]=0xC9
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);source=root/"rst-table.gb";source.write_bytes(rom)
            blocks=trace.compile_trace(source,root/"out",1)
            keys={(b["bank"],b["pc"]) for b in blocks}
            self.assertIn((0,0x140),keys);self.assertIn((0,0x150),keys)
            self.assertNotIn((0,0x103),keys)  # inline data is not code
            report=json.loads((root/"out"/"trace-profile.json").read_text())
            self.assertEqual(report["rst_inline_table_targets"],2)
            self.assertEqual(report["indirect_table_targets"],2)

    def test_rst_without_table_handler_keeps_normal_fallthrough(self):
        import trace_recompiler as trace
        rom=bytearray([0xFF])*0x8000
        rom[0x28]=0xC9
        rom[0x100:0x104]=bytes([0xEF,0x3E,0x42,0xC9])
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);source=root/"ordinary-rst.gb";source.write_bytes(rom)
            blocks=trace.compile_trace(source,root/"out",1)
            self.assertIn((0,0x101),{(b["bank"],b["pc"]) for b in blocks})

    def test_static_closure_rom_only_cross_window_jump(self):
        import trace_recompiler as trace
        for mapper in (0, 8, 9, 1):
            rom=bytearray(0x8000);rom[0x147]=mapper
            rom[0x100:0x103]=bytes([0xC3,0x00,0x40])
            rom[0x4000:0x4002]=bytes([0x18,0xFE])
            with tempfile.TemporaryDirectory() as d:
                root=pathlib.Path(d);source=root/'cross-window.gb';source.write_bytes(rom)
                blocks=trace.compile_trace(source,root/'out',1)
                keys={(b['bank'],b['pc']) for b in blocks}
                self.assertEqual((1,0x4000) in keys,mapper in (0,8,9))

    def test_static_closure_compiles_both_conditional_paths(self):
        import importlib.util
        sys.path.insert(0,str(ROOT))
        spec=importlib.util.spec_from_file_location("trace_closure",ROOT/"trace_recompiler.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        rom=bytearray(0x8000);rom[0x40]=0xC9
        rom[0x100:0x102]=bytes([0x20,0x02])  # JR NZ: fall $102, target $104
        rom[0x102]=0xC9
        rom[0x104:0x107]=bytes([0x3E,0x12,0xC9])
        with tempfile.TemporaryDirectory() as d:
            src=pathlib.Path(d)/"paths.gb";src.write_bytes(rom)
            blocks=module.compile_trace(src,pathlib.Path(d)/"out",1)
            keys={(b["bank"],b["pc"]) for b in blocks}
            self.assertIn((0,0x102),keys)
            self.assertIn((0,0x104),keys)
            self.assertIn((0,0x40),keys)

    def test_ldh_a_c_has_direct_native_lowering(self):
        import trace_recompiler as trace
        block={"bank":0,"pc":0x100,"opcode":0xF2,"operand":0,
               "bytes":"f2","family":"LDH_A_C"}
        body=trace.native_body(block)
        self.assertIsNotNone(body)
        self.assertIn("move.b gb_c,d1",body)
        self.assertIn("ori.w #$FF00,d1",body)
        self.assertIn("jsr gb_read8",body)
        self.assertIn("move.b d0,gb_a",body)

    def test_static_closure_recovers_direct_hram_code_target(self):
        import importlib.util
        sys.path.insert(0,str(ROOT))
        spec=importlib.util.spec_from_file_location("trace_hram_closure",ROOT/"trace_recompiler.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        rom=bytearray(0x8000)
        # Copy RET to FFB6, then call it. Two traced steps observe the copy;
        # static closure must recover the not-yet-executed HRAM target.
        rom[0x100:0x108]=bytes([0x3E,0xC9,0xE0,0xB6,0xCD,0xB6,0xFF,0x76])
        with tempfile.TemporaryDirectory() as d:
            src=pathlib.Path(d)/"hram.gb";src.write_bytes(rom)
            blocks=module.compile_trace(src,pathlib.Path(d)/"out",2)
            self.assertIn((0,0xFFB6),{(b["bank"],b["pc"]) for b in blocks})

    def test_read_only_ly_poll_is_marked_as_idle_wait(self):
        import importlib.util
        sys.path.insert(0,str(ROOT))
        spec=importlib.util.spec_from_file_location("trace_idle",ROOT/"trace_recompiler.py");module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        rom=bytearray(0x8000)
        # LDH A,(LY); CP 144; JR NZ back to the read.
        rom[0x100:0x106]=bytes([0xF0,0x44,0xFE,0x90,0x20,0xFA])
        with tempfile.TemporaryDirectory() as d:
            src=pathlib.Path(d)/"idle.gb";src.write_bytes(rom)
            blocks=module.compile_trace(src,pathlib.Path(d)/"out",100)
            branch=next(b for b in blocks if b["pc"]==0x104)
            self.assertTrue(branch["idle_wait"])
            self.assertEqual(branch["idle_ly_target"],0x90)
