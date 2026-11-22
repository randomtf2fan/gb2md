"""DMG background scanline oracle and native palette-pair lookup data.

This samples a whole line at fixed mode-3 end, not a pixel FIFO. Sprite/window
composition remains on the existing native renderer rather than this BG path.
"""

def palette_pair_table():
    return bytes((((bgp >> (2*a)) & 3) + 1) << 4 | (((bgp >> (2*b)) & 3) + 1)
                 for bgp in range(256) for a in range(4) for b in range(4))


def background_scanline(memory, y):
    if not 0 <= y < 144:raise ValueError('visible line required')
    lcdc=memory.io[0x40];palette=memory.io[0x47]
    if lcdc&0x22:raise ValueError('sprite/window raster composition not implemented')
    if not lcdc&0x80:return bytes(160)
    sy=(y+memory.io[0x42])&255;result=bytearray()
    base=0x1c00 if lcdc&8 else 0x1800
    for x in range(160):
        sx=(x+memory.io[0x43])&255
        tile=memory.vram[base+(sy//8)*32+sx//8]
        address=tile*16 if lcdc&16 else 0x1000+(tile if tile<128 else tile-256)*16
        lo=memory.vram[address+(sy%8)*2];hi=memory.vram[address+(sy%8)*2+1]
        bit=7-sx%8;colour=((hi>>bit)&1)*2+((lo>>bit)&1) if lcdc&1 else 0
        result.append((palette>>(colour*2))&3)
    return bytes(result)


def row_fingerprint(shades):
    if len(shades)!=160:raise ValueError('160 shades required')
    result=0
    for x in range(0,160,4):
        word=0
        for shade in shades[x:x+4]:
            if not 0<=shade<4:raise ValueError('DMG shade required')
            word=(word<<4)|(shade+1)
        result=(((result<<1)|(result>>31))^word)&0xffffffff
    return result
