"""Reference renderer for the DMG background plane used by GB2MD validation."""
from __future__ import annotations

def frame_ppm(memory):
    """Return a 160x144 binary PPM generated from GB VRAM/LCDC/BGP state."""
    lcdc, scy, scx, bgp = memory.io[0x40], memory.io[0x42], memory.io[0x43], memory.io[0x47]
    shades = ((224,248,208),(136,192,112),(52,104,86),(8,24,32))
    out = bytearray(b"P6\n160 144\n255\n")
    for y in range(144):
        py=(y+scy)&255; tile_y=py>>3; row=py&7
        for x in range(160):
            px=(x+scx)&255; tile_x=px>>3; tile=memory.vram[((0x1C00 if lcdc&8 else 0x1800) + tile_y*32 + tile_x)&0x1FFF]
            if lcdc&0x10: tile_base=tile*16
            else: tile_base=0x1000 + ((tile if tile < 128 else tile-256) * 16)
            lo=memory.vram[(tile_base+row*2)&0x1FFF]; hi=memory.vram[(tile_base+row*2+1)&0x1FFF]
            bit=7-(px&7); colour=((hi>>bit)&1)<<1 | ((lo>>bit)&1); out.extend(shades[(bgp>>(colour*2))&3])
    return bytes(out)
