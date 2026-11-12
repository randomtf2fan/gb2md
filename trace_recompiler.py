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
from bank_analysis import fixed_bank_context_targets
from ram_callback_analysis import RamCallbackAnalyzer
from serial_test import SerialTestMemory

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

class InputSweep:
    """Deterministic Start/A edges with varied holds and explicit releases.

    This is a coverage heuristic, not menu recognition. Five hold scales and
    three release scales avoid repeatedly sampling only one fixed input phase.
    Execution remains bounded by the caller's instruction budget.
    """
    def __init__(self,start_frame,hold_frames):
        if start_frame<0 or hold_frames<=0:raise ValueError('invalid input sweep timing')
        self.next_frame=start_frame;self.hold_frames=hold_frames
        self.press_count=0;self.pressed=False;self.button=255

    def state(self,frame):
        while frame>=self.next_frame:
            if self.pressed:
                self.pressed=False
                self.next_frame+=self.hold_frames*(1+(self.press_count-1)%3)
            else:
                self.button=BUTTON_STATES[('start','a')[self.press_count%2]]
                self.next_frame+=self.hold_frames*(1<<(self.press_count%5))
                self.press_count+=1;self.pressed=True
        return self.button if self.pressed else 255

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
    digest.update(struct.pack(">2H5B",
                              256 if memory.dma_requested is None else memory.dma_requested,
                              256 if memory.dma_starting is None else memory.dma_starting,
                              memory.dma_active,memory.dma_source,memory.dma_index,
                              memory.dma_phase,memory.joypad_state))
    digest.update(bytes([memory.stat_line]))
    for region in (memory.vram,memory.wram,memory.oam,memory.hram,memory.io,memory.eram):digest.update(region)
    return digest.digest()

def is_inline_rst_dispatch(rom, vector):
    """Recognize exact stack-consuming table dispatchers in fixed ROM only."""
    signatures=(bytes.fromhex('87e15f1600195e2356d5e1e9'),
                bytes.fromhex('5f1600cb23cb12e1195e2356d5e1e9'))
    address=vector;visited=set()
    for _ in range(4):
        if address in visited or not 0<=address<0x4000:return False
        visited.add(address)
        if any(address+len(s)<=min(len(rom),0x4000) and rom[address:address+len(s)]==s for s in signatures):return True
        if address+3>min(len(rom),0x4000) or rom[address]!=0xC3:return False
        address=rom[address+1]|rom[address+2]<<8
    return False

def _selected_bank_candidates(rom,value,address):
    """Physical candidates after one supported low-bank-register write."""
    mapper=rom[0x147]
    if mapper in (1,2,3) and 0x2000<=address<0x4000:
        banks=[high|((value&31) or 1) for high in (0,0x20,0x40,0x60)]
    elif 0x0F<=mapper<=0x13 and 0x2000<=address<0x4000:banks=[(value&127) or 1]
    elif 0x19<=mapper<=0x1E and 0x2000<=address<0x3000:banks=[value,value|0x100]
    else:return []
    return [bank for bank in banks if bank*0x4000<len(rom)]

def _shadow_store_end(rom,pc,end):
    """A-preserving WRAM/HRAM bank-shadow store, never a hardware I/O write."""
    if pc+2<=end and rom[pc]==0xE0 and 0x80<=rom[pc+1]<0xFF:return pc+2
    if pc+3<=end and rom[pc]==0xEA:
        address=rom[pc+1]|rom[pc+2]<<8
        if 0xC000<=address<0xE000 or 0xFF80<=address<0xFFFF:return pc+3
    return None

def _bank_setter_register(rom,pc):
    """Verify a short fixed-ROM bank store plus optional shadows and RET."""
    if not 0<=pc<0x4000:return None
    end=min(len(rom),0x4000,pc+16);address=None
    for _ in range(6):
        if pc>=end:return None
        if rom[pc]==0xC9:return address
        shadow=_shadow_store_end(rom,pc,end)
        if shadow is not None:pc=shadow;continue
        if pc+3<=end and rom[pc]==0xEA and address is None:
            candidate=rom[pc+1]|rom[pc+2]<<8
            if _selected_bank_candidates(rom,1,candidate):address=candidate;pc+=3;continue
        return None
    return None

def constant_bank_call_site(rom,pc):
    """Resolve bounded LD A,n / bank selection / CALL|JP in fixed ROM.

    Bank selection may use a direct mapper store or a verified store-only
    setter helper. At most two RAM shadow stores are allowed on either side.
    Unknown calls, A changes and upper-window callers terminate recognition.
    """
    if len(rom)<=0x147 or not 0<=pc<=0x4000-8 or rom[pc]!=0x3E:return None
    value=rom[pc+1];cursor=pc+2;end=min(len(rom),0x4000,pc+24)
    for _ in range(2):
        shadow=_shadow_store_end(rom,cursor,end)
        if shadow is None:break
        cursor=shadow
    if cursor+3>end:return None
    operand=rom[cursor+1]|rom[cursor+2]<<8
    if rom[cursor]==0xEA:address=operand
    elif rom[cursor]==0xCD:address=_bank_setter_register(rom,operand)
    else:return None
    if address is None:return None
    cursor+=3
    for _ in range(2):
        shadow=_shadow_store_end(rom,cursor,end)
        if shadow is None:break
        cursor=shadow
    if cursor+3>end or rom[cursor] not in (0xCD,0xC3):return None
    target=rom[cursor+1]|rom[cursor+2]<<8
    if not 0x4000<=target<0x8000:return None
    targets=[(bank,target) for bank in _selected_bank_candidates(rom,value,address)
             if bank*0x4000+target-0x4000<len(rom)]
    return (cursor,targets) if targets else None

def constant_bank_call_targets(rom,pc):
    site=constant_bank_call_site(rom,pc)
    return site[1] if site is not None else []

def constant_far_call_targets(rom,bank,pc,diagnostics=None):
    """Resolve constant B=bank / HL=target calls through a verified trampoline.

    Accept either setup order and CALL/JP, including bounded fixed-ROM aliases.
    The helper must save the current bank, select B, push its own return
    trampoline, JP(HL), then restore the saved bank and RET. No source-game
    addresses, assumed caller-bank invariants or replacement CPU semantics.
    """
    if len(rom)<=0x147 or not 0<=pc<0x8000:return []
    if pc+8>(0x4000 if pc<0x4000 else 0x8000):return []
    offset=pc if pc<0x4000 else bank*0x4000+pc-0x4000
    raw=rom[offset:offset+8]
    if len(raw)!=8 or raw[5] not in (0xCD,0xC3):return []
    if raw[0]==0x06 and raw[2]==0x21:value,target=raw[1],raw[3]|raw[4]<<8
    elif raw[0]==0x21 and raw[3]==0x06:value,target=raw[4],raw[1]|raw[2]<<8
    else:return []
    if not 0x100<=target<0x8000:return []
    helper=raw[6]|raw[7]<<8;seen=set()
    for _ in range(4):
        if helper in seen or not 0<=helper<0x4000:return []
        seen.add(helper)
        if helper+3<=min(len(rom),0x4000) and rom[helper]==0xC3:
            helper=rom[helper+1]|rom[helper+2]<<8;continue
        break
    else:return []
    if helper+22>min(len(rom),0x4000):return []
    body=rom[helper:helper+22]
    if (body[0]!=0xF0 or body[2:5]!=bytes.fromhex('f578e0') or body[6]!=0xEA
        or body[9]!=0x01 or body[12:17]!=bytes.fromhex('c5e9c178e0')
        or body[18]!=0xEA or body[21]!=0xC9):return []
    if not 0x80<=body[1]<0xFF or not body[1]==body[5]==body[17]:return []
    register=body[7]|body[8]<<8
    if body[7:9]!=body[19:21] or (body[10]|body[11]<<8)!=helper+14:return []
    # ROM-only cartridges ignore the helper's mapper write and retain bank1.
    if rom[0x147] in (0,8,9) and not 0x2000<=register<0x4000:return []
    selected_banks=[1] if rom[0x147] in (0,8,9) else _selected_bank_candidates(rom,value,register)
    targets=list(dict.fromkeys((0 if target<0x4000 else selected,target)
                for selected in selected_banks
                if target<0x4000 or selected*0x4000+target-0x4000<len(rom)))
    if targets and diagnostics is not None:diagnostics['return_target']=(0,helper+14)
    return targets

