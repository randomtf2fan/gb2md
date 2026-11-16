"""Original byte-offset ROM-table callbacks with an explicit return address."""
import os
from pathlib import Path
import tempfile
import unittest

from gb_cpu import CPU,Memory
from trace_recompiler import compile_trace,inline_bc_call_table


def inline_bc_rom():
    rom=bytearray(0x8000)
    main=bytes.fromhex('cd50013e99ea01c018fe');rom[0x100:0x100+len(main)]=main
    code=bytes.fromhex('e5d5c50e020600210003092a666ffa10c147fa11c14f')
    call=0x150+len(code);return_pc=call+5
    code+=bytes((0x11,return_pc&255,return_pc>>8,0xD5,0xE9))+bytes.fromhex('c1d1e1c9')
    rom[0x150:0x150+len(code)]=code
    rom[0x300:0x306]=bytes.fromhex('40036003ffff')
    for pc,value in ((0x340,0x11),(0x360,0x42)):
        rom[pc:pc+6]=bytes((0x3E,value,0xEA,0,0xC0,0xC9))
    return bytes(rom),0x155,call,return_pc


class InlineBcCallTests(unittest.TestCase):
    def test_table_and_return_are_operands_not_assumed_addresses(self):
        rom,entry,call,return_pc=inline_bc_rom();diagnostic={}
        self.assertEqual(inline_bc_call_table(rom,0,entry,diagnostic),0x300)
        self.assertEqual(diagnostic['return_address'],return_pc)
        moved=bytearray(rom);body=bytearray(rom[entry:return_pc+4])
        relocated=0x210;new_return=relocated+(return_pc-entry)
        tail=call-entry;body[tail+1:tail+3]=new_return.to_bytes(2,'little')
        moved[relocated:relocated+len(body)]=body
        diagnostic={};self.assertEqual(inline_bc_call_table(moved,0,relocated,diagnostic),0x300)
        self.assertEqual(diagnostic['return_address'],new_return)

    def test_rejects_unproven_high_index_hl_changes_writes_calls_and_returns(self):
        original,entry,call,return_pc=inline_bc_rom()
        for offset,raw in ((entry+1,b'\x01'),(entry+7,b'\x56'),(entry+9,b'\x23'),
                           (entry+9,bytes.fromhex('ea0020')),(entry+9,bytes.fromhex('cd0008')),
                           (call+1,b'\x00'),(return_pc,b'\xf1')):
            with self.subTest(offset=offset,raw=raw):
                rom=bytearray(original);rom[offset:offset+len(raw)]=raw
                self.assertIsNone(inline_bc_call_table(rom,0,entry))

    def test_static_closure_includes_callbacks_and_real_reference_preserves_stack(self):
        rom,entry,call,return_pc=inline_bc_rom();m=Memory(rom);c=CPU(m)
        for _ in range(120):c.step()
        self.assertEqual(m.wram[:2],bytes((0x42,0x99)));self.assertEqual(c.sp,0xFFFE)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'original.gb';source.write_bytes(rom)
            blocks=compile_trace(source,root/'out',2);keys={(b['bank'],b['pc']) for b in blocks}
            self.assertTrue({(0,0x340),(0,0x360),(0,return_pc)}<=keys)

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_callback_and_synthetic_return_restore_stack(self):
        from build_recompiled import build
        from run_compat_tests import _run_in_pty,_blastem_values
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);rom,*_=inline_bc_rom();source=root/'original.gb';source.write_bytes(rom)
            image=build(source,root/'out',2)
            rc,out,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(image)],
                'frames 120\np/x [$ff2300].b [$ff2301].b [$ff0010].w [$ff0018].l [$ff0038].l\nquit\n',20)
            self.assertFalse(timed,out);self.assertEqual(rc,0,out);v=_blastem_values(out)
            self.assertEqual([v.get(k) for k in ('FF2300.b','FF2301.b','FF0010.w','FF0018.l','FF0038.l')],[0x42,0x99,0xFFFE,0,0],out)
