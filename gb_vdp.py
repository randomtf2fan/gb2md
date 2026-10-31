"""Game Boy DMG background -> Mega Drive VDP asset conversion.

This is the data half of the native renderer: a generated 68000 runtime can
upload `tiles` to VDP VRAM and `plane_a` to a Genesis name table directly.
"""
from __future__ import annotations
import struct

DMG_CRAM = (0x0000, 0x0222, 0x0888, 0x0EEE)

def md_tile(gb_tile):
    """Expand one Game Boy 2bpp tile (16 bytes) into Genesis 4bpp (32 bytes)."""
    if len(gb_tile) != 16: raise ValueError("GB tile must be 16 bytes")
    out=bytearray()
    for row in range(8):
        lo,hi=gb_tile[row*2],gb_tile[row*2+1]
        for pair in range(4):
            p0=7-pair*2; p1=p0-1
            out.append((((hi>>p0)&1)*2 | ((lo>>p0)&1)) << 4 | (((hi>>p1)&1)*2 | ((lo>>p1)&1)))
    return bytes(out)

def background_assets(memory):
    """Convert current DMG background VRAM into VDP tile/palette/name-table data."""
    lcdc=memory.io[0x40]; map_base=0x1C00 if lcdc&8 else 0x1800
    tiles=b"".join(md_tile(memory.vram[i*16:i*16+16]) for i in range(384))
    words=[]
    for y in range(32):
        for x in range(32):
            raw=memory.vram[map_base+y*32+x]
            tile=raw if lcdc&0x10 else 256+(raw if raw < 128 else raw-256)
            words.append(tile)
    return {"tiles":tiles, "plane_a":struct.pack(">1024H",*words), "cram":struct.pack(">4H",*DMG_CRAM),
            "scroll_x":memory.io[0x43], "scroll_y":memory.io[0x42]}
