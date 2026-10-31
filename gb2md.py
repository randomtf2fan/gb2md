#!/usr/bin/env python3
"""GB2MD: conservative LR35902 -> Motorola 68000 static-translation front end.

This tool intentionally does not distribute or embed a Game Boy ROM.  It reads a
ROM supplied by its owner and emits GNU m68k assembly plus a machine-readable
memory plan.  The assembly is a *native-code scaffold*: decoded basic blocks are
lowered to 68000 instructions and all Game Boy memory/I/O accesses go through a
small target runtime.  That boundary is essential because GB PPU, timers, MBCs,
and interrupts have no one-to-one Genesis address equivalent.
"""
from __future__ import annotations

import argparse, json, pathlib, struct
from collections import deque

GB_REGIONS = (
    (0x0000, 0x3FFF, "rom0", "source image; writes are MBC commands"),
    (0x4000, 0x7FFF, "romx", "source image selected by MBC"),
    (0x8000, 0x9FFF, "vram", "64 KiB Genesis VDP VRAM via a tile/map renderer"),
    (0xA000, 0xBFFF, "eram", "68k RAM/save backing; MBC-selected"),
    (0xC000, 0xDFFF, "wram", "68k work RAM, suggested $FF0000+$0000"),
    (0xE000, 0xFDFF, "echo", "alias of $C000-$DDFF; never allocate separately"),
    (0xFE00, 0xFE9F, "oam", "68k RAM shadow; converted to Genesis sprite table"),
    (0xFEA0, 0xFEFF, "unusable", "open-bus semantics"),
    (0xFF00, 0xFF7F, "io", "runtime services: joypad, timer, PPU, APU, IRQ"),
    (0xFF80, 0xFFFE, "hram", "68k RAM, suggested $FF2000+$0000"),
    (0xFFFF, 0xFFFF, "ie", "runtime interrupt-enable byte"),
)

# Cartridge type values needed by the initial implementation.  The value is
# hardware, not a filename convention: it decides how writes at $0000-$7FFF
# must be interpreted.
CARTRIDGES = {
    0x00: ("ROM ONLY", "none"), 0x01: ("MBC1", "mbc1"),
    0x02: ("MBC1+RAM", "mbc1"), 0x03: ("MBC1+RAM+BATTERY", "mbc1"),
    0x0F: ("MBC3+TIMER+BATTERY", "mbc3"),
    0x10: ("MBC3+TIMER+RAM+BATTERY", "mbc3"),
    0x11: ("MBC3", "mbc3"), 0x12: ("MBC3+RAM", "mbc3"),
    0x13: ("MBC3+RAM+BATTERY", "mbc3"),
    0x19: ("MBC5", "mbc5"), 0x1A: ("MBC5+RAM", "mbc5"),
    0x1B: ("MBC5+RAM+BATTERY", "mbc5"),
}
ROM_BANKS = {0x00: 2, 0x01: 4, 0x02: 8, 0x03: 16, 0x04: 32, 0x05: 64,
             0x06: 128, 0x07: 256, 0x08: 512, 0x52: 72, 0x53: 80, 0x54: 96}
RAM_BYTES = {0x00: 0, 0x01: 2 * 1024, 0x02: 8 * 1024, 0x03: 32 * 1024,
             0x04: 128 * 1024, 0x05: 64 * 1024}

def cartridge_profile(rom):
    """Validate header geometry and return the runtime configuration."""
    ctype, mapper = CARTRIDGES.get(rom[0x147], (f"UNKNOWN (${rom[0x147]:02X})", "unknown"))
    declared_banks = ROM_BANKS.get(rom[0x148])
    actual_banks = len(rom) // 0x4000
    warnings = []
    if len(rom) % 0x4000: warnings.append("ROM size is not a whole number of 16 KiB banks")
    if declared_banks is None: warnings.append(f"unrecognized ROM-size code ${rom[0x148]:02X}")
    elif declared_banks != actual_banks: warnings.append(f"header declares {declared_banks} banks; file has {actual_banks}")
    if mapper == "unknown": warnings.append("unsupported cartridge mapper")
    return {"cartridge_type": ctype, "cartridge_type_code": f"${rom[0x147]:02X}",
            "mapper": mapper, "rom_banks": actual_banks,
            "external_ram_bytes": RAM_BYTES.get(rom[0x149], None),
            "ram_size_code": f"${rom[0x149]:02X}", "warnings": warnings}

