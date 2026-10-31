#!/usr/bin/env python3
"""Trace-guided static LR35902 block emitter.

Each discovered Game Boy PC gets a distinct 68000 label and semantic micro-op
call. The target runtime owns registers/flags/memory and dispatches `gb_pc` to
the next compiled block. This is the bridge from the validated Python oracle to
a native 68000 recompiler; no source ROM bytes are placed in the output.
"""
from __future__ import annotations
import argparse, collections, copy, hashlib, json, pathlib, re, struct
from gb_cpu import CPU, Memory, instruction_cycles
from lr35902_lowering import family
from gb2md import instruction_length

REGS=("gb_b","gb_c","gb_d","gb_e","gb_h","gb_l",None,"gb_a")
REGS16=("gb_b","gb_d","gb_h","gb_sp")
BUTTON_STATES={"right":0xFE,"left":0xFD,"up":0xFB,"down":0xF7,
               "a":0xEF,"b":0xDF,"select":0xBF,"start":0x7F}
AUTO_INPUT_ACTIONS=list(BUTTON_STATES.items())+[
    (f"{button}|{direction}",BUTTON_STATES[button]&BUTTON_STATES[direction])
    for button in ("a","b") for direction in ("right","left","up","down")
]+[("start|a",BUTTON_STATES["start"]&BUTTON_STATES["a"]),
   ("select|start",BUTTON_STATES["select"]&BUTTON_STATES["start"])]
SCHEDULER_BATCH_T_CYCLES=200

def reads_joypad(cpu, memory):
    """Conservatively identify an instruction whose read address is FF00."""
    pc=cpu.pc;op=memory.read(pc)
    if op==0xF0:return memory.read((pc+1)&0xFFFF)==0
    if op==0xFA:return memory.read((pc+1)&0xFFFF)|(memory.read((pc+2)&0xFFFF)<<8)==0xFF00
    if op==0xF2:return cpu.c==0
    if op==0x0A:return cpu.bc()==0xFF00
    if op==0x1A:return cpu.de()==0xFF00
    if op in (0x2A,0x3A):return cpu.hl()==0xFF00
    if cpu.hl()!=0xFF00:return False
    return (0x40<=op<0xC0 and (op&7)==6) or op in (0x34,0x35,0xCB)

def exploration_state_key(cpu):
    """Hash state that can affect future execution, excluding source ROM bytes."""
    memory=cpu.m;digest=hashlib.blake2b(digest_size=20)
    digest.update(struct.pack(">8B2H5B",cpu.a,cpu.f,cpu.b,cpu.c,cpu.d,cpu.e,cpu.h,cpu.l,
                              cpu.sp,cpu.pc,cpu.ime,cpu.halted,cpu.ei_delay,cpu.halt_bug,memory.ie))
    digest.update(struct.pack(">5I",memory.rom_bank,memory.ram_bank,memory.ram_enabled,
                              memory.mbc1_mode,memory.cycles%70224))
    digest.update(struct.pack(">3I",memory.div_counter,memory.timer_reload_delay,
                              memory.timer_reloaded_this_cycle))
    for region in (memory.vram,memory.wram,memory.oam,memory.hram,memory.io,memory.eram):digest.update(region)
    return digest.digest()

def parse_input_script(spec: str):
    """Parse controller pulses and optional generic trace-memory events.

    Memory syntax is ``poke:0xSTART[-0xEND]=VALUE@FRAME``. It modifies only
    reference discovery state; generated ROMs never replay the poke.
    """
    events=[];memory_events=[]
    for item in filter(None,(part.strip() for part in spec.split(","))):
        if item.lower().startswith("poke:"):
            try:
                assignment,frame_text=item[5:].split("@",1)
                range_text,value_text=assignment.split("=",1)
                bounds=range_text.split("-",1);start=int(bounds[0],0);end=int(bounds[-1],0)
                frame=int(frame_text,0);value=int(value_text,0)
            except ValueError as exc:
                raise ValueError(f"invalid trace poke {item!r}; expected poke:0xCA22-0xCA2B=0x8C@850") from exc
            if not (0<=start<=end<=0xFFFF and 0<=value<=0xFF and frame>=0):raise ValueError("trace poke is out of range")
            memory_events.append((frame,start,end,value));continue
        try:names,window=item.split("@",1);start_text,duration_text=window.split(":",1)
        except ValueError as exc:raise ValueError(f"invalid input pulse {item!r}; expected start@512:8") from exc
        state=0xFF
        for name in names.lower().split("|"):
            if name not in BUTTON_STATES:raise ValueError(f"unknown GB button {name!r}")
            state &= BUTTON_STATES[name]
        start=int(start_text,0);duration=int(duration_text,0)
        if start<0 or duration<=0:raise ValueError("input frame and duration must be positive")
        events.append((start,start+duration,state))
    if not events and not memory_events:raise ValueError("input script contains no events")
    return {"name":spec,"events":events,"memory_events":memory_events}
