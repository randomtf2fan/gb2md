"""Original scanline-scroll/palette fixtures; no commercial/demo ROM data."""
import os,tempfile,unittest
from pathlib import Path
from gb_cpu import Memory
from gb_raster import background_scanline,palette_pair_table,row_fingerprint


def fixture(signed=False,unsupported=0,transition=False,static=False):
    rom=bytearray(0x8000);rom[0x100:0x103]=bytes.fromhex('c35001')
    code=bytearray.fromhex('f331feffafe040e007e041e00feaffff')
    lcdc=0x89 if signed else 0x91
    ids=[0,129,1,255] if signed else [0,1,2,3]
    tiles={}
    for tile in ids:
        data=bytes(((tile*19+i*73)^0xa6)&255 for i in range(16))
        offset=(0x1000+(tile if tile<128 else tile-256)*16) if signed else tile*16
        tiles[offset]=data;code+=bytes((0x21,offset&255,0x80+(offset>>8)))
        for value in data:code+=bytes((0x3e,value,0x22))
    mapbase=0x1c00 if signed else 0x1800
    code+=bytes((0x21,mapbase&255,0x80+(mapbase>>8)))
    tilemap=bytes(ids[(y+3*x)%4] for y in range(32) for x in range(32))
    for value in tilemap:code+=bytes((0x3e,value,0x22))
    scx=253 if signed else 3
    code+=bytes((0x3e,scx,0xe0,0x43,0x3e,lcdc|unsupported,0xe0,0x40))
    code+=bytes.fromhex('3ea5ea00c0af')+bytes.fromhex('ea01c0')
    loop=0x150+len(code)
    def wait(ly):code.extend((0xf0,0x44,0xfe,ly,0x20,0xfa))
    if static:
        wait(48);code+=bytes.fromhex('3e1be04718fe')
    else:
        wait(0);code+=bytes.fromhex('afe0423ee4e047')
        wait(48);code+=bytes.fromhex('3e05e042')
        wait(96);code+=bytes.fromhex('3e1be047')
        wait(112);code+=bytes.fromhex('3e39e047')  # force two-slot palette eviction
        wait(144)
    if transition:
        code+=bytes.fromhex('2101c0347efe03')
        code+=bytes((0xc2,loop&255,loop>>8))
        code+=bytes((0x3e,lcdc|2,0xe0,0x40,0x18,0xfe))
    elif not static:code+=bytes((0xc3,loop&255,loop>>8))
    rom[0x150:0x150+len(code)]=code
    memory=Memory(bytes(rom));memory.io[0x40]=lcdc;memory.io[0x43]=scx
    for offset,data in tiles.items():memory.vram[offset:offset+16]=data
    memory.vram[mapbase:mapbase+1024]=tilemap
    expected=[]
    for y in range(144):
        memory.io[0x42]=0 if static or y<48 else 5
        memory.io[0x47]=0x1b if static else 0xe4 if y<96 else 0x1b if y<112 else 0x39
        expected.append(row_fingerprint(background_scanline(memory,y)))
    return bytes(rom),expected