# Directly lowered forms. All remaining documented LR35902 opcodes are still
# decoded at their proper length and represented in IR; their semantic lowering
# is deliberately staged behind gb_execute_opcode rather than guessed.
OPS = {
    0x00:(1,"nop"), 0x3E:(2,"ld_a_d8"), 0x06:(2,"ld_b_d8"),
    0x0E:(2,"ld_c_d8"), 0x16:(2,"ld_d_d8"), 0x1E:(2,"ld_e_d8"),
    0x26:(2,"ld_h_d8"), 0x2E:(2,"ld_l_d8"), 0xEA:(3,"ld_a16_a"),
    0xFA:(3,"ld_a_a16"), 0xC3:(3,"jp"), 0x18:(2,"jr"), 0xCD:(3,"call"),
    0xC9:(1,"ret"), 0x76:(1,"halt"), 0xAF:(1,"xor_a"), 0x3C:(1,"inc_a"),
    0x3D:(1,"dec_a"), 0xF3:(1,"di"), 0xFB:(1,"ei"),
}
COND = {0xC2:"nz", 0xCA:"z", 0xD2:"nc", 0xDA:"c", 0xC4:"nz", 0xCC:"z", 0xD4:"nc", 0xDC:"c"}
for opcode in COND:
    OPS[opcode] = (3, "call_cc" if opcode & 4 else "jp_cc")

# Every documented base opcode has a deterministic encoded length.  Keeping
# this table independent of lowering prevents a partially implemented compiler
# from desynchronizing when it encounters, for example, LD r,d8 or CB r.
IMM8 = {0x06,0x0E,0x16,0x1E,0x26,0x2E,0x36,0x3E,0x10,
        0x18,0x20,0x28,0x30,0x38,0xC6,0xCE,0xD6,0xDE,
        0xE0,0xE6,0xE8,0xEE,0xF0,0xF6,0xF8,0xFE,0xCB}
IMM16 = {0x01,0x08,0x11,0x21,0x31,0xC2,0xC3,0xC4,0xCA,
         0xCC,0xCD,0xD2,0xD4,0xDA,0xDC,0xEA,0xFA}
COND_JR = {0x20:"nz", 0x28:"z", 0x30:"nc", 0x38:"c"}
COND_RET = {0xC0:"nz", 0xC8:"z", 0xD0:"nc", 0xD8:"c"}
RST = {0xC7,0xCF,0xD7,0xDF,0xE7,0xEF,0xF7,0xFF}

def instruction_length(op):
    if op in IMM8: return 2
    if op in IMM16: return 3
    return 1

def instruction_kind(op):
    if op in OPS: return OPS[op][1]
    if op in COND_JR: return "jr_cc"
    if op in COND_RET: return "ret_cc"
    if op == 0xD9: return "reti"
    if op == 0xE9: return "jp_hl"
    if op in RST: return "rst"
    if op == 0xCB: return "cb"
    return "generic"

def u16(rom, at): return rom[at] | (rom[at + 1] << 8)
def s8(v): return v - 256 if v & 0x80 else v

def decode_reachable(rom, entry):
    """Decode only reachable addresses in bank 0; return blocks and diagnostics."""
    pending, seen, insns, notes = deque([entry]), set(), {}, []
    while pending:
        pc = pending.popleft()
        while pc < min(len(rom), 0x4000) and pc not in seen:
            seen.add(pc); op = rom[pc]; size, kind = instruction_length(op), instruction_kind(op)
            if pc + size > len(rom): notes.append(f"truncated instruction at ${pc:04X}"); break
            arg = u16(rom, pc + 1) if size == 3 else (rom[pc + 1] if size == 2 else None)
            insns[pc] = (op, size, kind, arg)
            next_pc = pc + size
            if kind in ("jp", "jp_cc", "call", "call_cc"):
                target = arg
                if target < 0x4000: pending.append(target)
                else: notes.append(f"${pc:04X}: target ${target:04X} is banked/dynamic")
                if kind == "jp": break
            elif kind in ("jr", "jr_cc"):
                target = next_pc + s8(arg)
                if 0 <= target < 0x4000: pending.append(target)
                else: notes.append(f"${pc:04X}: JR leaves bank 0")
                if kind == "jr": break
            elif kind in ("ret", "reti", "halt", "jp_hl"): break
            elif kind == "rst": pending.append(op & 0x38)
            pc = next_pc
    return insns, notes