def native_body(block):
    """Return direct 68000 statements for semantics already safe to lower."""
    op,operand,pc,bank=block["opcode"],block["operand"],block["pc"],block["bank"]
    nextpc=(pc+len(bytes.fromhex(block["bytes"])))&0xFFFF; fam=block["family"]
    body=[]
    stem=f"B{bank:03X}_{pc:04X}"
    taken_cost=instruction_cycles(op,operand,True)
    def push_word(value_setup):
        return value_setup + ["move.w gb_sp,d1","subq.w #2,d1","move.w d1,gb_sp","move.l d1,d4","addq.w #1,d1",
                              "move.l d3,d0","lsr.w #8,d0","jsr gb_write8","move.l d4,d1","move.l d3,d0","jsr gb_write8"]
    def pop_word():
        return ["moveq #0,d1","move.w gb_sp,d1","jsr gb_read8","moveq #0,d3","move.b d0,d3","moveq #0,d1","move.w gb_sp,d1","addq.w #1,d1",
                "jsr gb_read8","lsl.w #8,d0","or.w d0,d3","addq.w #2,gb_sp"]
    def load_r_d3(index):
        if index==6:return ["moveq #0,d1","move.w gb_h,d1","jsr gb_read8","moveq #0,d3","move.b d0,d3"]
        return ["moveq #0,d3",f"move.b {REGS[index]},d3"]
    def finish_logic(flagbase=0):
        return ["move.b d0,gb_a",f"moveq #${flagbase:02X},d1","tst.b d0",f"bne.s .logicnz_{stem}","ori.b #$80,d1",f".logicnz_{stem}:","move.b d1,gb_f"]
    if fam=="NOP": pass
    elif fam=="LD_R_D8" and ((op>>3)&7)!=6: body.append(f"move.b #${operand&255:02X},{REGS[(op>>3)&7]}")
    elif fam=="LD_R_D8": body += ["moveq #0,d0",f"move.b #${operand&255:02X},d0","moveq #0,d1","move.w gb_h,d1","jsr gb_write8"]
    elif fam=="LD_R_R" and ((op>>3)&7)!=6 and (op&7)!=6: body.append(f"move.b {REGS[op&7]},{REGS[(op>>3)&7]}")
    elif fam=="LD_R_R" and ((op>>3)&7)==6:
        body += ["moveq #0,d0",f"move.b {REGS[op&7]},d0","moveq #0,d1","move.w gb_h,d1","jsr gb_write8"]
    elif fam=="LD_R_R" and (op&7)==6:
        body += ["moveq #0,d1","move.w gb_h,d1","jsr gb_read8",f"move.b d0,{REGS[(op>>3)&7]}"]
    elif fam=="LD_RR_D16": body.append(f"move.w #${operand:04X},{REGS16[(op>>4)&3]}")
    elif fam=="INC_RR": body.append(f"addq.w #1,{REGS16[(op>>4)&3]}")
    elif fam=="DEC_RR": body.append(f"subq.w #1,{REGS16[(op>>4)&3]}")
    elif fam=="LD_SP_HL": body.append("move.w gb_h,gb_sp")
    elif fam=="LD_A16_SP":
        body += ["moveq #0,d3","move.w gb_sp,d3",f"move.l #${operand:04X},d1","move.l d3,d0","jsr gb_write8",
                 f"move.l #${(operand+1)&0xFFFF:04X},d1","move.l d3,d0","lsr.w #8,d0","jsr gb_write8"]
    elif fam in ("ADD_SP_R8","LD_HL_SP_R8"):
        # H and C use the unsigned low nibble/byte additions even though the
        # displacement is sign-extended for the 16-bit result. Z and N clear.
        value=operand&255
        body += ["moveq #0,d0","move.w gb_sp,d0","moveq #0,d1",
                 "move.w d0,d2","andi.w #$000F,d2",f"addi.w #${value&15:02X},d2",
                 "cmpi.w #$000F,d2",f"bls.s .spr8_nohalf_{stem}","ori.b #$20,d1",f".spr8_nohalf_{stem}:",
                 "move.w d0,d2","andi.w #$00FF,d2",f"addi.w #${value:02X},d2",
                 "cmpi.w #$00FF,d2",f"bls.s .spr8_nocarry_{stem}","ori.b #$10,d1",f".spr8_nocarry_{stem}:",
                 "moveq #0,d3",f"move.b #${value:02X},d3","ext.w d3","add.w d3,d0",
                 f"move.w d0,{'gb_sp' if fam=='ADD_SP_R8' else 'gb_h'}","move.b d1,gb_f"]
    elif fam=="DI": body += ["clr.b gb_ime","clr.b gb_ei_delay"]
    elif fam=="EI":
        body += ["tst.b gb_ime",f"bne.s .ei_done_{stem}","tst.b gb_ei_delay",f"bne.s .ei_done_{stem}","move.b #2,gb_ei_delay",f".ei_done_{stem}:"]
    elif fam=="HALT": body.append("move.b #1,gb_halted")
    elif fam=="XOR_A_R" and (op&7)==7: body += ["clr.b gb_a","move.b #$80,gb_f"]
    elif fam in ("AND_A_R","OR_A_R","XOR_A_R"):
        body += load_r_d3(op&7)+["moveq #0,d0","move.b gb_a,d0"]
        body += [{"AND_A_R":"and.b d3,d0","OR_A_R":"or.b d3,d0","XOR_A_R":"eor.b d3,d0"}[fam]]+finish_logic(0x20 if fam=="AND_A_R" else 0)
    elif fam in ("AND_A_D8","OR_A_D8","XOR_A_D8"):
        body += ["moveq #0,d0","move.b gb_a,d0",f"{ {'AND_A_D8':'and','OR_A_D8':'or','XOR_A_D8':'eor'}[fam] }.b #${operand&255:02X},d0"]+finish_logic(0x20 if fam=="AND_A_D8" else 0)
    elif fam=="CPL": body += ["not.b gb_a","move.b gb_f,d0","ori.b #$60,d0","move.b d0,gb_f"]
    elif fam=="SCF":
        body += ["move.b gb_f,d0","andi.b #$80,d0","ori.b #$10,d0","move.b d0,gb_f"]
    elif fam=="CCF":
        body += ["moveq #0,d0","move.b gb_f,d0","move.b d0,d1","andi.b #$80,d0","eori.b #$10,d1","andi.b #$10,d1","or.b d1,d0","move.b d0,gb_f"]
    elif fam=="DAA":
        # LR35902 decimal adjust. Preserve N, recompute Z/H, and retain or set
        # C according to the pre-adjust accumulator and flags.
        body += ["moveq #0,d0","move.b gb_a,d0","moveq #0,d1","move.b gb_f,d1",
                 "moveq #0,d2","moveq #0,d3","move.b d1,d3","andi.b #$10,d3",
                 f"btst #6,d1",f"bne.s .daa_sub_{stem}",
                 "move.b d0,d4","andi.w #$000F,d4","cmpi.b #$09,d4",f"bhi.s .daa_add_six_{stem}",
                 "btst #5,d1",f"beq.s .daa_add_high_{stem}",f".daa_add_six_{stem}:","ori.b #$06,d2",
                 f".daa_add_high_{stem}:","tst.b d3",f"bne.s .daa_add_sixty_{stem}",
                 "cmpi.b #$99,d0",f"bls.s .daa_apply_add_{stem}",f".daa_add_sixty_{stem}:",
                 "ori.b #$60,d2","moveq #$10,d3",f".daa_apply_add_{stem}:","add.b d2,d0",
                 f"bra.s .daa_flags_{stem}",f".daa_sub_{stem}:","btst #5,d1",f"beq.s .daa_sub_high_{stem}",
                 "ori.b #$06,d2",f".daa_sub_high_{stem}:","tst.b d3",f"beq.s .daa_apply_sub_{stem}",
                 "ori.b #$60,d2",f".daa_apply_sub_{stem}:","sub.b d2,d0",f".daa_flags_{stem}:",
                 "andi.b #$40,d1","or.b d3,d1","tst.b d0",f"bne.s .daa_nonzero_{stem}",
                 "ori.b #$80,d1",f".daa_nonzero_{stem}:","move.b d0,gb_a","move.b d1,gb_f"]
    elif fam in ("ADD_A_R","ADC_A_R","SUB_A_R","SBC_A_R","CP_A_R"):
        subtract=fam in ("SUB_A_R","SBC_A_R","CP_A_R"); with_carry=fam in ("ADC_A_R","SBC_A_R")
        body += load_r_d3(op&7)+["moveq #0,d0","move.b gb_a,d0","moveq #0,d5"]
        if with_carry: body += ["move.b gb_f,d5","lsr.b #4,d5","andi.w #1,d5"]
        body += ["moveq #0,d1"]
        if subtract:
            body += ["ori.b #$40,d1","move.w d0,d2","andi.w #$000F,d2","move.w d3,d4","andi.w #$000F,d4","add.w d5,d4","cmp.w d4,d2",f"bhs.s .subnohalf_{stem}","ori.b #$20,d1",f".subnohalf_{stem}:","move.w d3,d4","add.w d5,d4","cmp.w d4,d0",f"bhs.s .subnocarry_{stem}","ori.b #$10,d1",f".subnocarry_{stem}:","sub.w d3,d0","sub.w d5,d0"]
        else:
            body += ["move.w d0,d2","andi.w #$000F,d2","move.w d3,d4","andi.w #$000F,d4","add.w d5,d4","add.w d4,d2","cmpi.w #$000F,d2",f"bls.s .addnohalf_{stem}","ori.b #$20,d1",f".addnohalf_{stem}:","add.w d3,d0","add.w d5,d0","cmpi.w #$00FF,d0",f"bls.s .addnocarry_{stem}","ori.b #$10,d1",f".addnocarry_{stem}:"]
        body += ["tst.b d0",f"bne.s .alunonzero_{stem}","ori.b #$80,d1",f".alunonzero_{stem}:"]
        if fam!="CP_A_R":body.append("move.b d0,gb_a")
        body.append("move.b d1,gb_f")
    elif fam in ("ADD_A_D8","ADC_A_D8","SUB_A_D8","SBC_A_D8"):
        subtract=fam in ("SUB_A_D8","SBC_A_D8");with_carry=fam in ("ADC_A_D8","SBC_A_D8");value=operand&255
        body += ["moveq #0,d0","move.b gb_a,d0","moveq #0,d5"]
        if with_carry:body += ["move.b gb_f,d5","lsr.b #4,d5","andi.w #1,d5"]
        body += ["moveq #0,d1"]
        if subtract:
            body += ["ori.b #$40,d1","move.w d0,d2","andi.w #$000F,d2",f"move.w #${value&15:02X},d4","add.w d5,d4","cmp.w d4,d2",f"bhs.s .subihalfok_{stem}","ori.b #$20,d1",f".subihalfok_{stem}:",f"move.w #${value:02X},d4","add.w d5,d4","cmp.w d4,d0",f"bhs.s .subicarryok_{stem}","ori.b #$10,d1",f".subicarryok_{stem}:","sub.w d4,d0"]
        else:
            body += ["move.w d0,d2","andi.w #$000F,d2",f"addi.w #${value&15:02X},d2","add.w d5,d2","cmpi.w #$000F,d2",f"bls.s .addihalfok_{stem}","ori.b #$20,d1",f".addihalfok_{stem}:",f"addi.w #${value:02X},d0","add.w d5,d0","cmpi.w #$00FF,d0",f"bls.s .addicarryok_{stem}","ori.b #$10,d1",f".addicarryok_{stem}:"]
        body += ["tst.b d0",f"bne.s .aluinonzero_{stem}","ori.b #$80,d1",f".aluinonzero_{stem}:","move.b d0,gb_a","move.b d1,gb_f"]
    elif fam=="ADD_HL_RR":
        source=REGS16[(op>>4)&3]
        body += ["moveq #0,d0","move.w gb_h,d0","moveq #0,d3",f"move.w {source},d3","moveq #0,d1","move.b gb_f,d1","andi.b #$80,d1",
                 "move.l d0,d2","andi.l #$00000FFF,d2","move.l d3,d4","andi.l #$00000FFF,d4","add.l d4,d2","cmpi.l #$00000FFF,d2",f"bls.s .hlnohalf_{stem}","ori.b #$20,d1",f".hlnohalf_{stem}:",
                 "add.l d3,d0","cmpi.l #$0000FFFF,d0",f"bls.s .hlnocarry_{stem}","ori.b #$10,d1",f".hlnocarry_{stem}:","move.w d0,gb_h","move.b d1,gb_f"]
    elif fam=="ROT_A":
        kind=(op>>3)&3
        body += ["moveq #0,d3","move.b gb_a,d3","moveq #0,d0"]
        if kind==0:body += ["move.b d3,d0","lsr.b #7,d0","rol.b #1,d3"]
        elif kind==1:body += ["move.b d3,d0","andi.b #1,d0","ror.b #1,d3"]
        elif kind==2:body += ["moveq #0,d2","move.b gb_f,d2","lsr.b #4,d2","andi.b #1,d2","move.b d3,d0","lsr.b #7,d0","lsl.b #1,d3","or.b d2,d3"]
        else:body += ["moveq #0,d2","move.b gb_f,d2","andi.b #$10,d2","lsl.b #3,d2","move.b d3,d0","andi.b #1,d0","lsr.b #1,d3","or.b d2,d3"]
        body += ["moveq #0,d1","tst.b d0",f"beq.s .rotanocarry_{stem}","ori.b #$10,d1",f".rotanocarry_{stem}:","move.b d3,gb_a","move.b d1,gb_f"]
    elif fam=="CB":
        sub=operand&255; group=sub>>6; reg=sub&7; bit=(sub>>3)&7
        if group==1:
            body += load_r_d3(reg)+["moveq #$20,d1","moveq #0,d0","move.b gb_f,d0","andi.b #$10,d0","or.b d0,d1",f"btst #{bit},d3",f"bne.s .bitset_{stem}","ori.b #$80,d1",f".bitset_{stem}:","move.b d1,gb_f"]
        elif group in (2,3):
            body += load_r_d3(reg)+[f"{'bset' if group==3 else 'bclr'} #{bit},d3"]
            if reg==6: body += ["moveq #0,d0","move.b d3,d0","moveq #0,d1","move.w gb_h,d1","jsr gb_write8"]
            else: body += [f"move.b d3,{REGS[reg]}"]
        else:
            kind=(sub>>3)&7
            body += load_r_d3(reg)+["moveq #0,d0"]
            if kind==0:body += ["move.b d3,d0","lsr.b #7,d0","rol.b #1,d3"]
            elif kind==1:body += ["move.b d3,d0","andi.b #1,d0","ror.b #1,d3"]
            elif kind==2:body += ["moveq #0,d2","move.b gb_f,d2","lsr.b #4,d2","andi.b #1,d2","move.b d3,d0","lsr.b #7,d0","lsl.b #1,d3","or.b d2,d3"]
            elif kind==3:body += ["moveq #0,d2","move.b gb_f,d2","andi.b #$10,d2","lsl.b #3,d2","move.b d3,d0","andi.b #1,d0","lsr.b #1,d3","or.b d2,d3"]
            elif kind==4:body += ["move.b d3,d0","lsr.b #7,d0","lsl.b #1,d3"]
            elif kind==5:body += ["move.b d3,d0","andi.b #1,d0","asr.b #1,d3"]
            elif kind==6:body += ["move.b d3,d2","lsl.b #4,d3","lsr.b #4,d2","or.b d2,d3"]
            else:body += ["move.b d3,d0","andi.b #1,d0","lsr.b #1,d3"]
            body += ["moveq #0,d1","tst.b d3",f"bne.s .cbnonzero_{stem}","ori.b #$80,d1",f".cbnonzero_{stem}:","tst.b d0",f"beq.s .cbnocarry_{stem}","ori.b #$10,d1",f".cbnocarry_{stem}:","move.b d1,gb_f"]
            if reg==6:body += ["moveq #0,d0","move.b d3,d0","moveq #0,d1","move.w gb_h,d1","jsr gb_write8"]
            else:body += [f"move.b d3,{REGS[reg]}"]
    elif fam=="CP_A_D8":
        value=operand&255
        body += ["moveq #0,d0","move.b gb_a,d0","moveq #$40,d1","move.b d0,d2","andi.b #$0F,d2",
                 f"cmpi.b #${value&15:02X},d2",f"bhs.s .nohalf_{stem}","ori.b #$20,d1",f".nohalf_{stem}:",
                 f"cmpi.b #${value:02X},d0",f"bhi.s .donecp_{stem}",f"bne.s .carry_{stem}","ori.b #$80,d1",f"bra.s .donecp_{stem}",
                 f".carry_{stem}:","ori.b #$10,d1",f".donecp_{stem}:","move.b d1,gb_f"]
    elif fam in ("INC_R","DEC_R") and ((op>>3)&7)!=6:
        reg=REGS[(op>>3)&7]; half_branch="bne.s" if fam=="DEC_R" else "bne.s"
        half_expected=0 if fam=="DEC_R" else 15
        body += [f"moveq #0,d0",f"move.b {reg},d0","moveq #$10,d1","and.b gb_f,d1",f"ori.b #${0x40 if fam=='DEC_R' else 0:02X},d1",
                 "move.b d0,d2","andi.b #$0F,d2",f"cmpi.b #${half_expected:02X},d2",f"{half_branch} .nohalf_{stem}","ori.b #$20,d1",f".nohalf_{stem}:",
                 f"{'subq' if fam=='DEC_R' else 'addq'}.b #1,d0",f"bne.s .nozero_{stem}","ori.b #$80,d1",f".nozero_{stem}:",f"move.b d0,{reg}","move.b d1,gb_f"]
    elif fam in ("INC_R","DEC_R"):
        half_expected=0 if fam=="DEC_R" else 15
        body += ["moveq #0,d1","move.w gb_h,d1","jsr gb_read8","move.b d0,d3","moveq #$10,d1","and.b gb_f,d1",f"ori.b #${0x40 if fam=='DEC_R' else 0:02X},d1",
                 "move.b d3,d2","andi.b #$0F,d2",f"cmpi.b #${half_expected:02X},d2",f"bne.s .nohalf_{stem}","ori.b #$20,d1",f".nohalf_{stem}:",
                 f"{'subq' if fam=='DEC_R' else 'addq'}.b #1,d3",f"bne.s .nozero_{stem}","ori.b #$80,d1",f".nozero_{stem}:","move.b d1,gb_f",
                 "moveq #0,d0","move.b d3,d0","moveq #0,d1","move.w gb_h,d1","jsr gb_write8"]
    elif fam=="LD_RR_A":
        pair=(op>>4)&3; addr=REGS16[2 if pair==3 else pair]
        body += ["moveq #0,d0","move.b gb_a,d0","moveq #0,d1",f"move.w {addr},d1","jsr gb_write8"]
        if op==0x22: body.append("addq.w #1,gb_h")
        elif op==0x32: body.append("subq.w #1,gb_h")
    elif fam in ("LDH_A8_A","LD_A16_A","LDH_C_A"):
        if fam=="LDH_A8_A": address=0xFF00+(operand&255); body += [f"move.l #${address:04X},d1"]
        elif fam=="LD_A16_A": body += [f"move.l #${operand:04X},d1"]
        else: body += ["moveq #0,d1","move.b gb_c,d1","ori.w #$FF00,d1"]
        body += ["moveq #0,d0","move.b gb_a,d0","jsr gb_write8"]
    elif fam in ("LDH_A_A8","LDH_A_C","LD_A_A16","LD_A_RR"):
        if fam=="LDH_A_A8": body += [f"move.l #${0xFF00+(operand&255):04X},d1"]
        elif fam=="LDH_A_C": body += ["moveq #0,d1","move.b gb_c,d1","ori.w #$FF00,d1"]
        elif fam=="LD_A_A16": body += [f"move.l #${operand:04X},d1"]
        else:
            pair=(op>>4)&3; addr=REGS16[2 if pair==3 else pair]; body += ["moveq #0,d1",f"move.w {addr},d1"]
        body += ["jsr gb_read8","move.b d0,gb_a"]
        if op==0x2A: body.append("addq.w #1,gb_h")
        elif op==0x3A: body.append("subq.w #1,gb_h")
    elif fam=="JP":
        nextpc=operand
        body.append("move.w gb_rom_bank,gb_bank" if 0x4000<=operand<0x8000 else "clr.w gb_bank")
    elif fam=="JP_CC":
        target=operand; cond=(op>>3)&3; bit=7 if cond<2 else 4
        branch=("beq.s","bne.s","beq.s","bne.s")[cond]
        body += [f"move.w #${nextpc:04X},gb_pc",f"btst #{bit},gb_f",f"{branch} .jptaken_{stem}","jmp gb_dispatch",f".jptaken_{stem}:",f"move.b #{taken_cost},gb_step_cycles"]
        nextpc=target
        body.append("move.w gb_rom_bank,gb_bank" if 0x4000<=target<0x8000 else "clr.w gb_bank")
    elif fam=="JP_HL":
        body += ["move.w gb_h,gb_pc","cmpi.w #$4000,gb_h",f"blo.s .jphlfixed_{stem}","cmpi.w #$8000,gb_h",f"bhs.s .jphlfixed_{stem}","move.w gb_rom_bank,gb_bank",f"bra.s .jphlready_{stem}",f".jphlfixed_{stem}:","clr.w gb_bank",f".jphlready_{stem}:","jmp gb_dispatch"]
        return body
    elif fam=="JR":
        delta=(operand&255)-256 if operand&128 else operand&255; nextpc=(pc+2+delta)&0xFFFF
    elif fam=="JR_CC":
        delta=(operand&255)-256 if operand&128 else operand&255; target=(pc+2+delta)&0xFFFF; cond=(op>>3)&3; bit=7 if cond<2 else 4
        # BTST sets its Z result when the selected GB flag bit is clear.
        branch=("beq.s","bne.s","beq.s","bne.s")[cond]
        body += [f"move.w #${nextpc:04X},gb_pc",f"btst #{bit},gb_f",f"{branch} .taken_{stem}","jmp gb_dispatch",f".taken_{stem}:",f"move.b #{taken_cost},gb_step_cycles"]
        if block.get("idle_wait"):
            body += [f"move.w #${target:04X},gb_pc"]
            if "idle_ly_target" in block:
                body += [f"move.w #{block['idle_ly_target']},d0","jsr gb_idle_ly"]
            else:body += ["jsr gb_idle_wait"]
            body += ["jmp gb_dispatch_tree"]
            return body
        nextpc=target
    elif fam in ("CALL","RST"):
        target=operand if fam=="CALL" else (op&0x38)
        body += push_word([f"move.l #${nextpc:04X},d3"])
        body += ["move.w gb_rom_bank,gb_bank" if 0x4000<=target<0x8000 else "clr.w gb_bank"]
        nextpc=target
    elif fam=="CALL_CC":
        target=operand;cond=(op>>3)&3;bit=7 if cond<2 else 4;branch=("beq.s","bne.s","beq.s","bne.s")[cond]
        body += [f"btst #{bit},gb_f",f"{branch} .calltaken_{stem}",f"move.w #${nextpc:04X},gb_pc","jmp gb_dispatch",f".calltaken_{stem}:",f"move.b #{taken_cost},gb_step_cycles"]
        body += push_word([f"move.l #${nextpc:04X},d3"])
        body += ["move.w gb_rom_bank,gb_bank" if 0x4000<=target<0x8000 else "clr.w gb_bank"]
        nextpc=target
    elif fam in ("RET","RETI"):
        body += pop_word()+["move.w d3,gb_pc","cmpi.w #$4000,d3",f"blo.s .retfixed_{stem}","cmpi.w #$8000,d3",f"bhs.s .retfixed_{stem}","move.w gb_rom_bank,gb_bank",f"bra.s .retbank_{stem}",f".retfixed_{stem}:","clr.w gb_bank",f".retbank_{stem}:"]
        if fam=="RETI": body += ["move.b #1,gb_ime","clr.b gb_ei_delay"]
        body.append("jmp gb_dispatch"); return body
    elif fam=="RET_CC":
        cond=(op>>3)&3; bit=7 if cond<2 else 4; branch=("beq.s","bne.s","beq.s","bne.s")[cond]
        body += [f"btst #{bit},gb_f",f"{branch} .rettaken_{stem}",f"move.w #${nextpc:04X},gb_pc","jmp gb_dispatch",f".rettaken_{stem}:",f"move.b #{taken_cost},gb_step_cycles"]
        body += pop_word()+["move.w d3,gb_pc","cmpi.w #$4000,d3",f"blo.s .retccfixed_{stem}","cmpi.w #$8000,d3",f"bhs.s .retccfixed_{stem}","move.w gb_rom_bank,gb_bank",f"bra.s .retccbank_{stem}",f".retccfixed_{stem}:","clr.w gb_bank",f".retccbank_{stem}:","jmp gb_dispatch"]
        return body
    elif fam=="PUSH_RR":
        pair=REGS16[(op>>4)&3] if op!=0xF5 else "gb_a"
        body += push_word(["moveq #0,d3",f"move.w {pair},d3"])
    elif fam=="POP_RR":
        pair=REGS16[(op>>4)&3] if op!=0xF1 else "gb_a"
        body += pop_word()+[f"move.w d3,{pair}"]
        if op==0xF1: body.append("andi.b #$F0,gb_f")
    else:return None
    body += [f"move.w #${nextpc:04X},gb_pc","jmp gb_dispatch"]
    return body