def bitmask_dispatch_targets(rom,bank,pc):
    """Resolve an exact MSB-first bit scan over eight return/callback pairs.

    SLA A shifts one input bit into carry; each unset bit advances HL by four.
    A zero mask loops rather than selecting a ninth record. Both pointers in
    each record are executable roots: the callback RETs to the pushed address.
    Unknown fixed-ROM upper-window mappings and altered scan loops are rejected.
    """
    signature=bytes.fromhex('cb2738062323232318f62a5f2a572a666fd5e9')
    def read(address,size):
        if not 0<=address<0x8000 or address+size>(0x4000 if address<0x4000 else 0x8000):return b''
        if address<0x4000:offset=address
        elif pc>=0x4000:offset=bank*0x4000+address-0x4000
        elif len(rom)>0x147 and rom[0x147] in (0,8,9):offset=address
        else:return b''
        return rom[offset:offset+size]
    head=read(pc,3)
    if len(head)!=3 or head[0]!=0x21 or read(pc+3,len(signature))!=signature:return []
    table=head[1]|head[2]<<8;targets=[];records=0
    for index in range(8):
        record=read(table+4*index,4)
        if len(record)!=4:break
        pair=[]
        for offset in (0,2):
            target=record[offset]|record[offset+1]<<8;opcode=read(target,1)
            if target<0x100 or not opcode or family(opcode[0]) in ('INVALID','STOP'):break
            pair.append((0 if target<0x4000 else (bank if pc>=0x4000 else 1),target))
        if len(pair)!=2:break
        records+=1;targets.extend(pair)
    return list(dict.fromkeys(targets)) if records>=2 else []

def hl_dispatch_table(rom,bank,pc,diagnostics=None):
    """Track a ROM table through a bounded, bank-stable pointer lookup.

    Track bank-stable setup and A-only index computation without changing HL.
    Verify helpers returning table[A] in HL or calling it through a preserving
    trampoline. Unknown calls and HL writes terminate recognition.
    """
    signatures=(bytes.fromhex('cb274f0600094e23466069c9'),
                bytes.fromhex('3dcb274f0600094e23466069c9'))
    window_end=0x4000 if pc<0x4000 else 0x8000
    def read(address,size):
        if not 0<=address<0x8000 or address+size>(0x4000 if address<0x4000 else 0x8000):return None
        if address<0x4000:offset=address
        elif 0x4000<=pc<0x8000:offset=bank*0x4000+address-0x4000
        elif rom[0x147] in (0,8,9):offset=address
        else:return None
        return rom[offset:offset+size] if offset+size<=len(rom) else None
    head=read(pc,3)
    if not head or head[0]!=0x21:return None
    table=head[1]|head[2]<<8;cursor=pc+3;end=min(window_end,pc+32);resolved=False
    # Inline A*2 / BC-index / little-endian HL lookup, with optional BC save.
    inline=(bytes.fromhex('c58706004f09c12a666fe9'),bytes.fromhex('8706004f092a666fe9'))
    if any(read(cursor,len(signature))==signature for signature in inline):return table
    def callback_return(helper):
        seen=set()
        for _ in range(4):
            if helper in seen:return None
            seen.add(helper);body=read(helper,3)
            if body is None:return None
            if body[0]==0xC3:helper=body[1]|body[2]<<8;continue
            body=read(helper,20)
            if (body is not None and body[:12]==bytes.fromhex('e5d5c58716005f192a666f11')
                and body[14:]==bytes.fromhex('d5e9c1d1e1c9')
                and (body[12]|body[13]<<8)==helper+16):return helper+16
            return None
        return None
    for _ in range(12):
        if cursor>=end:return None
        raw=read(cursor,1)
        if not raw:return None
        op=raw[0]
        if op==0xE9:return table if resolved else None
        if op==0:cursor+=1
        elif op in (0x01,0x11):
            if not read(cursor,3) or cursor+3>end:return None
            cursor+=3
        elif op==0x18:
            raw=read(cursor,2)
            if not raw or raw[1]>=128:return None
            cursor+=2+raw[1]
        elif op in (0x0A,0x1A,0xF2,0x3C,0x3D,0x07,0x0F,0x17,0x1F,0x27,0x2F,0x37,0x3F) or 0x78<=op<=0xBF:
            cursor+=1 # A/flags only; no HL, memory or mapper writes.
        elif op in (0xFA,0xF0,0x3E,0xC6,0xCE,0xD6,0xDE,0xE6,0xEE,0xF6,0xFE):
            size=instruction_length(op)
            if cursor+size>end or read(cursor,size) is None:return None
            cursor+=size
        elif op in (0xCD,0xC3) and not resolved:
            raw=read(cursor,3)
            if raw is None or cursor+3>end:return None
            helper=raw[1]|raw[2]<<8;return_pc=callback_return(helper)
            if return_pc is not None:
                if diagnostics is not None:
                    diagnostics.update(helper=helper,return_address=return_pc,entry_limit=128,min_entries=1)
                return table
            if op==0xC3:return None
            if not any(read(helper,len(s))==s for s in signatures):return None
            resolved=True;cursor+=3
        else:return None
    return None