class RasterBackgroundTests(unittest.TestCase):
    def test_all_palette_pairs_are_opaque_and_follow_bgp(self):
        table=palette_pair_table();self.assertEqual(len(table),4096)
        for bgp in range(256):
            for pair in range(16):
                a=(bgp>>(2*(pair>>2)))&3;b=(bgp>>(2*(pair&3)))&3
                self.assertEqual(table[bgp*16+pair],((a+1)<<4)|(b+1))

    def test_background_line_wrap_signed_tiles_and_palette(self):
        for signed in (False,True):
            rom,expected=fixture(signed);self.assertEqual(len(expected),144)
            self.assertGreater(len(set(expected)),8)
        m=Memory(bytes(0x8000));m.io[0x40]=0x91;m.io[0x47]=0xe4
        m.vram[:16]=bytes((0x80,0))*8
        self.assertEqual(background_scanline(m,0)[:2],bytes((1,0)))
        m.io[0x43]=255;self.assertEqual(background_scanline(m,0)[:2],bytes((0,1)))
        for bits in (2,0x20):
            m.io[0x40]=0x91|bits
            with self.assertRaises(ValueError):background_scanline(m,0)

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_palette_cache_all_values_and_evictions(self):
        # Isolate the actual native helper, independently of guest execution.
        # Every palette's computed pairs feed an ordered fingerprint; no
        # expected values or result signatures are written into native RAM.
        import subprocess
        from build_recompiled import build,find_assembler
        from run_compat_tests import _run_in_pty,_blastem_values
        probe='''gb_palette_probe:
 moveq #0,d6
 lea $FF4300,a2
.palette:
 move.w d6,d0
 jsr gb_raster_select_palette
 moveq #0,d3
 moveq #0,d7
.pair:
 move.w d7,d1
 andi.w #3,d1
 move.w d7,d2
 andi.w #12,d2
 lsl.w #2,d2
 or.w d2,d1
 moveq #0,d0
 move.b (a3,d1.w),d0
 rol.l #1,d3
 eor.l d0,d3
 addq.w #1,d7
 cmpi.w #16,d7
 blo.s .pair
 move.l d3,(a2)+
 addq.w #1,d6
 cmpi.w #256,d6
 blo.s .palette
 move.b #$A5,$FF2300
.done:
 bra.s .done
'''
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);rom=bytearray(0x8000);rom[0x100:0x103]=bytes.fromhex('c30001')
            source=root/'original.gb';source.write_bytes(rom);build(source,root/'out',2)
            main=root/'out/recompiled_rom.s'
            main.write_text(main.read_text().replace('\tjmp gb_compiled_entry','\tjmp gb_palette_probe',1).replace('gb_cart_rom:',probe+'\ngb_cart_rom:',1))
            image=root/'probe.md';subprocess.run([str(find_assembler()),'-m68000','-Fbin',str(main),'-o',str(image)],check=True,capture_output=True)
            addresses=[f'[$ff{0x4300+4*p:04x}].l' for p in range(256)]
            commands='frames 120\np/x [$ff2300].b\n'+''.join('p/x '+' '.join(addresses[i:i+16])+'\n' for i in range(0,256,16))+'quit\n'
            rc,out,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(image)],commands,30)
            self.assertFalse(timed,out);self.assertEqual(rc,0,out);v=_blastem_values(out)
            self.assertEqual(v.get('FF2300.b'),0xa5,out)
            table=palette_pair_table()
            for palette in range(256):
                expected=0
                for byte in table[palette*16:(palette+1)*16]:expected=(((expected<<1)|(expected>>31))^byte)&0xffffffff
                self.assertEqual(v.get(f'FF{0x4300+4*palette:04X}.l'),expected,f'BGP={palette:02X}')

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_every_scanline_matches_oracle_and_modes_fall_back(self):
        from build_recompiled import build
        from run_compat_tests import _run_in_pty,_blastem_values
        cases=[('unsigned',False,0,False,False),('signed-wrap',True,0,False,False),
               ('sprites',False,2,False,False),('window',False,0x20,False,False),
               ('transition',False,0,True,False),('static-init',False,0,False,True)]
        for name,signed,unsupported,transition,static in cases:
            with self.subTest(name=name),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);rom,expected=fixture(signed,unsupported,transition,static)
                source=root/'original.gb';source.write_bytes(rom);image=build(source,root/'out',150000)
                query='p/x [$ff2300].b [$ff0082].b [$ff0083].b [$ff0086].b [$ff0088].l [$ff008c].l [$ff0018].l [$ff0038].l\n'
                addresses=[f'[$ff{0xc700+4*y:04x}].l' for y in range(144)]
                query+=''.join('p/x '+' '.join(addresses[i:i+12])+'\n' for i in range(0,144,12))
                rc,out,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(image)],
                    'binddown "ui.set_speed.4"\nbindup "ui.set_speed.4"\nframes 1200\n'+query+'quit\n',60)
                self.assertFalse(timed,out);self.assertEqual(rc,0,out);v=_blastem_values(out)
                self.assertEqual(v.get('FF2300.b'),0xa5,out)
                self.assertEqual(v.get('FF0018.l'),0,out);self.assertEqual(v.get('FF0038.l'),0,out)
                if unsupported:
                    self.assertEqual(v.get('FF0088.l'),0,out)
                else:
                    self.assertGreater(v.get('FF0088.l',0),0,out)
                    actual=[v.get(f'FF{0xc700+4*y:04X}.l') for y in range(144)]
                    self.assertEqual(actual,expected,out)
                if unsupported or transition or static:
                    self.assertEqual(v.get('FF0083.b'),0,out)
                    self.assertEqual(v.get('FF0086.b'),0,out)