def auto_stop_reason(total_steps,max_steps,growth,plateau_chunks,min_new_blocks,events_pending=False):
    """Return why auto tracing should stop, or None to run another chunk."""
    if total_steps >= max_steps:return "maximum step limit reached"
    if events_pending:return None
    if len(growth)>=plateau_chunks and all(value<min_new_blocks for value in growth[-plateau_chunks:]):
        return "coverage plateau (not complete coverage; controller input may be required)"
    return None

def compile_trace(rom_path, out, steps, input_scenarios=None, auto_steps=False,
                  auto_max_steps=50_000_000,auto_chunk_steps=None,
                  auto_plateau_chunks=3,auto_min_new_blocks=1,auto_inputs=False,
                  input_max_branches=128,input_max_depth=4,input_branch_steps=150_000,
                  input_max_steps=20_000_000,input_hold_frames=4,
                  input_snapshot_interval_frames=4,input_max_snapshots=1024,
                  input_bridge_states_per_depth=8):
    if steps<=0:raise ValueError("steps must be positive")
    if auto_steps and (auto_max_steps<steps or (auto_chunk_steps is not None and auto_chunk_steps<=0) or auto_plateau_chunks<=0 or auto_min_new_blocks<=0):
        raise ValueError("invalid auto-step safety limits")
    if auto_inputs and min(input_max_branches,input_max_depth,input_branch_steps,input_max_steps,input_hold_frames,input_snapshot_interval_frames,input_max_snapshots,input_bridge_states_per_depth)<=0:
        raise ValueError("invalid automatic-input safety limits")
    rom=rom_path.read_bytes();hits=collections.Counter();first={};scenario_reports=[];dynamic_values=collections.defaultdict(set)
    input_candidates=[];candidate_keys=set();candidate_last_frame={}
    def capture_input_state(cpu,memory,origin,target,depth=0,limit=None,interval=None):
        if not auto_inputs or not reads_joypad(cpu,memory):return
        frame=memory.cycles//70224;interval=input_snapshot_interval_frames if interval is None else interval
        if frame<candidate_last_frame.get(origin,-interval)+interval:return
        candidate_last_frame[origin]=frame;key=exploration_state_key(cpu)
        if key in candidate_keys:return
        candidate_keys.add(key)
        if limit is None or len(target)<limit:target.append((copy.deepcopy(cpu),depth,origin,frame,key))
    def trace_step(cpu,memory,scenario_keys):
        pc=cpu.pc;bank=memory.rom_bank if 0x4000<=pc<0x8000 else 0;key=(bank,pc);hits[key]+=1
        if key not in scenario_keys:
            size=instruction_length(memory.read(pc));raw=bytes(memory.read(pc+i) for i in range(size))
            if key in first and first[key]!=raw:raise RuntimeError(f"dynamic code conflict at bank {bank} PC ${pc:04X}: {first[key].hex()} vs {raw.hex()}")
            first.setdefault(key,raw);scenario_keys.add(key)
        cpu.step()
    scenarios=[{"name":"no-input","events":[]}]+list(input_scenarios or [])
    for scenario_index,scenario in enumerate(scenarios):
        memory=Memory(rom);cpu=CPU(memory);scenario_keys=set();applied_memory_events=set()
        total_steps=0;growth=[];stop_reason="fixed step budget reached";chunk=steps
        while True:
            before=len(scenario_keys);run_steps=min(chunk,(auto_max_steps-total_steps) if auto_steps else chunk)
            for _ in range(run_steps):
                frame=memory.cycles//70224;state=0xFF
                for start,end,pulse_state in scenario["events"]:
                    if start<=frame<end:state &= pulse_state
                memory.joypad_state=state
                for index,(event_frame,start,end,value) in enumerate(scenario.get("memory_events",())):
                    if frame>=event_frame and index not in applied_memory_events:
                        for address in range(start,end+1):memory.write(address,value)
                        applied_memory_events.add(index)
                capture_input_state(cpu,memory,f"scenario-{scenario_index}",input_candidates,limit=input_max_snapshots)
                trace_step(cpu,memory,scenario_keys)
            total_steps+=run_steps;growth.append(len(scenario_keys)-before)
            if not auto_steps:break
            last_event_frame=max([end for _,end,_ in scenario["events"]]+[event[0] for event in scenario.get("memory_events",())]+[0])
            stop_reason=auto_stop_reason(total_steps,auto_max_steps,growth,auto_plateau_chunks,auto_min_new_blocks,memory.cycles//70224<last_event_frame)
            if stop_reason:break
            chunk=auto_chunk_steps or steps
        for offset,value in enumerate(memory.hram):dynamic_values[0xFF80+offset].add(value)
        scenario_reports.append({"name":scenario["name"],"blocks":len(scenario_keys),"steps_executed":total_steps,"coverage_growth":growth,"stop_reason":stop_reason,"end_pc":cpu.pc,"end_frame":memory.cycles//70224})
    exploration_report={"enabled":auto_inputs,"branches_executed":0,"steps_executed":0,
                        "limits":{"max_branches":input_max_branches,"max_depth":input_max_depth,
                                  "branch_steps":input_branch_steps,"max_steps":input_max_steps,
                                  "hold_frames":input_hold_frames,
                                  "snapshot_interval_frames":input_snapshot_interval_frames,
                                  "max_snapshots":input_max_snapshots,
                                  "bridge_states_per_depth":input_bridge_states_per_depth},
                        "initial_snapshots":len(input_candidates),"new_blocks":0,
                        "bridge_states_expanded":0,"stop_reason":"disabled","branches":[]}
    if auto_inputs:
        root_count=min(len(input_candidates),max(1,input_max_branches//(len(AUTO_INPUT_ACTIONS)*2)))
        if root_count and len(input_candidates)>root_count:
            indices=[round(i*(len(input_candidates)-1)/(root_count-1)) for i in range(root_count)] if root_count>1 else [len(input_candidates)-1]
            roots=[input_candidates[index] for index in dict.fromkeys(indices)]
        else:roots=input_candidates
        queue=collections.deque(roots);exploration_keys=set();initial_blocks=len(first);bridge_counts=collections.Counter()
        while queue and exploration_report["branches_executed"]<input_max_branches and exploration_report["steps_executed"]<input_max_steps:
            snapshot,depth,origin,snapshot_frame,snapshot_key=queue.popleft()
            for action_name,action_state in AUTO_INPUT_ACTIONS:
                if exploration_report["branches_executed"]>=input_max_branches or exploration_report["steps_executed"]>=input_max_steps:break
                cpu=copy.deepcopy(snapshot);memory=cpu.m;start_frame=memory.cycles//70224
                local_candidates=[];before=len(first);executed=0
                branch_limit=min(input_branch_steps,input_max_steps-exploration_report["steps_executed"])
                branch_origin=f"branch-{exploration_report['branches_executed']}"
                for _ in range(branch_limit):
                    memory.joypad_state=action_state if memory.cycles//70224<start_frame+input_hold_frames else 0xFF
                    capture_input_state(cpu,memory,branch_origin,local_candidates,depth+1,limit=16,interval=1)
                    trace_step(cpu,memory,exploration_keys);executed+=1
                new_blocks=len(first)-before;exploration_report["branches_executed"]+=1;exploration_report["steps_executed"]+=executed
                exploration_report["branches"].append({"depth":depth,"action":action_name,"source_frame":snapshot_frame,"steps":executed,"new_blocks":new_blocks,"end_pc":cpu.pc,"end_bank":memory.rom_bank if 0x4000<=cpu.pc<0x8000 else 0})
                if new_blocks:
                    print(f"auto-input branch {exploration_report['branches_executed']}: depth={depth} action={action_name} +{new_blocks} blocks",flush=True)
                    if depth<input_max_depth:
                        for candidate in reversed(local_candidates[-4:]):queue.appendleft(candidate)
                elif depth<input_max_depth and origin.startswith("branch-") and local_candidates and bridge_counts[depth]<input_bridge_states_per_depth:
                    # Some useful paths require a sequence of inputs where an
                    # intermediate press changes state but executes no new PC.
                    # Keep a small, depth-bounded quota of those bridge states;
                    # novel branches still take priority at the front.
                    # Interleave bridges after a few high-priority novel
                    # states so they are not starved by a large novel queue.
                    queue.insert(min(4,len(queue)),local_candidates[-1]);bridge_counts[depth]+=1
                    exploration_report["bridge_states_expanded"]+=1
                elif exploration_report["branches_executed"]%16==0:
                    print(f"auto-input progress: {exploration_report['branches_executed']} branches, {exploration_report['steps_executed']} steps",flush=True)
        exploration_report["new_blocks"]=len(first)-initial_blocks
        if exploration_report["steps_executed"]>=input_max_steps:exploration_report["stop_reason"]="maximum exploration instruction limit reached"
        elif exploration_report["branches_executed"]>=input_max_branches:exploration_report["stop_reason"]="maximum branch limit reached"
        elif not roots:exploration_report["stop_reason"]="no JOYP read snapshots discovered"
        else:exploration_report["stop_reason"]="exploration queue exhausted"
        scenario_reports.append({"name":"automatic-input-exploration","blocks":len(exploration_keys),"steps_executed":exploration_report["steps_executed"],"coverage_growth":[exploration_report["new_blocks"]],"stop_reason":exploration_report["stop_reason"],"end_pc":None,"end_frame":None})
    dynamic_unique_block_count=len(first)
    # Close direct ROM control flow from every dynamically observed entry.
    # Trace discovery identifies the active banks and dynamic targets; this
    # pass then compiles both outcomes of conditionals so collision failures,
    # wall corrections, and similar input-dependent branches do not require an
    # exact frame script merely to avoid gb_missing_block.
    frontier=collections.deque(key for key in first if key[1] < 0x8000)
    expanded=set();indirect_table_targets=set();hl_table_targets=set();rst_table_targets=set()
    def rom_key(source_key,address):
        address &= 0xFFFF;source_bank,source_pc=source_key
        if address < 0x4000:return (0,address)
        if address < 0x8000 and 0x4000 <= source_pc < 0x8000:return (source_bank,address)
        if 0xFF80 <= address < 0xFFFF:return (0,address)
        return None
    def add_rom_block(key):
        if key is None or key in first:return
        bank,pc=key
        if pc < 0x4000:offset=pc;limit=0x4000
        elif pc < 0x8000 and bank:offset=bank*0x4000+pc-0x4000;limit=0x8000
        elif 0xFF80 <= pc < 0xFFFF:
            values=dynamic_values.get(pc)
            if not values or len(values)!=1 or next(iter(values)) in (0x00,0xFF):return
            opcode=next(iter(values));size=instruction_length(opcode);raw=[]
            for address in range(pc,pc+size):
                byte_values=dynamic_values.get(address)
                if not byte_values or len(byte_values)!=1:return
                raw.append(next(iter(byte_values)))
            raw=bytes(raw)
            if pc+size>0xFFFF:return
            if family(opcode) in ("INVALID","STOP"):return
            first[key]=raw;hits[key]+=0;frontier.append(key);return
        else:return
        if offset >= len(rom):return
        size=instruction_length(rom[offset])
        if pc+size>limit or offset+size>len(rom):return
        # Do not let speculative closure walk through padding/data after an
        # illegal opcode or an unobserved STOP. Dynamically executed instances
        # are already present in ``first`` and remain diagnostics.
        if family(rom[offset]) in ("INVALID","STOP"):return
        first[key]=rom[offset:offset+size];hits[key]+=0;frontier.append(key)
    def bounded_pointer_table(source_key,table,max_entries=64):
        """Return consecutive, validated ROM code pointers from ``table``.

        A minimum length is enforced by callers.  The first invalid pointer
        terminates the table, preventing speculative scanning through adjacent
        data or instructions.
        """
        candidates=[];source_bank,_=source_key
        for index in range(max_entries):
            address=(table+index*2)&0xFFFF
            if address+1>=0x8000:break
            if address<0x4000:entry_offset=address
            elif source_bank:entry_offset=source_bank*0x4000+address-0x4000
            else:break
            if entry_offset+1>=len(rom):break
            target=rom[entry_offset]|rom[entry_offset+1]<<8;target_key=rom_key(source_key,target)
            if target_key is None:break
            target_bank,target_pc=target_key
            target_offset=target_pc if target_pc<0x4000 else target_bank*0x4000+target_pc-0x4000
            if target_offset>=len(rom) or family(rom[target_offset]) in ("INVALID","STOP"):break
            candidates.append(target_key)
        return candidates
    # Interrupt entry is asynchronous and target timing can take a vector that
    # a finite reference trace did not. Compile every non-padding cartridge
    # vector independently of whether the oracle happened to service it.
    for vector in (0x40,0x48,0x50,0x58,0x60):
        if vector < len(rom) and rom[vector] not in (0x00,0xFF):add_rom_block((0,vector))
    while frontier:
        key=frontier.popleft()
        if key in expanded:continue
        expanded.add(key);bank,pc=key;raw=first[key];op=raw[0];fam=family(op)
        size=len(raw);fall=(pc+size)&0xFFFF;operand=(raw[1] if size==2 else (raw[1]|raw[2]<<8 if size==3 else 0))
        successors=[]
        if fam=="JR":
            delta=(operand&255)-256 if operand&128 else operand&255;successors=[(pc+2+delta)&0xFFFF]
        elif fam=="JR_CC":
            delta=(operand&255)-256 if operand&128 else operand&255;successors=[fall,(pc+2+delta)&0xFFFF]
        elif fam=="JP":successors=[operand]
        elif fam=="JP_CC":successors=[fall,operand]
        elif fam in ("CALL","CALL_CC"):
            successors=[fall,operand]
        elif fam=="RST":
            vector=op&0x38
            # Recognize the common SM83 inline table-call convention. The RST
            # handler consumes its stacked return address as a pointer table
            # base, indexes it with A*2, and JP (HL)s to the selected routine:
            #   ADD A,A / POP HL / LD E,A / LD D,0 / ADD HL,DE /
            #   LD E,(HL) / INC HL / LD D,(HL) / PUSH DE / POP HL / JP (HL)
            # In that convention the bytes after RST are data, not executable
            # fallthrough. Require the exact handler and at least two bounded,
            # valid pointers before suppressing ordinary RST fallthrough.
            handler=rom[vector:vector+12]
            rst_candidates=bounded_pointer_table(key,fall) if handler==bytes.fromhex("87e15f1600195e2356d5e1e9") else []
            if len(rst_candidates)>=2:
                successors=[vector]
                for target_key in rst_candidates:
                    rst_table_targets.add(target_key);indirect_table_targets.add(target_key);add_rom_block(target_key)
            else:successors=[fall,vector]
        elif fam in ("RET_CC",):successors=[fall]
        elif fam not in ("RET","RETI","JP_HL","HALT","STOP","INVALID","UNCLASSIFIED"):
            successors=[fall]
        for address in successors:add_rom_block(rom_key(key,address))
        # Resolve a common bounded ROM dispatch idiom:
        #   LD HL,table / CALL index_helper / JP (HL)
        # The helper selects a little-endian pointer from the table. Require
        # at least two consecutive, valid ROM code pointers and stop at the
        # first invalid entry; this avoids treating arbitrary data as code.
        if op==0x21 and pc+7<=0x8000:
            if pc<0x4000:sequence_offset=pc
            elif bank:sequence_offset=bank*0x4000+pc-0x4000
            else:sequence_offset=-1
            sequence=rom[sequence_offset:sequence_offset+7] if sequence_offset>=0 else b""
            if len(sequence)==7 and sequence[0]==0x21 and sequence[3]==0xCD and sequence[6]==0xE9:
                table=sequence[1]|sequence[2]<<8;candidates=bounded_pointer_table(key,table)
                if len(candidates)>=2:
                    for target_key in candidates:
                        hl_table_targets.add(target_key);indirect_table_targets.add(target_key);add_rom_block(target_key)
    blocks=[]
    for (bank,pc),count in sorted(hits.items()):
        raw=first[(bank,pc)]; operand=(raw[1] if len(raw)==2 else (raw[1]|raw[2]<<8 if len(raw)==3 else 0))
        block={"bank":bank,"pc":pc,"opcode":raw[0],"operand":operand,"bytes":raw.hex(),"family":family(raw[0]),"hits":count}
        block["native_lowered"]=native_body(block) is not None; blocks.append(block)
    # Recognize short, backward, read-only polling loops. These commonly wait
    # for a VBlank flag or LY value and would otherwise consume nearly all
    # target CPU time. The runtime still executes the real interrupt and the
    # loop re-reads its condition after RETI.
    by_key={(b["bank"],b["pc"]):b for b in blocks}
    harmless={"NOP","LDH_A_A8","LD_A_A16","LDH_A_C","LD_A_RR",
              "AND_A_R","AND_A_D8","OR_A_R","OR_A_D8","XOR_A_R",
              "XOR_A_D8","CP_A_R","CP_A_D8"}
    for block in blocks:
        if block["family"]!="JR_CC":continue
        delta=(block["operand"]&255)-256 if block["operand"]&128 else block["operand"]&255
        target=(block["pc"]+2+delta)&0xFFFF
        if target>=block["pc"] or block["pc"]-target>16:continue
        cursor=target;loop=[]
        while cursor<block["pc"]:
            item=by_key.get((block["bank"],cursor))
            if item is None:break
            loop.append(item);cursor += len(bytes.fromhex(item["bytes"]))
        if cursor!=block["pc"] or not loop:continue
        safe=True;has_read=False
        for item in loop:
            fam=item["family"]
            if fam=="LD_R_R":
                safe &= ((item["opcode"]>>3)&7)!=6
                has_read |= (item["opcode"]&7)==6
            elif fam=="CB":
                safe &= (item["operand"]>>6)==1
                has_read |= (item["operand"]&7)==6
            else:safe &= fam in harmless
            has_read |= fam in ("LDH_A_A8","LD_A_A16","LDH_A_C","LD_A_RR")
        if safe and has_read:
            block["idle_wait"]=True
            ly_reads=[item for item in loop if item["family"]=="LDH_A_A8" and item["operand"]==0x44]
            compares=[item for item in loop if item["family"]=="CP_A_D8"]
            if ly_reads and compares:block["idle_ly_target"]=compares[-1]["operand"]&255
    for block in blocks:block["native_lowered"]=native_body(block) is not None
    out.mkdir(parents=True,exist_ok=True)
    (out/"trace-profile.json").write_text(json.dumps({"input":str(rom_path),"steps_per_scenario":steps,"auto_steps":auto_steps,"auto_inputs":auto_inputs,"total_steps_executed":sum(s["steps_executed"] for s in scenario_reports),"dynamic_unique_blocks":dynamic_unique_block_count,"indirect_table_targets":len(indirect_table_targets),"hl_pointer_table_targets":len(hl_table_targets),"rst_inline_table_targets":len(rst_table_targets),"total_blocks_after_static_closure":len(blocks),"input_exploration":exploration_report,"scenarios":scenario_reports,"blocks":blocks},indent=2)+"\n")
    used=sorted({b["family"] for b in blocks if not b["native_lowered"]})
    label=lambda b:f"L_gb_B{b['bank']:03X}_{b['pc']:04X}"
    block_by_key={(b["bank"],b["pc"]):b for b in blocks}
    chain_targets=set()
    pc_store=re.compile(r"move\.w #\$([0-9A-Fa-f]{4}),gb_pc$")
    def thread_static_dispatch(block,body):
        """Direct-link constant successors while preserving IRQ/bank checks."""
        current_target=None;current_store_index=None;result=[]
        for statement in body:
            match=pc_store.match(statement)
            if match:
                current_target=int(match.group(1),16);current_store_index=len(result)
            elif "gb_pc" in statement and not statement.endswith(":"):
                current_target=None;current_store_index=None
            target_key=None
            if current_target is not None:
                if not 0x4000<=current_target<0x8000:target_key=(0,current_target)
                elif block["bank"]:target_key=(block["bank"],current_target)
                else:
                    candidates=[key for key in block_by_key if key[1]==current_target]
                    if len(candidates)==1:target_key=candidates[0]
            if statement=="jmp gb_dispatch" and target_key in block_by_key and block["family"] not in ("HALT","STOP"):
                # The edge stub writes PC only when it actually flushes the
                # scheduler. Straight-line code does not otherwise observe PC,
                # so avoid one absolute RAM write per emulated instruction.
                if current_store_index is not None:result[current_store_index]=None
                result.append(f"jmp gb_chain_B{target_key[0]:03X}_{target_key[1]:04X}");chain_targets.add(target_key)
            else:result.append(statement)
        return [statement for statement in result if statement is not None]
    entry=next((b for b in blocks if b["bank"] == 0 and b["pc"] == 0x100),blocks[0])
    lines=["; Trace-guided static LR35902 -> 68000 block output.","\txdef gb_compiled_entry,gb_compiled_block_table,gb_dispatch_tree"]
    lines += ["gb_compiled_entry:",f"\tbra.w {label(entry)}",""]
    for block in blocks:
        lines.append(f"{label(block)}:")
        lines.append(f"\tmove.b #{instruction_cycles(block['opcode'],block['operand'],False)},gb_step_cycles")
        direct=native_body(block)
        if direct is not None: lines += [f"\t{x}" for x in thread_static_dispatch(block,direct)]+[""]
        else:
            lines += [f"\tmove.w #${block['bank']:04X},gb_bank",f"\tmove.w #${block['pc']:04X},gb_pc",
                      f"\tmove.b #${block['opcode']:02X},gb_opcode",f"\tmove.w #${block['operand']:04X},gb_operand",
                      f"\tjsr gbop_{block['family'].lower()}","\tjmp gb_dispatch",""]
    # Hot constant successors above jump through these shared chain stubs.
    # gb_tick may redirect execution for an IRQ, so validate PC/bank before
    # entering the successor. Returns, JP (HL), mapper changes, and IRQ entry
    # continue through the general dispatcher below.
    for bank,target in sorted(chain_targets):
        stem=f"B{bank:03X}_{target:04X}"
        lines += [f"gb_chain_{stem}:","\ttst.b gb_force_tick",f"\tbne.s .chain_flush_{stem}","\ttst.b gb_ei_delay",f"\tbne.s .chain_flush_{stem}","\tmoveq #0,d0","\tmove.b gb_step_cycles,d0","\tmoveq #0,d1","\tmove.w d7,d1","\tadd.w d0,d1",f"\tcmpi.w #{SCHEDULER_BATCH_T_CYCLES},d1",f"\tbhs.s .chain_flush_{stem}","\tmove.w d1,d7",f"\tjmp {label(block_by_key[(bank,target)])}",f".chain_flush_{stem}:","\tclr.b gb_force_tick",f"\tmove.w #${target:04X},gb_pc","\tjsr gb_tick","\ttst.b gb_halted",f"\tbeq.s .chain_awake_{stem}","\tjmp gb_dispatch",f".chain_awake_{stem}:",f"\tcmpi.w #${bank:04X},gb_bank",f"\tbeq.s .chain_bank_ok_{stem}","\tjmp gb_dispatch_tree",f".chain_bank_ok_{stem}:",f"\tcmpi.w #${target:04X},gb_pc",f"\tbeq.s .chain_pc_ok_{stem}","\tjmp gb_dispatch_tree",f".chain_pc_ok_{stem}:",f"\tjmp {label(block_by_key[(bank,target)])}",""]
    # Balanced native decision tree: about log2(N) comparisons rather than a
    # linear scan through every compiled block on every GB instruction.
    lines += ["gb_dispatch_tree:","\tmoveq #0,d0","\tmove.w gb_bank,d0","\tswap d0","\tmove.w gb_pc,d0","\tjmp .dispatch_node_0"]
    ordered=sorted(blocks,key=lambda b:(b["bank"]<<16)|b["pc"])
    def tree(lo,hi,node):
        if lo>=hi:return [f".dispatch_node_{node}:","\tjmp gb_missing_block"]
        mid=(lo+hi)//2;b=ordered[mid];key=(b["bank"]<<16)|b["pc"];left=node*2+1;right=node*2+2
        result=[f".dispatch_node_{node}:",f"\tcmpi.l #${key:08X},d0",f"\tbne.s .dispatch_not_equal_{node}",f"\tjmp {label(b)}",f".dispatch_not_equal_{node}:",f"\tbhs.s .dispatch_not_lower_{node}"]
        result += [f"\tjmp .dispatch_node_{left}" if lo<mid else "\tjmp gb_missing_block"]
        result += [f".dispatch_not_lower_{node}:"]
        result += [f"\tjmp .dispatch_node_{right}" if mid+1<hi else "\tjmp gb_missing_block"]
        return result+tree(lo,mid,left)+tree(mid+1,hi,right)
    lines += tree(0,len(ordered),0)
    lines += ["\teven","gb_compiled_block_table:"]
    for block in blocks: lines += [f"\tdc.w ${block['bank']:04X},${block['pc']:04X}",f"\tdc.l {label(block)}"]
    lines += ["\tdc.w $FFFF,$FFFF","\tdc.l 0"]
    (out/"translated_trace.s").write_text("\n".join(lines))
    return blocks

def main():
    p=argparse.ArgumentParser();p.add_argument("rom",type=pathlib.Path);p.add_argument("--out",type=pathlib.Path,default=pathlib.Path("build"));p.add_argument("--steps",type=int,default=100000);p.add_argument("--auto-steps",action="store_true");p.add_argument("--auto-max-steps",type=int,default=50_000_000);p.add_argument("--auto-chunk-steps",type=int);p.add_argument("--auto-plateau-chunks",type=int,default=3);p.add_argument("--auto-min-new-blocks",type=int,default=1);p.add_argument("--auto-inputs",action="store_true");p.add_argument("--input-max-branches",type=int,default=128);p.add_argument("--input-max-depth",type=int,default=4);p.add_argument("--input-branch-steps",type=int,default=150_000);p.add_argument("--input-max-steps",type=int,default=20_000_000);p.add_argument("--input-hold-frames",type=int,default=4);p.add_argument("--input-snapshot-interval-frames",type=int,default=4);p.add_argument("--input-max-snapshots",type=int,default=1024);p.add_argument("--input-bridge-states-per-depth",type=int,default=8);p.add_argument("--input-script",action="append",default=[],metavar="PULSES",help="merge a trace such as start@512:8,a@560:4");ns=p.parse_args()
    blocks=compile_trace(ns.rom,ns.out,ns.steps,[parse_input_script(s) for s in ns.input_script],ns.auto_steps,ns.auto_max_steps,ns.auto_chunk_steps,ns.auto_plateau_chunks,ns.auto_min_new_blocks,ns.auto_inputs,ns.input_max_branches,ns.input_max_depth,ns.input_branch_steps,ns.input_max_steps,ns.input_hold_frames,ns.input_snapshot_interval_frames,ns.input_max_snapshots,ns.input_bridge_states_per_depth);print(f"wrote {len(blocks)} traced static blocks to {ns.out/'translated_trace.s'}")
if __name__ == "__main__":main()
