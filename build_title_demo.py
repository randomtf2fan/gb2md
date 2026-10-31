#!/usr/bin/env python3
"""Build a self-contained 68000 Genesis title-screen smoke-test ROM."""
from __future__ import annotations
import argparse, pathlib, struct

VDP_DATA, VDP_CTRL = 0xC00000, 0xC00004
# 5x7 glyphs expanded into 8x8 4bpp Genesis tiles. This keeps the title-ROM
# path independent of copyrighted game graphics while handling normal ASCII
# cartridge titles (A-Z, 0-9, space, dash, question mark).
FONT5 = {
 "A":"01110/10001/10001/11111/10001/10001/10001", "B":"11110/10001/10001/11110/10001/10001/11110",
 "C":"01111/10000/10000/10000/10000/10000/01111", "D":"11110/10001/10001/10001/10001/10001/11110",
 "E":"11111/10000/10000/11110/10000/10000/11111", "F":"11111/10000/10000/11110/10000/10000/10000",
 "G":"01111/10000/10000/10111/10001/10001/01111", "H":"10001/10001/10001/11111/10001/10001/10001",
 "I":"11111/00100/00100/00100/00100/00100/11111", "J":"00001/00001/00001/00001/10001/10001/01110",
 "K":"10001/10010/10100/11000/10100/10010/10001", "L":"10000/10000/10000/10000/10000/10000/11111",
 "M":"10001/11011/10101/10101/10001/10001/10001", "N":"10001/11001/10101/10011/10001/10001/10001",
 "O":"01110/10001/10001/10001/10001/10001/01110", "P":"11110/10001/10001/11110/10000/10000/10000",
 "Q":"01110/10001/10001/10001/10101/10010/01101", "R":"11110/10001/10001/11110/10100/10010/10001",
 "S":"01111/10000/10000/01110/00001/00001/11110", "T":"11111/00100/00100/00100/00100/00100/00100",
 "U":"10001/10001/10001/10001/10001/10001/01110", "V":"10001/10001/10001/10001/10001/01010/00100",
 "W":"10001/10001/10001/10101/10101/10101/01010", "X":"10001/10001/01010/00100/01010/10001/10001",
 "Y":"10001/10001/01010/00100/00100/00100/00100", "Z":"11111/00001/00010/00100/01000/10000/11111",
 "0":"01110/10001/10011/10101/11001/10001/01110", "1":"00100/01100/00100/00100/00100/00100/01110",
 "2":"01110/10001/00001/00010/00100/01000/11111", "3":"11110/00001/00001/01110/00001/00001/11110",
 "4":"00010/00110/01010/10010/11111/00010/00010", "5":"11111/10000/10000/11110/00001/00001/11110",
 "6":"01110/10000/10000/11110/10001/10001/01110", "7":"11111/00001/00010/00100/01000/01000/01000",
 "8":"01110/10001/10001/01110/10001/10001/01110", "9":"01110/10001/10001/01111/00001/00001/01110",
 "-":"00000/00000/00000/11111/00000/00000/00000", "?":"01110/10001/00001/00010/00100/00000/00100",
}
def glyph(ch):
    if ch == " ": return [0] * 8
    rows = FONT5.get(ch, FONT5["?"]).split("/")
    return [0] + [sum((bit == "1") << (6 - i) for i,bit in enumerate(row)) for row in rows]

def vram_write_command(address):
    return 0x40000000 | ((address & 0x3FFF) << 16) | ((address & 0xC000) >> 14)

def tile(rows):
    out = bytearray()
    for row in rows:
        for pair in range(4): out.append((((row >> (7-pair*2)) & 1) << 4) | ((row >> (6-pair*2)) & 1))
    return out

def put_string(buf, off, size, text): buf[off:off+size] = text.encode("ascii")[:size].ljust(size, b" ")