def emit_instruction(pc, op, size, kind, arg):
    p = f"L_gb_{pc:04X}:"
    if kind == "nop": body = "nop"
    elif kind.startswith("ld_") and kind.endswith("_d8"):
        reg = kind[3].lower()
        body = f"move.b #{arg:#04x},{'d0' if reg == 'a' else 'gb_' + reg}"
    elif kind == "ld_a16_a": body = f"move.w #{arg:#06x},d1\n\tjsr gb_write8 ; d0.b=A, d1.w=GB address"
    elif kind == "ld_a_a16": body = f"move.w #{arg:#06x},d1\n\tjsr gb_read8 ; d1.w=GB address, returns A in d0.b"
    elif kind == "xor_a": body = "clr.b d0"
    elif kind == "inc_a": body = "addq.b #1,d0"
    elif kind == "dec_a": body = "subq.b #1,d0"
    elif kind == "di": body = "clr.b gb_ime"
    elif kind == "ei": body = "move.b #1,gb_ime"
    elif kind == "jp": body = f"bra.w L_gb_{arg:04X}"
    elif kind == "jr": body = f"bra.w L_gb_{pc + size + s8(arg):04X}"
    elif kind == "call": body = f"bsr.w L_gb_{arg:04X}"
    elif kind == "ret": body = "rts"
    elif kind == "halt": body = "jsr gb_halt\n\tbra.w L_gb_%04X" % pc
    elif kind in ("jp_cc", "call_cc"):
        # GB flag layout differs from 68k CCR, so the runtime owns exact tests.
        body = f"move.b #{op:#04x},d1\n\tmove.w #{arg:#06x},d2\n\tjsr gb_conditional_transfer"
    else: body = f"move.w #{pc:#06x},d0\n\tmove.b #{op:#04x},d1\n\tjsr gb_execute_opcode ; staged LR35902 lowering"
    return f"{p}\n\t{body}\n"

def main():
    ap = argparse.ArgumentParser(description="Generate a conservative native 68000 translation scaffold.")
    ap.add_argument("rom", type=pathlib.Path, help="legally obtained .gb ROM")
    ap.add_argument("--out", type=pathlib.Path, default=pathlib.Path("build"))
    ap.add_argument("--entry", type=lambda x: int(x, 0), default=0x100)
    ap.add_argument("--emit-title-rom", action="store_true", help="emit a bootable Genesis title-screen ROM using the GB header title")
    ns = ap.parse_args()
    rom = ns.rom.read_bytes()
    if len(rom) < 0x150: raise SystemExit("input is too small to be a Game Boy ROM")
    ns.out.mkdir(parents=True, exist_ok=True)
    insns, notes = decode_reachable(rom, ns.entry)
    title = rom[0x134:0x144].split(b"\0", 1)[0].decode("ascii", "replace")
    profile = cartridge_profile(rom)
    report = {"input": str(ns.rom), "title": title, "size": len(rom), "entry": ns.entry,
              "cartridge": profile,
              "decoded_bank0_instructions": len(insns), "diagnostics": notes,
              "ir": [{"address": f"${pc:04X}", "opcode": f"${op:02X}", "size": size, "kind": kind,
                      "operand": None if arg is None else f"${arg:04X}"}
                     for pc,(op,size,kind,arg) in sorted(insns.items())],
              "gb_memory_map": [{"range":f"${a:04X}-${b:04X}","region":n,"target":d} for a,b,n,d in GB_REGIONS]}
    (ns.out / "memory-plan.json").write_text(json.dumps(report, indent=2) + "\n")
    lines = ["; Generated by gb2md.py. Assemble with a 68000 GNU-compatible assembler.",
             ".cpu 68000", ".text", ".globl gb_entry", ".extern gb_read8, gb_write8, gb_halt, gb_execute_opcode, gb_conditional_transfer", ".extern gb_ime, gb_b, gb_c, gb_d, gb_e, gb_h, gb_l", "gb_entry:", f"\tbra.w L_gb_{ns.entry:04X}", ""]
    for pc in sorted(insns): lines.append(emit_instruction(pc, *insns[pc]))
    lines += ["; Original ROM is deliberately not copied into the output. Provide assets separately."]
    (ns.out / "translated_bank0.s").write_text("\n".join(lines) + "\n")
    if ns.emit_title_rom:
        from build_title_demo import emit_title_rom
        result = emit_title_rom(ns.out / "title_screen.md", title)
        print(f"wrote {ns.out/'title_screen.md'} ({result['size']} bytes; native Genesis title screen)")
    print(f"wrote {ns.out/'translated_bank0.s'} and memory-plan.json ({len(insns)} decoded instructions)")

if __name__ == "__main__": main()