def banked_pointer_table_targets(rom,bank,pc,max_entries=128,diagnostics=None):
    """Recognize a bounded bank/lo/hi lookup returning HL and a bank byte.

    The exact index/three-byte-load sequence is verified, while table, index
    and bank-variable addresses are operands, not cartridge-specific constants.
    Only WRAM/HRAM state operands and a known ROM window are accepted. These
    are speculative coverage candidates; this never changes live bank dispatch.
    """
    if len(rom)<=0x147:return []
    mapper=rom[0x147]
    if mapper not in (1,2,3) and not 0x0F<=mapper<=0x13 and not 0x19<=mapper<=0x1E:return []
    def read(address,size):
        if not 0<=address<0x8000 or address+size>(0x4000 if address<0x4000 else 0x8000):return None
        if address<0x4000:offset=address
        elif 0x4000<=pc<0x8000:offset=bank*0x4000+address-0x4000
        else:return None
        return rom[offset:offset+size] if offset+size<=len(rom) else None
    raw=read(pc,30)
    if not raw or raw[0]!=0x21 or raw[3:7]!=bytes.fromhex('110000fa'):return []
    if raw[9:21]!=bytes.fromhex('5f87835f30011419545d1aea') or raw[23:]!=bytes.fromhex('131a6f131a67c9'):return []
    index_address=raw[7]|raw[8]<<8;bank_address=raw[21]|raw[22]<<8
    is_work_ram=lambda a:0xC000<=a<0xE000 or 0xFF80<=a<0xFFFF
    if not is_work_ram(index_address) or not is_work_ram(bank_address):return []
    # The doubled byte index is exact for A=0..127; larger A values overflow
    # before the following addition. Cover that aligned range, not just an
    # arbitrary prefix. Never infer misaligned higher-index targets here.
    table=raw[1]|raw[2]<<8;targets=[];entries=0;limit=max(0,min(max_entries,128))
    stop_reason='entry_limit'
    for index in range(limit):
        entry=read(table+3*index,3)
        if entry is None:stop_reason='table_boundary';break
        value,target=entry[0],entry[1]|entry[2]<<8
        if not 0x100<=target<0x8000:stop_reason='non_code_pointer';break
        banks=_selected_bank_candidates(rom,value,0x2000)
        candidates=[]
        for active_bank in banks:
            if active_bank*0x4000>=len(rom):continue
            offset=target if target<0x4000 else active_bank*0x4000+target-0x4000
            if offset>=len(rom) or family(rom[offset]) in ('INVALID','STOP'):continue
            size=instruction_length(rom[offset])
            if offset+size>len(rom) or target+size>(0x4000 if target<0x4000 else 0x8000):continue
            candidates.append((0 if target<0x4000 else active_bank,target))
        if not candidates:stop_reason='no_valid_target';break
        targets.extend(candidates);entries+=1
    if diagnostics is not None:
        diagnostics.update(bank=bank,pc=pc,table=table,entry_limit=limit,
                           entries=entries,stop_reason=stop_reason,
                           unique_targets=len(set(targets)),accepted=entries>=2)
    return list(dict.fromkeys(targets)) if entries>=2 else []

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
    stem=f"B{bank:03X}_{pc:04X}{block.get('variant_suffix','')}"
    taken_cost=instruction_cycles(op,operand,True)-block.get('bus_fetch_cycles',0)
    def push_word(value_setup):
        return value_setup + ["move.w gb_sp,d1","subq.w #2,d1",
                              "cmpi.w #$FDFF,d1",f"blo.s .push_fast_{stem}",
                              "cmpi.w #$FF80,d1",f"blo.s .push_timed_{stem}",
                              "cmpi.w #$FFFE,d1",f"blo.s .push_fast_{stem}",
                              f".push_timed_{stem}:","jsr gb_push16_timed",f"bra.s .push_ready_{stem}",
                              f".push_fast_{stem}:","move.w d1,gb_sp","move.l d1,d4","addq.w #1,d1",
                              "move.l d3,d0","lsr.w #8,d0","jsr gb_write8","move.l d4,d1","move.l d3,d0","jsr gb_write8",f".push_ready_{stem}:"]
    def pop_word(prefix=8):
        # Only peripheral/OAM stack reads need individual bus phases. Keep
        # ordinary stack storage on the existing inline path.
        return ["cmpi.w #$FDFF,gb_sp",f"blo.s .pop_fast_{stem}",
                "cmpi.w #$FF80,gb_sp",f"bhs.s .pop_fast_{stem}",
                f"moveq #{prefix},d0","jsr gb_pop16_timed",f"bra.s .pop_ready_{stem}",f".pop_fast_{stem}:",
                "moveq #0,d1","move.w gb_sp,d1","jsr gb_read8","moveq #0,d3","move.b d0,d3","moveq #0,d1","move.w gb_sp,d1","addq.w #1,d1",
                "jsr gb_read8","lsl.w #8,d0","or.w d0,d3","addq.w #2,gb_sp",f".pop_ready_{stem}:"]
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
            else:body += ["jsr gb_idle_flag_wait"]
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
        body += pop_word(12)+["move.w d3,gb_pc","cmpi.w #$4000,d3",f"blo.s .retccfixed_{stem}","cmpi.w #$8000,d3",f"bhs.s .retccfixed_{stem}","move.w gb_rom_bank,gb_bank",f"bra.s .retccbank_{stem}",f".retccfixed_{stem}:","clr.w gb_bank",f".retccbank_{stem}:","jmp gb_dispatch"]
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
                  input_bridge_states_per_depth=8,input_sweep_steps=0,test_serial=False):
    if steps<=0:raise ValueError("steps must be positive")
    if auto_steps and (auto_max_steps<steps or (auto_chunk_steps is not None and auto_chunk_steps<=0) or auto_plateau_chunks<=0 or auto_min_new_blocks<=0):
        raise ValueError("invalid auto-step safety limits")
    if auto_inputs and min(input_max_branches,input_max_depth,input_branch_steps,input_max_steps,input_hold_frames,input_snapshot_interval_frames,input_max_snapshots,input_bridge_states_per_depth)<=0:
        raise ValueError("invalid automatic-input safety limits")
    if input_sweep_steps<0 or (input_sweep_steps and not auto_inputs):
        raise ValueError('input sweep requires --auto-inputs and a nonnegative budget')
    rom=rom_path.read_bytes();hits=collections.Counter();first={};observed=collections.defaultdict(collections.Counter);scenario_reports=[];dynamic_values=collections.defaultdict(set)
    observed_banks=collections.defaultdict(set)
    input_candidates=[];candidate_keys=set();candidate_last_frame={};sweep_start=None
    def capture_input_state(cpu,memory,origin,target,depth=0,limit=None,interval=None):
        if not auto_inputs or not reads_joypad(cpu,memory):return
        frame=memory.cycles//70224;interval=input_snapshot_interval_frames if interval is None else interval
        if frame<candidate_last_frame.get(origin,-interval)+interval:return
        candidate_last_frame[origin]=frame;key=exploration_state_key(cpu)
        if key in candidate_keys:return
        candidate_keys.add(key)
        if limit is None or len(target)<limit:target.append((copy.deepcopy(cpu),depth,origin,frame,key))
    def trace_step(cpu,memory,scenario_keys):
        cpu.step()
        # Record the bytes actually fetched by the CPU after its M-cycle bus
        # transition. Peeking before step() is wrong for DMA-contended OAM and
        # also invents instructions during HALT or interrupt dispatch.
        if cpu.last_instruction is None:return
        pc=cpu.last_pc;bank=cpu.last_bank;key=(bank,pc);raw=cpu.last_instruction;hits[key]+=1
        observed_banks[key].add(memory.rom_bank)
        observed[key][raw]+=1
        if key not in scenario_keys:
            first.setdefault(key,raw);scenario_keys.add(key)
    scenarios=[{"name":"no-input","events":[]}]+list(input_scenarios or [])
    for scenario_index,scenario in enumerate(scenarios):
        memory=SerialTestMemory(rom) if test_serial else Memory(rom);cpu=CPU(memory);scenario_keys=set();applied_memory_events=set()
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
        if input_sweep_steps and scenario_index==0:sweep_start=copy.deepcopy(cpu)
    exploration_report={"enabled":auto_inputs,"branches_executed":0,"steps_executed":0,
                        "limits":{"max_branches":input_max_branches,"max_depth":input_max_depth,
                                  "branch_steps":input_branch_steps,"max_steps":input_max_steps,
                                  "hold_frames":input_hold_frames,
                                  "snapshot_interval_frames":input_snapshot_interval_frames,
                                  "max_snapshots":input_max_snapshots,
                                  "sweep_steps":input_sweep_steps,
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
        if input_sweep_steps:
            cpu=sweep_start;memory=cpu.m;start_frame=memory.cycles//70224
            policy=InputSweep(start_frame,input_hold_frames)
            candidates=collections.deque(maxlen=min(16,input_max_snapshots))
            limit=min(input_sweep_steps,input_max_steps);before=len(first)
            print(f'auto-input sweep: up to {limit} steps within the input safety limit',flush=True)
            for executed in range(1,limit+1):
                memory.joypad_state=policy.state(memory.cycles//70224)
                capture_input_state(cpu,memory,'sweep',candidates,0,interval=input_snapshot_interval_frames)
                trace_step(cpu,memory,exploration_keys)
                if executed%1_000_000==0:
                    print(f'auto-input sweep: {executed} steps, +{len(first)-before} blocks, frame {memory.cycles//70224}',flush=True)
            new_blocks=len(first)-before
            exploration_report['branches_executed']=1
            exploration_report['steps_executed']=limit
            exploration_report['sweep_steps_executed']=limit
            exploration_report['sweep_new_blocks']=new_blocks
            exploration_report['branches'].append({'kind':'sweep','depth':0,'action':'varied-start-a',
                'source_frame':start_frame,'steps':limit,'new_blocks':new_blocks,
                'end_pc':cpu.pc,'end_bank':memory.rom_bank if 0x4000<=cpu.pc<0x8000 else 0,
                'press_count':policy.press_count,'stop_reason':'input safety limit reached' if limit<input_sweep_steps else 'sweep instruction limit reached'})
            # Continue ordinary exploration from recent progressed input states.
            # Macro timing is discovery-only; native code still polls real pads.
            for candidate in candidates:queue.appendleft(candidate)
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
                elif depth<input_max_depth and local_candidates and bridge_counts[depth]<input_bridge_states_per_depth:
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
    expanded=set();indirect_table_targets=set();hl_table_targets=set();rst_table_targets=set();banked_thunk_targets=set();constant_bank_targets=set();far_table_targets=set();bank_context_targets=set();far_table_reports=[];far_call_targets=set();far_call_returns=set();bitmask_targets=set()
    def rom_key(source_key,address):
        address &= 0xFFFF;source_bank,source_pc=source_key
        if address < 0x4000:return (0,address)
        # ROM-only cartridges have a fixed upper window even when the
        # branch originates in the lower window. No bank-state inference
        # is needed (or safe to assume for banked cartridges).
        if address < 0x8000 and rom[0x147] in (0x00,0x08,0x09):return (1,address)
        if address < 0x8000 and 0x4000 <= source_pc < 0x8000:return (source_bank,address)
        if 0xFF80 <= address < 0xFFFF:return (0,address)
        return None
    def add_rom_block(key):
        if key is None or key in first:return
        bank,pc=key
        if pc < 0x4000:offset=pc;limit=0x4000
        elif pc < 0x8000 and (bank or 0x19<=rom[0x147]<=0x1E):offset=bank*0x4000+pc-0x4000;limit=0x8000
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
    def bounded_pointer_table(source_key,table,max_entries=64,stop_at_targets=False,diagnostics=None):
        """Return consecutive, validated ROM code pointers from ``table``.

        A minimum length is enforced by callers.  The first invalid pointer
        terminates the table, preventing speculative scanning through adjacent
        data or instructions.
        """
        candidates=[];source_bank,_=source_key;table_offset=None;code_end=None;stop_reason='entry_limit'
        window_end=0x4000 if table<0x4000 else 0x8000
        for index in range(max_entries):
            address=(table+index*2)&0xFFFF
            if address+1>=0x8000 or stop_at_targets and address+1>=window_end:
                stop_reason='table_boundary';break
            if address<0x4000:entry_offset=address
            elif rom[0x147] in (0,8,9):entry_offset=address
            elif source_bank or (0x4000<=source_key[1]<0x8000 and 0x19<=rom[0x147]<=0x1E):entry_offset=source_bank*0x4000+address-0x4000
            else:stop_reason='unknown_bank';break
            if table_offset is None:table_offset=entry_offset
            if code_end is not None and entry_offset+2>code_end:
                stop_reason='code_boundary';break
            if entry_offset+1>=len(rom):stop_reason='table_boundary';break
            target=rom[entry_offset]|rom[entry_offset+1]<<8;target_key=rom_key(source_key,target)
            if target_key is None:stop_reason='non_code_pointer';break
            target_bank,target_pc=target_key
            target_offset=target_pc if target_pc<0x4000 else target_bank*0x4000+target_pc-0x4000
            if target_offset>=len(rom) or family(rom[target_offset]) in ("INVALID","STOP"):
                stop_reason='non_code_pointer';break
            candidates.append(target_key)
            if stop_at_targets and target_offset//0x4000==table_offset//0x4000 and target_offset>table_offset:
                code_end=target_offset if code_end is None else min(code_end,target_offset)
        if diagnostics is not None:diagnostics['stop_reason']=stop_reason
        return candidates
    # Interrupt entry is asynchronous and target timing can take a vector that
    # a finite reference trace did not. Compile every non-padding cartridge
    # vector independently of whether the oracle happened to service it.
    for vector in (0x40,0x48,0x50,0x58,0x60):
        if vector < len(rom) and rom[vector] not in (0x00,0xFF):add_rom_block((0,vector))
    ram_callback_analyzer=RamCallbackAnalyzer(rom,_selected_bank_candidates)
    ram_callback_targets=set();ram_callback_returns=set();ram_callback_report={}
    indexed_call_targets=set();indexed_call_returns=set();indexed_call_reports=[]
    analyzed_size=-1;warned_contexts=set();warned_pair_limit=False
    while frontier or analyzed_size!=len(first):
        if not frontier:
            analyzed_size=len(first)
            ram_callback_report=ram_callback_analyzer.discover(first.keys())
            for target_key in sorted(ram_callback_report['targets']):
                add_rom_block(target_key)
                if target_key in first:ram_callback_targets.add(target_key)
            for return_key in sorted(ram_callback_report['returns']):
                add_rom_block(return_key)
                if return_key in first:ram_callback_returns.add(return_key)
            for context in ram_callback_report['exhausted_contexts']:
                if context not in warned_contexts:
                    print(f'warning: RAM callback context at $00:${context:04X} reached its analysis budget',flush=True)
                    warned_contexts.add(context)
            if ram_callback_report['pair_limit_reached'] and not warned_pair_limit:
                print('warning: RAM callback record-pair analysis budget reached',flush=True)
                warned_pair_limit=True
            if not frontier:break
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
            rst_candidates=bounded_pointer_table(key,fall) if is_inline_rst_dispatch(rom,vector) else []
            if len(rst_candidates)>=2:
                successors=[vector]
                for target_key in rst_candidates:
                    rst_table_targets.add(target_key);indirect_table_targets.add(target_key);add_rom_block(target_key)
                    # The exact dispatcher preserves the ROM mapping. A fixed
                    # table target that immediately JP's to the upper window
                    # also preserves it. Use observed caller mappings (or the
                    # caller's upper-window identity), never a unique-address
                    # guess. Other fixed-ROM paths need fuller bank dataflow.
                    target_pc=target_key[1]
                    if target_pc+3<=min(len(rom),0x4000) and rom[target_pc]==0xC3:
                        destination=rom[target_pc+1]|rom[target_pc+2]<<8
                        contexts=observed_banks.get(key,set()) or ({bank} if 0x4000<=pc<0x8000 else set())
                        if 0x4000<=destination<0x8000:
                            for active_bank in contexts:
                                thunk=(active_bank,destination);add_rom_block(thunk)
                                if thunk in first:banked_thunk_targets.add(thunk)
            else:successors=[fall,vector]
        elif fam in ("RET_CC",):successors=[fall]
        elif fam not in ("RET","RETI","JP_HL","HALT","STOP","INVALID","UNCLASSIFIED"):
            successors=[fall]
        for address in successors:add_rom_block(rom_key(key,address))
        if op in (0x06,0x21):
            far_call_diagnostic={}
            for target_key in constant_far_call_targets(rom,bank,pc,diagnostics=far_call_diagnostic):
                add_rom_block(target_key)
                if target_key in first:far_call_targets.add(target_key)
            if far_call_diagnostic:
                return_key=far_call_diagnostic['return_target'];add_rom_block(return_key)
                if return_key in first:far_call_returns.add(return_key)
        if op==0x3E and pc<0x4000:
            site=constant_bank_call_site(rom,pc)
            if site is not None:
                call_pc,candidates=site
                for target_key in candidates:
                    add_rom_block(target_key)
                    if target_key in first:constant_bank_targets.add(target_key)
                    for context_target in fixed_bank_context_targets(rom,target_key[0],call_pc):
                        add_rom_block(context_target)
                        if context_target in first:bank_context_targets.add(context_target)
        # Resolve a common bounded ROM dispatch idiom:
        #   LD HL,table / CALL index_helper / JP (HL)
        # The helper selects a little-endian pointer from the table. Require
        # at least two consecutive, valid ROM code pointers and stop at the
        # first invalid entry; this avoids treating arbitrary data as code.
        if op==0x21 and pc+7<=0x8000:
            for target_key in bitmask_dispatch_targets(rom,bank,pc):
                add_rom_block(target_key)
                if target_key in first:
                    bitmask_targets.add(target_key);indirect_table_targets.add(target_key)
            table_diagnostic={}
            for target_key in banked_pointer_table_targets(rom,bank,pc,diagnostics=table_diagnostic):
                add_rom_block(target_key)
                if target_key in first:
                    far_table_targets.add(target_key);indirect_table_targets.add(target_key)
            if table_diagnostic:
                far_table_reports.append(table_diagnostic)
                if table_diagnostic['stop_reason']=='entry_limit':
                    print(f"warning: banked table at ${bank:02X}:${pc:04X} reached its {table_diagnostic['entry_limit']}-entry discovery limit",flush=True)
            if pc<0x4000:sequence_offset=pc
            elif bank:sequence_offset=bank*0x4000+pc-0x4000
            else:sequence_offset=-1
            sequence=rom[sequence_offset:sequence_offset+7] if sequence_offset>=0 else b""
            dispatch_diagnostic={}
            table=hl_dispatch_table(rom,bank,pc,dispatch_diagnostic)
            if table is None and len(sequence)==7 and sequence[0]==0x21 and sequence[3]==0xCD and sequence[6]==0xE9:
                table=sequence[1]|sequence[2]<<8
            if table is not None:
                scan_diagnostic={}
                candidates=bounded_pointer_table(key,table,max_entries=dispatch_diagnostic.get('entry_limit',64),
                    stop_at_targets=bool(dispatch_diagnostic),diagnostics=scan_diagnostic)
                if len(candidates)>=dispatch_diagnostic.get('min_entries',2):
                    for target_key in candidates:
                        hl_table_targets.add(target_key);indirect_table_targets.add(target_key);add_rom_block(target_key)
                        if dispatch_diagnostic and target_key in first:indexed_call_targets.add(target_key)
                    if dispatch_diagnostic:
                        return_key=rom_key(key,dispatch_diagnostic['return_address']);add_rom_block(return_key)
                        if return_key in first:indexed_call_returns.add(return_key)
                        indexed_call_reports.append(dict(bank=bank,pc=pc,table=table,
                            helper=dispatch_diagnostic['helper'],return_address=dispatch_diagnostic['return_address'],
                            entries=len(candidates),entry_limit=128,stop_reason=scan_diagnostic['stop_reason']))
    blocks=[]
    for (bank,pc),count in sorted(hits.items()):
        raw=first[(bank,pc)]; operand=(raw[1] if len(raw)==2 else (raw[1]|raw[2]<<8 if len(raw)==3 else 0))
        block={"bank":bank,"pc":pc,"opcode":raw[0],"operand":operand,"bytes":raw.hex(),"family":family(raw[0]),"hits":count}
        block["observed_variants"]=[value.hex() for value in observed[(bank,pc)] if value!=raw]
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
        safe=True;has_read=False;read_addresses=[]
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
            if fam=="LDH_A_A8":read_addresses.append(0xFF00|(item["operand"]&255))
            elif fam=="LD_A_A16":read_addresses.append(item["operand"])
            elif (fam in ("LDH_A_C","LD_A_RR")
                  or fam=="LD_R_R" and (item["opcode"]&7)==6
                  or fam=="CB" and (item["operand"]&7)==6):
                # Unknown addresses may be hardware registers. LD A,(HL+/-)
                # additionally changes HL on each iteration and is not idle.
                safe=False
        if safe and has_read:
            # Only an exact LY equality wait may jump to a chosen scanline.
            # Inequalities/leave-this-line loops must observe intermediate LY.
            if (len(loop)==2 and loop[0]["family"]=="LDH_A_A8" and loop[0]["operand"]==0x44
                and loop[1]["family"]=="CP_A_D8" and loop[1]["operand"]<154 and block["opcode"]==0x20):
                block["idle_wait"]=True
                block["idle_ly_target"]=loop[1]["operand"]
            elif read_addresses and all(0xC000<=a<0xFE00 or 0xFF80<=a<0xFFFF for a in read_addresses):
                block["idle_wait"]=True
    for block in blocks:block["native_lowered"]=native_body(block) is not None
    out.mkdir(parents=True,exist_ok=True)
    (out/"trace-profile.json").write_text(json.dumps({"input":str(rom_path),"steps_per_scenario":steps,"auto_steps":auto_steps,"auto_inputs":auto_inputs,"test_serial":test_serial,"total_steps_executed":sum(s["steps_executed"] for s in scenario_reports),"dynamic_unique_blocks":dynamic_unique_block_count,"indirect_table_targets":len(indirect_table_targets),"hl_pointer_table_targets":len(hl_table_targets),"bitmask_dispatch_targets":len(bitmask_targets),"rst_inline_table_targets":len(rst_table_targets),"banked_thunk_targets":len(banked_thunk_targets),"constant_bank_call_targets":len(constant_bank_targets),"constant_far_call_targets":len(far_call_targets),"constant_far_call_returns":len(far_call_returns),"banked_pointer_table_targets":len(far_table_targets),"banked_pointer_tables":far_table_reports,"bank_context_targets":len(bank_context_targets),"indexed_call_targets":len(indexed_call_targets),"indexed_call_returns":len(indexed_call_returns),"indexed_call_tables":indexed_call_reports,"ram_callback_targets":len(ram_callback_targets),"ram_callback_returns":len(ram_callback_returns),"ram_callback_records":ram_callback_report.get("records",[]),"ram_callback_analysis_limits":{"pair_limit_reached":ram_callback_report.get("pair_limit_reached",False),"exhausted_contexts":ram_callback_report.get("exhausted_contexts",[])},"total_blocks_after_static_closure":len(blocks),"input_exploration":exploration_report,"scenarios":scenario_reports,"blocks":blocks},indent=2)+"\n")
    emit_native_blocks(blocks,out)
    return blocks

def emit_native_blocks(blocks,out,dispatch_format="auto",max_hot_chains=None,include_block_table=True,optimize_pure_chains=True):
    """Emit validated block metadata without repeating reference discovery."""
    if max_hot_chains is not None and max_hot_chains<0:raise ValueError('negative hot chain limit')
    blocks=[dict(block) for block in blocks]
    for block in blocks:
        pc=block['pc'];raws=[bytes.fromhex(x) for x in (block['bytes'],*block.get('observed_variants',[]))]
        end=0xE000 if 0xC000<=pc<0xE000 else 0xFE00
        if len(raws)>1 and 0xC000<=pc<0xFE00 and any(pc+len(raw)>end for raw in raws):
            # Keep mixed-opcode/length discovery conservative. Uniform native
            # variants can fetch their bytes across logical memory windows.
            if len({(raw[0],len(raw)) for raw in raws})!=1:
                raise RuntimeError(f'dynamic code variant crosses WRAM window at ${pc:04X} with differing opcode/length')
            block['bus_fetch_cycles']=len(raws[0])*4
    used=sorted({b["family"] for b in blocks if not b["native_lowered"]})
    label=lambda b:f"L_gb_B{b['bank']:03X}_{b['pc']:04X}"
    block_by_key={(b["bank"],b["pc"]):b for b in blocks}
    chain_targets=set();incoming_costs=collections.defaultdict(set);source_edges=collections.defaultdict(set)
    def pure_cycles(block,body):
        if block.get('bus_fetch_cycles'):return None
        op=block["opcode"]
        register_only=(op in (0,0x01,0x11,0x21,0x31,0x03,0x13,0x23,0x33,0x0B,0x1B,0x2B,0x3B,0x07,0x0F,0x17,0x1F,0x27,0x2F,0x37,0x3F,0xE8,0xF8,0xF9)
                       or op<0x40 and op&7 in (4,5,6) and (op>>3)&7!=6
                       or 0x40<=op<0x80 and op&7!=6 and (op>>3)&7!=6
                       or 0x80<=op<0xC0 and op&7!=6
                       or op in (0xC6,0xCE,0xD6,0xDE,0xE6,0xEE,0xF6,0xFE)
                       or op==0xCB and block["operand"]&7!=6)
        if register_only and not any(line.startswith("jsr ") for line in body):
            return instruction_cycles(op,block["operand"],False)
        return None
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
                elif 0x4000<=block["pc"]<0x8000:target_key=(block["bank"],current_target)
                # Fixed-ROM callers have no proven active cartridge bank.
                # One observed target is coverage, not a bank invariant.
            if statement=="jmp gb_dispatch" and target_key in block_by_key and block["family"] not in ("HALT","STOP"):
                # The edge stub writes PC only when it actually flushes the
                # scheduler. Straight-line code does not otherwise observe PC,
                # so avoid one absolute RAM write per emulated instruction.
                if current_store_index is not None:result[current_store_index]=None
                result.append(f"jmp gb_chain_B{target_key[0]:03X}_{target_key[1]:04X}");chain_targets.add(target_key)
                incoming_costs[target_key].add(pure_cycles(block,body))
                source_edges[(block["bank"],block["pc"],block["bytes"])].add(target_key)
            else:result.append(statement)
        return [statement for statement in result if statement is not None]
    # Discover incoming edge costs first: a shared target can use a constant
    # only when EVERY statically chained predecessor has the same safe cost.
    threaded_bodies={}
    for block in blocks:
        variants=[block]
        for raw_hex in block.get("observed_variants",[]):
            raw=bytes.fromhex(raw_hex)
            variants.append({**block,"opcode":raw[0],"operand":raw[1] if len(raw)==2 else (raw[1]|raw[2]<<8 if len(raw)==3 else 0),"bytes":raw_hex,"family":family(raw[0]),"observed_variants":[]})
        for index,variant in enumerate(variants):
            if len(variants)>1:variant={**variant,"variant_suffix":f"_V{index}"}
            body=native_body(variant)
            if body is not None:
                threaded_bodies[(variant['bank'],variant['pc'],variant['bytes'])]=thread_static_dispatch(variant,body)
    hot_candidates=sorted((key for key in chain_targets if block_by_key[key]['hits']>0),
                          key=lambda key:(-block_by_key[key]['hits'],key))
    hot_targets=set(hot_candidates if max_hot_chains is None else hot_candidates[:max_hot_chains])
    constant_costs={key:next(iter(costs)) for key,costs in incoming_costs.items()
                    if optimize_pure_chains and key in hot_targets and len(costs)==1 and None not in costs}
    elided_cycle_stores=0
    entry=next((b for b in blocks if b["bank"] == 0 and b["pc"] == 0x100),blocks[0])
    lines=["; Trace-guided static LR35902 -> 68000 block output.","\txdef gb_compiled_entry,gb_compiled_block_table,gb_dispatch_tree"]
    lines += ["gb_compiled_entry:",f"\tbra.w {label(entry)}",""]
    for block in blocks:
        lines.append(f"{label(block)}:")
        variants=[block]
        for raw_hex in block.get("observed_variants",[]):
            raw=bytes.fromhex(raw_hex);operand=raw[1] if len(raw)==2 else (raw[1]|raw[2]<<8 if len(raw)==3 else 0)
            variants.append({**block,"opcode":raw[0],"operand":operand,"bytes":raw_hex,"family":family(raw[0]),"observed_variants":[]})
        if len(variants)>1:
            pc=block["pc"];resolver=f"{block['bank']:03X}_{pc:04X}"
            if block.get('bus_fetch_cycles'):
                for offset in range(block['bus_fetch_cycles']//4):
                    lines += [f"\tmove.w #${pc+offset:04X},d1","\tjsr gb_fetch_read8",f"\tmove.b d0,gb_fetch_bytes+{offset}"]
                lines += ["\tlea gb_fetch_bytes,a0"]
                base=0
            elif 0xFE00<=pc<0xFEA0:
                ff_index=next((index for index,item in enumerate(variants) if item["bytes"]=="ff"),None)
                lines += ["\ttst.b gb_dma_active",f"\tbeq.s .dynamic_accessible_{resolver}"]
                lines += [f"\tbra.w .dynamic_variant_{resolver}_{ff_index}" if ff_index is not None else f"\tbra.w .dynamic_missing_{resolver}",f".dynamic_accessible_{resolver}:","\tlea gb_oam,a0"]
                base=pc-0xFE00
            elif 0xC000<=pc<0xFE00:
                # WRAM and its echo share storage but retain logical PCs.
                # Only observed byte sequences are compiled, never decoded
                # dynamically by the target runtime.
                lines += ["\tlea gb_wram,a0"]
                base=pc-(0xC000 if pc<0xE000 else 0xE000)
                end=0xE000 if pc<0xE000 else 0xFE00
                if any(pc+len(bytes.fromhex(v['bytes']))>end for v in variants):
                    raise RuntimeError(f"dynamic code variant crosses WRAM window at ${pc:04X}")
            elif 0xFF80<=pc<0xFFFF:
                lines += ["\tlea gb_hram,a0"]
                base=pc-0xFF80
            else:
                raise RuntimeError(f"unsupported dynamic code variants at bank {block['bank']} PC ${pc:04X}: "+", ".join(item["bytes"] for item in variants))
            for index,variant in enumerate(variants):
                raw=bytes.fromhex(variant["bytes"]);next_label=f".dynamic_next_{resolver}_{index}"
                for offset,value in enumerate(raw):
                    lines += [f"\tcmpi.b #${value:02X},{base+offset}(a0)",f"\tbne.w {next_label}"]
                lines += [f"\tbra.w .dynamic_variant_{resolver}_{index}",f"{next_label}:"]
            lines += [f".dynamic_missing_{resolver}:",f"\tmove.w #${pc:04X},gb_pc","\tjmp gb_missing_block"]
            variants=[{**variant,"variant_suffix":f"_V{index}"} for index,variant in enumerate(variants)]
        for index,variant in enumerate(variants):
            if len(variants)>1:
                lines.append(f".dynamic_variant_{block['bank']:03X}_{block['pc']:04X}_{index}:")
            identity=(variant['bank'],variant['pc'],variant['bytes'])
            edges=source_edges.get(identity,set())
            elide=not variant.get('bus_fetch_cycles') and bool(edges) and all(target in constant_costs for target in edges)
            if not elide:
                cost=instruction_cycles(variant['opcode'],variant['operand'],False)-variant.get('bus_fetch_cycles',0)
                lines.append(f"\tmove.b #{cost},gb_step_cycles")
            else:elided_cycle_stores+=1
            direct=threaded_bodies.get(identity)
            if direct is not None: lines += [f"\t{x}" for x in direct]+[""]
            else:
                lines += [f"\tmove.w #${variant['bank']:04X},gb_bank",f"\tmove.w #${variant['pc']:04X},gb_pc",
                          f"\tmove.b #${variant['opcode']:02X},gb_opcode",f"\tmove.w #${variant['operand']:04X},gb_operand",
                          f"\tjsr gbop_{variant['family'].lower()}","\tjmp gb_dispatch",""]
    # Hot constant successors above jump through these shared chain stubs.
    # gb_tick may redirect execution for an IRQ, so validate PC/bank before
    # entering the successor. Returns, JP (HL), mapper changes, and IRQ entry
    # continue through the general dispatcher below.
    compact_targets=chain_targets-hot_targets
    for bank,target in sorted(chain_targets):
        stem=f"B{bank:03X}_{target:04X}"
        if (bank,target) in compact_targets:
            # Static coverage and rarely visited paths can be large. Share
            # the scheduler body without discarding any translated entries.
            # The 68000 return address is the native destination, not a GB
            # interpreter entry. No host temporary except d7 is live here.
            lines += [f"gb_chain_{stem}:",f"\tmove.w #${target:04X},d0",f"\tmove.w #${bank:04X},d1",
                      f"\tpea {label(block_by_key[(bank,target)])}","\tjmp gb_chain_compact",""]
            continue
        cost=constant_costs.get((bank,target))
        if cost is not None:
            add=f"addq.w #{cost},d7" if cost<=8 else f"addi.w #{cost},d7"
            lines += [f"gb_chain_{stem}:","\ttst.b gb_force_tick",f"\tbne.s .chain_flush_{stem}",
                      "\ttst.b gb_ei_delay",f"\tbne.s .chain_flush_{stem}",
                      f"\tcmpi.w #{SCHEDULER_BATCH_T_CYCLES-cost},d7",f"\tbhs.s .chain_flush_{stem}",
                      "\t"+add,f"\tjmp {label(block_by_key[(bank,target)])}",
                      f".chain_flush_{stem}:",f"\tmove.b #{cost},gb_step_cycles","\tclr.b gb_force_tick",f"\tmove.w #${target:04X},gb_pc","\tjsr gb_tick","\ttst.b gb_halted",f"\tbeq.s .chain_awake_{stem}","\tjmp gb_dispatch",f".chain_awake_{stem}:",f"\tcmpi.w #${bank:04X},gb_bank",f"\tbeq.s .chain_bank_ok_{stem}","\tjmp gb_dispatch_tree",f".chain_bank_ok_{stem}:",f"\tcmpi.w #${target:04X},gb_pc",f"\tbeq.s .chain_pc_ok_{stem}","\tjmp gb_dispatch_tree",f".chain_pc_ok_{stem}:",f"\tjmp {label(block_by_key[(bank,target)])}",""]
        else:
            lines += [f"gb_chain_{stem}:","\ttst.b gb_force_tick",f"\tbne.s .chain_flush_{stem}","\ttst.b gb_ei_delay",f"\tbne.s .chain_flush_{stem}","\tmoveq #0,d0","\tmove.b gb_step_cycles,d0","\tmoveq #0,d1","\tmove.w d7,d1","\tadd.w d0,d1",f"\tcmpi.w #{SCHEDULER_BATCH_T_CYCLES},d1",f"\tbhs.s .chain_flush_{stem}","\tmove.w d1,d7",f"\tjmp {label(block_by_key[(bank,target)])}",f".chain_flush_{stem}:","\tclr.b gb_force_tick",f"\tmove.w #${target:04X},gb_pc","\tjsr gb_tick","\ttst.b gb_halted",f"\tbeq.s .chain_awake_{stem}","\tjmp gb_dispatch",f".chain_awake_{stem}:",f"\tcmpi.w #${bank:04X},gb_bank",f"\tbeq.s .chain_bank_ok_{stem}","\tjmp gb_dispatch_tree",f".chain_bank_ok_{stem}:",f"\tcmpi.w #${target:04X},gb_pc",f"\tbeq.s .chain_pc_ok_{stem}","\tjmp gb_dispatch_tree",f".chain_pc_ok_{stem}:",f"\tjmp {label(block_by_key[(bank,target)])}",""]
    if compact_targets:
        lines += ["gb_chain_compact:","\ttst.b gb_force_tick","\tbne.s .compact_flush",
                  "\ttst.b gb_ei_delay","\tbne.s .compact_flush","\tmoveq #0,d2",
                  "\tmove.b gb_step_cycles,d2","\tadd.w d7,d2",
                  f"\tcmpi.w #{SCHEDULER_BATCH_T_CYCLES},d2","\tbhs.s .compact_flush",
                  "\tmove.w d2,d7","\trts",".compact_flush:","\tmove.w d0,gb_pc",
                  "\tmove.w d1,-(sp)","\tmove.w d0,-(sp)","\tclr.b gb_force_tick",
                  "\tjsr gb_tick","\ttst.b gb_halted","\tbne.s .compact_halted",
                  "\tmove.w (sp)+,d0","\tcmp.w gb_pc,d0","\tbne.s .compact_pc_changed",
                  "\tmove.w (sp)+,d0","\tcmp.w gb_bank,d0","\tbne.s .compact_bank_changed",
                  "\trts",".compact_halted:","\taddq.l #8,sp","\tjmp gb_dispatch",
                  ".compact_pc_changed:","\taddq.l #6,sp","\tjmp gb_dispatch_tree",
                  ".compact_bank_changed:","\taddq.l #4,sp","\tjmp gb_dispatch_tree",""]
    # Retain the entry symbol used by the runtime, but use bank -> PC page ->
    # instruction pointer tables. Only populated 256-byte pages need storage.
    # All holes point to the existing diagnostic, including absent banks.
    pages={};banks={b['bank'] for b in blocks};max_bank=max(banks)
    for block in blocks:
        pages.setdefault((block['bank'],block['pc']>>8),{})[block['pc']&255]=label(block)
    page_bytes=4*(max_bank+1)+1024*(2+len(banks)+len(pages))
    if dispatch_format not in ('auto','paged','tree'):raise ValueError('unknown native dispatch format')
    use_pages=dispatch_format=='paged' or dispatch_format=='auto' and page_bytes+96<24*len(blocks)
    if use_pages:
        lines += ["gb_dispatch_tree:","\tjsr gb_normalize_bank","\tmoveq #0,d0",
              "\tmove.w gb_bank,d0",f"\tcmpi.w #${max_bank:04X},d0","\tbls.s .dispatch_bank_in_range",
              "\tjmp gb_missing_block",".dispatch_bank_in_range:",
              "\tlsl.w #2,d0","\tlea gb_dispatch_banks,a0","\tmovea.l (a0,d0.w),a0",
              "\tmoveq #0,d0","\tmove.w gb_pc,d0","\tlsr.w #8,d0","\tlsl.w #2,d0",
              "\tmovea.l (a0,d0.w),a0","\tmoveq #0,d0","\tmove.b gb_pc+1,d0",
              "\tlsl.w #2,d0","\tmovea.l (a0,d0.w),a0","\tjmp (a0)","\teven",
                  "gb_dispatch_banks:"]
    def pointers(values):
        for index in range(0,len(values),8):lines.append("\tdc.l "+",".join(values[index:index+8]))
    if use_pages:
        pointers([f'gb_dispatch_bank_{bank:03X}' if bank in banks else 'gb_dispatch_empty_bank'
                  for bank in range(max_bank+1)])
        lines += ['gb_dispatch_empty_bank:','\tdcb.l 256,gb_dispatch_empty_page',
                  'gb_dispatch_empty_page:','\tdcb.l 256,gb_missing_block']
        for bank in sorted(banks):
            lines.append(f'gb_dispatch_bank_{bank:03X}:')
            pointers([f'gb_dispatch_page_{bank:03X}_{page:02X}' if (bank,page) in pages else 'gb_dispatch_empty_page'
                      for page in range(256)])
        for (bank,page),entries in sorted(pages.items()):
            lines.append(f'gb_dispatch_page_{bank:03X}_{page:02X}:')
            pointers([entries.get(offset,'gb_missing_block') for offset in range(256)])
    else:
        # Sparse/tiny programs keep the smaller original decision tree.
        lines += ["gb_dispatch_tree:","\tjsr gb_normalize_bank","\tmoveq #0,d0","\tmove.w gb_bank,d0","\tswap d0","\tmove.w gb_pc,d0","\tjmp .dispatch_node_0"]
        ordered=sorted(blocks,key=lambda b:(b['bank']<<16)|b['pc'])
        def tree(lo,hi,node):
            if lo>=hi:return [f'.dispatch_node_{node}:','\tjmp gb_missing_block']
            mid=(lo+hi)//2;b=ordered[mid];key=(b['bank']<<16)|b['pc'];left=node*2+1;right=node*2+2
            result=[f'.dispatch_node_{node}:',f'\tcmpi.l #${key:08X},d0',f'\tbne.s .dispatch_not_equal_{node}',f'\tjmp {label(b)}',f'.dispatch_not_equal_{node}:',f'\tbhs.s .dispatch_not_lower_{node}']
            result += [f'\tjmp .dispatch_node_{left}' if lo<mid else '\tjmp gb_missing_block',f'.dispatch_not_lower_{node}:',f'\tjmp .dispatch_node_{right}' if mid+1<hi else '\tjmp gb_missing_block']
            return result+tree(lo,mid,left)+tree(mid+1,hi,right)
        lines += tree(0,len(ordered),0)
    lines += ["\teven","gb_compiled_block_table:"]
    if include_block_table:
        for block in blocks: lines += [f"\tdc.w ${block['bank']:04X},${block['pc']:04X}",f"\tdc.l {label(block)}"]
    lines += ["\tdc.w $FFFF,$FFFF","\tdc.l 0"]
    (out/"translated_trace.s").write_text("\n".join(lines))
    (out/"native-codegen-report.json").write_text(json.dumps({
        "blocks":len(blocks),"chain_targets":len(chain_targets),
        "compact_chain_targets":len(compact_targets),
        "hot_chain_targets":len(chain_targets)-len(compact_targets),
        "hot_chain_limit":max_hot_chains,
        "optimize_pure_chains":optimize_pure_chains,
        "constant_cycle_chain_targets":len(constant_costs),
        "elided_cycle_stores":elided_cycle_stores,
        "block_catalog_included":include_block_table,
        "block_catalog_bytes":8*(len(blocks)+1) if include_block_table else 8,
        "dispatch_format":"bank_page_table" if use_pages else "balanced_tree",
        "dispatch_pages":len(pages) if use_pages else 0,
        "dispatch_table_bytes":page_bytes if use_pages else 0},indent=2)+"\n")
    return blocks

def main():
    p=argparse.ArgumentParser();p.add_argument("rom",type=pathlib.Path);p.add_argument("--out",type=pathlib.Path,default=pathlib.Path("build"));p.add_argument("--steps",type=int,default=100000);p.add_argument("--auto-steps",action="store_true");p.add_argument("--auto-max-steps",type=int,default=50_000_000);p.add_argument("--auto-chunk-steps",type=int);p.add_argument("--auto-plateau-chunks",type=int,default=3);p.add_argument("--auto-min-new-blocks",type=int,default=1);p.add_argument("--auto-inputs",action="store_true");p.add_argument("--input-max-branches",type=int,default=128);p.add_argument("--input-max-depth",type=int,default=4);p.add_argument("--input-branch-steps",type=int,default=150_000);p.add_argument("--input-max-steps",type=int,default=20_000_000);p.add_argument("--input-sweep-steps",type=int,default=0);p.add_argument("--input-hold-frames",type=int,default=4);p.add_argument("--input-snapshot-interval-frames",type=int,default=4);p.add_argument("--input-max-snapshots",type=int,default=1024);p.add_argument("--input-bridge-states-per-depth",type=int,default=8);p.add_argument("--input-script",action="append",default=[],metavar="PULSES",help="merge a trace such as start@512:8,a@560:4");ns=p.parse_args()
    blocks=compile_trace(ns.rom,ns.out,ns.steps,[parse_input_script(s) for s in ns.input_script],ns.auto_steps,ns.auto_max_steps,ns.auto_chunk_steps,ns.auto_plateau_chunks,ns.auto_min_new_blocks,ns.auto_inputs,ns.input_max_branches,ns.input_max_depth,ns.input_branch_steps,ns.input_max_steps,ns.input_hold_frames,ns.input_snapshot_interval_frames,ns.input_max_snapshots,ns.input_bridge_states_per_depth,ns.input_sweep_steps);print(f"wrote {len(blocks)} traced static blocks to {ns.out/'translated_trace.s'}")
if __name__ == "__main__":main()