def emit_title_rom(output: pathlib.Path, title="POKEMON RED"):
    text = "".join(ch if ch in FONT5 or ch == " " else "?" for ch in title.upper())[:28] or "GAME BOY ROM"
    chars = [" "] + sorted(set(text) - {" "})
    index = {ch:n for n,ch in enumerate(chars)}; tiles = b"".join(tile(glyph(ch)) for ch in chars); map_words = [index[ch] for ch in text]
    code = bytearray()
    def w(v): code.extend(struct.pack(">H", v & 0xFFFF))
    def l(v): code.extend(struct.pack(">I", v & 0xFFFFFFFF))
    def mwa(v,a): w(0x33FC); w(v); l(a)
    def mla(v,a): w(0x23FC); l(v); l(a)
    def lea(reg,a): w(0x41F9 | (reg << 9)); l(a)
    def dbra(reg,target):
        # DBcc's displacement is relative to the extension word (PC after the
        # opcode), not the address following the extension word.
        here=len(code); w(0x51C8|reg); w(target-(here+2))
    w(0x46FC); w(0x2700)
    for value in (0x8004,0x8104,0x8230,0x833C,0x8407,0x8578,0x8700,0x8B00,0x8C81,0x8D3F,0x8F02,0x9001): mwa(value,VDP_CTRL)
    mla(vram_write_command(0),VDP_CTRL); lea(0,VDP_DATA); w(0x303C); w(0x7FFF)
    clear=len(code); w(0x30BC); w(0); dbra(0,clear)
    mla(0xC0000000,VDP_CTRL); mwa(0,VDP_DATA); mwa(0x0EEE,VDP_DATA)
    mla(vram_write_command(0),VDP_CTRL); font_fix=len(code)+2; lea(1,0); w(0x303C); w(len(tiles)//2-1)
    copy=len(code); w(0x3099); dbra(0,copy)
    vram_address=0xC000+2*(12*64+(64-len(map_words))//2); mla(vram_write_command(vram_address),VDP_CTRL); map_fix=len(code)+2; lea(1,0); w(0x303C); w(len(map_words)-1)
    copy=len(code); w(0x3099); dbra(0,copy); mwa(0x8174,VDP_CTRL); w(0x60FE)
    font_addr=0x200+len(code); map_addr=font_addr+len(tiles)
    struct.pack_into(">I",code,font_fix,font_addr); struct.pack_into(">I",code,map_fix,map_addr)
    image=bytearray(max(0x4000,0x200+len(code)+len(tiles)+2*len(map_words)))
    struct.pack_into(">II",image,0,0x00FF0000,0x200); image[0x100:0x110]=b"SEGA GENESIS    "
    put_string(image,0x120,48,"GB2MD Pokemon Red title-screen bring-up"); put_string(image,0x150,48,"GB2MD Pokemon Red title-screen bring-up"); put_string(image,0x180,14,"GM 00000000-00"); image[0x1F0:0x1F3]=b"JUE"
    image[0x200:0x200+len(code)]=code; image[font_addr:font_addr+len(tiles)]=tiles
    for n,word in enumerate(map_words): struct.pack_into(">H",image,map_addr+n*2,word)
    checksum=sum(struct.unpack_from(">H",image,i)[0] for i in range(0x200,len(image),2))&0xFFFF; struct.pack_into(">H",image,0x18E,checksum)
    output.parent.mkdir(parents=True,exist_ok=True); output.write_bytes(image); return {"size":len(image),"checksum":checksum,"text":text}

def main():
    p=argparse.ArgumentParser(); p.add_argument("--out",type=pathlib.Path,default=pathlib.Path("build/pokemon_red_title_demo.md")); p.add_argument("--title",default="POKEMON RED"); ns=p.parse_args(); result=emit_title_rom(ns.out,ns.title); print(f"wrote {ns.out} ({result['size']} bytes, checksum ${result['checksum']:04X})")
if __name__ == "__main__": main()
