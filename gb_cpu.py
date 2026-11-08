"""Portable LR35902 execution oracle for GB2MD.

The translator uses this small, dependency-free implementation to validate
decoded instructions and game boot paths before lowering them to 68000.  It is
also the semantic reference for the future generated 68000 runtime.
"""
from __future__ import annotations
from collections import Counter

Z, N, H, C = 0x80, 0x40, 0x20, 0x10

def instruction_cycles(op: int, operand: int = 0, taken: bool = False) -> int:
    """Return LR35902 T-cycles for an instruction.

    ``operand`` is the CB sub-opcode when ``op`` is $CB.  Conditional control
    flow uses ``taken`` to select the longer timing.  Keeping this table beside
    the semantic oracle lets trace discovery and the generated 68000 scheduler
    share one timing contract.
    """
    op &= 0xFF
    if op == 0xCB:
        sub = operand & 0xFF
        if (sub & 7) != 6: return 8
        return 12 if (sub >> 6) == 1 else 16
    if 0x40 <= op < 0x80:
        if op == 0x76: return 4
        return 8 if ((op >> 3) & 7) == 6 or (op & 7) == 6 else 4
    if 0x80 <= op < 0xC0: return 8 if (op & 7) == 6 else 4
    if op in (0x01,0x11,0x21,0x31): return 12
    if op in (0x02,0x12,0x22,0x32,0x0A,0x1A,0x2A,0x3A): return 8
    if op in (0x03,0x13,0x23,0x33,0x0B,0x1B,0x2B,0x3B): return 8
    if op in (0x09,0x19,0x29,0x39): return 8
    if op in (0x34,0x35): return 12
    if op in (0x04,0x0C,0x14,0x1C,0x24,0x2C,0x3C,
              0x05,0x0D,0x15,0x1D,0x25,0x2D,0x3D): return 4
    if op == 0x36: return 12
    if op in (0x06,0x0E,0x16,0x1E,0x26,0x2E,0x3E): return 8
    if op == 0x08: return 20
    if op == 0x18: return 12
    if op in (0x20,0x28,0x30,0x38): return 12 if taken else 8
    if op in (0xC3,): return 16
    if op in (0xC2,0xCA,0xD2,0xDA): return 16 if taken else 12
    if op == 0xE9: return 4
    if op == 0xCD: return 24
    if op in (0xC4,0xCC,0xD4,0xDC): return 24 if taken else 12
    if op in (0xC9,0xD9): return 16
    if op in (0xC0,0xC8,0xD0,0xD8): return 20 if taken else 8
    if op in (0xC1,0xD1,0xE1,0xF1): return 12
    if op in (0xC5,0xD5,0xE5,0xF5): return 16
    if op in (0xC6,0xCE,0xD6,0xDE,0xE6,0xEE,0xF6,0xFE): return 8
    if op in (0xC7,0xCF,0xD7,0xDF,0xE7,0xEF,0xF7,0xFF): return 16
    if op in (0xE0,0xF0): return 12
    if op in (0xE2,0xF2): return 8
    if op in (0xEA,0xFA): return 16
    if op == 0xE8: return 16
    if op == 0xF8: return 12
    if op == 0xF9: return 8
    return 4

class Memory:
    def __init__(self, rom: bytes):
        if len(rom) < 0x150: raise ValueError("not a Game Boy ROM")
        self.rom = rom; self.vram = bytearray(0x2000); self.wram = bytearray(0x2000)
        self.oam = bytearray(0xA0); self.hram = bytearray(0x7F); self.io = bytearray(0x80)
        self.ie = 0
        self.io[0] = 0xCF  # FF00: no buttons pressed after the DMG boot ROM
        # FF04 exposes the upper byte of this internal divider. TIMA clocks on
        # falling edges of a TAC-selected divider bit.
        self.div_counter = 0
        self.timer_reload_delay = 0
        self.timer_reloaded_this_cycle = False
        # OAM DMA is an M-cycle state machine rather than an instantaneous
        # copy.  FF46 writes pass through requested -> starting -> active,
        # which preserves the two-cycle startup/restart behaviour measured by
        # the Mooneye acceptance tests.  Active transfers copy one byte every
        # four T-cycles and keep OAM inaccessible until the final byte lands.
        self.dma_requested = None
        self.dma_starting = None
        self.dma_active = False
        self.dma_source = 0xFF
        self.dma_index = 0
        self.dma_phase = 0
        # Active-low: bits 0-3 are Right/Left/Up/Down and bits 4-7 are
        # A/B/Select/Start.  Tests and trace discovery can inject input here.
        self.joypad_state = 0xFF
        self.mapper = rom[0x147]; self.rom_bank = 1; self.ram_bank = 0; self.ram_enabled = False; self.mbc1_mode = 0
        ram_sizes={0:0,1:0x800,2:0x2000,3:0x8000,4:0x20000,5:0x10000}; self.eram=bytearray(ram_sizes.get(rom[0x149],0))
        self.cycles = 0
        self.stat_line = False
    def read(self, a):
        a &= 0xFFFF
        if a < 0x4000: return self.rom[a] if a < len(self.rom) else 0xFF
        if a < 0x8000:
            offset=self.rom_bank*0x4000+(a-0x4000)
            return self.rom[offset] if offset < len(self.rom) else 0xFF
        if 0x8000 <= a < 0xA000: return self.vram[a-0x8000]
        if 0xA000 <= a < 0xC000:
            offset=self.ram_bank*0x2000+a-0xA000
            return self.eram[offset] if self.ram_enabled and offset < len(self.eram) else 0xFF
        if 0xC000 <= a < 0xE000: return self.wram[a-0xC000]
        if 0xE000 <= a < 0xFE00: return self.wram[a-0xE000]
        if 0xFE00 <= a < 0xFEA0:
            return 0xFF if self._dma_blocks_oam() else self.oam[a-0xFE00]
        if a == 0xFF00:
            select=self.io[0]&0x30; low=0x0F
            if not select&0x10: low &= self.joypad_state&0x0F
            if not select&0x20: low &= (self.joypad_state>>4)&0x0F
            return 0xC0|select|low
        if a == 0xFF07:return self.io[0x07]|0xF8
        if a == 0xFF41:return self.io[0x41]|0x80
        if a == 0xFF0F:return self.io[0x0F]|0xE0
        if 0xFF00 <= a < 0xFF80: return self.io[a-0xFF00]
        if 0xFF80 <= a < 0xFFFF: return self.hram[a-0xFF80]
        return self.ie if a == 0xFFFF else 0xFF
    def write(self, a, v, bus_phase=0):
        a &= 0xFFFF; v &= 0xFF
        if a < 0x8000: self.mapper_write(a,v)
        elif 0x8000 <= a < 0xA000: self.vram[a-0x8000] = v
        elif 0xA000 <= a < 0xC000:
            offset=self.ram_bank*0x2000+a-0xA000
            if self.ram_enabled and offset < len(self.eram): self.eram[offset]=v
        elif 0xC000 <= a < 0xE000: self.wram[a-0xC000] = v
        elif 0xE000 <= a < 0xFE00: self.wram[a-0xE000] = v
        elif 0xFE00 <= a < 0xFEA0:
            if not self._dma_blocks_oam():self.oam[a-0xFE00] = v
        elif 0xFF00 <= a < 0xFF80:
            if a == 0xFF00:self.io[0]=0xC0|(v&0x30)|0x0F
            elif a == 0xFF04:
                old_signal=self._timer_signal();self.div_counter=0;self.io[0x04]=0
                if old_signal and not self._timer_signal():self._timer_increment()
            elif a == 0xFF05:
                # A TIMA write on the reload cycle is ignored. Earlier writes
                # in the four-cycle overflow window cancel the reload.
                if not self.timer_reloaded_this_cycle:
                    self.io[0x05]=v
                    if self.timer_reload_delay:self.timer_reload_delay=0
            elif a == 0xFF06:
                self.io[0x06]=v
                if self.timer_reloaded_this_cycle:self.io[0x05]=v
            elif a == 0xFF07:
                # The TAC bus write occurs in LDH's final machine cycle. The
                # instruction-level core reaches us four T-cycles later, so
                # evaluate its mux transition at the divider phase that was
                # present on that bus cycle.
                edge_counter=(self.div_counter-bus_phase)&0xFFFF
                old_signal=self._timer_signal(edge_counter,self.io[0x07]);self.io[0x07]=v&7
                if old_signal and not self._timer_signal(edge_counter,self.io[0x07]):
                    self._timer_increment()
                    if self.timer_reload_delay==4:
                        self.timer_reload_delay=0;self.io[0x05]=self.io[0x06];self.io[0x0F]|=4;self.timer_reloaded_this_cycle=True
            elif a == 0xFF0F:self.io[0x0F]=v&0x1F
            elif a == 0xFF41:self.io[0x41]=(v&0x78)|(self.io[0x41]&7)
            elif a == 0xFF44:pass
            else:self.io[a-0xFF00] = v
            if a in (0xFF40,0xFF41,0xFF45):self._update_stat(self.cycles)
            if a == 0xFF46:
                self.dma_requested = v
        elif 0xFF80 <= a < 0xFFFF: self.hram[a-0xFF80] = v
        elif a == 0xFFFF: self.ie = v
    def mapper_write(self,a,v):
        """MBC1/MBC3/MBC5 bank controls; ROM-only writes intentionally do nothing."""
        if self.mapper in (1,2,3):
            if a < 0x2000:self.ram_enabled=(v&15)==10
            elif a < 0x4000:self.rom_bank=(self.rom_bank&0x60)|(v&0x1F) or 1
            elif a < 0x6000:
                if self.mbc1_mode:self.ram_bank=v&3
                else:self.rom_bank=((v&3)<<5)|(self.rom_bank&0x1F)
            else:self.mbc1_mode=v&1
        elif self.mapper in (0x0F,0x10,0x11,0x12,0x13):
            if a < 0x2000:self.ram_enabled=(v&15)==10
            elif a < 0x4000:self.rom_bank=(v&0x7F) or 1
            elif a < 0x6000:self.ram_bank=v&3 # RTC selections are added by the timer layer
        elif self.mapper in range(0x19,0x1F):
            if a < 0x2000:self.ram_enabled=(v&15)==10
            elif a < 0x3000:self.rom_bank=(self.rom_bank&0x100)|v
            elif a < 0x4000:self.rom_bank=((v&1)<<8)|(self.rom_bank&0xFF)
            elif a < 0x6000:self.ram_bank=v&15
    def _timer_signal(self, counter=None, tac=None):
        counter=self.div_counter if counter is None else counter
        tac=self.io[0x07] if tac is None else tac
        bit=(9,3,5,7)[tac&3]
        return bool(tac&4 and counter&(1<<bit))
    def _timer_increment(self):
        if self.timer_reload_delay:return
        if self.io[0x05]==0xFF:self.io[0x05]=0;self.timer_reload_delay=4
        else:self.io[0x05]=(self.io[0x05]+1)&0xFF
    def _dma_read(self, a):
        """Read a DMA source byte without applying CPU-side OAM blocking."""
        a &= 0xFFFF
        if a < 0x4000:return self.rom[a] if a < len(self.rom) else 0xFF
        if a < 0x8000:
            offset=self.rom_bank*0x4000+(a-0x4000)
            return self.rom[offset] if offset < len(self.rom) else 0xFF
        if a < 0xA000:return self.vram[a-0x8000]
        if a < 0xC000:
            offset=self.ram_bank*0x2000+a-0xA000
            return self.eram[offset] if self.ram_enabled and offset < len(self.eram) else 0xFF
        # DMA source pages E0-FF mirror the corresponding C0-DF WRAM pages;
        # unlike CPU reads, FE/FF do not select OAM or I/O during the transfer.
        return self.wram[(a-0xC000)&0x1FFF]
    def _dma_blocks_oam(self):
        # CPU bus helpers advance the current M-cycle before sampling memory,
        # so the startup transition has already promoted ``starting`` to an
        # active transfer when OAM must become inaccessible.
        return self.dma_active
    def _dma_machine_cycle(self):
        # An existing transfer continues during both restart pipeline cycles.
        if self.dma_active:
            self.oam[self.dma_index] = self._dma_read((self.dma_source<<8)|self.dma_index)
            self.dma_index += 1
            if self.dma_index >= 0xA0:self.dma_active=False
        if self.dma_starting is not None:
            self.dma_source=self.dma_starting;self.dma_starting=None
            self.dma_index=0;self.dma_active=True
        if self.dma_requested is not None:
            self.dma_starting=self.dma_requested;self.dma_requested=None
    def _tick_dma(self, n):
        self.dma_phase += n
        while self.dma_phase >= 4:
            self.dma_phase -= 4
            self._dma_machine_cycle()
    def _update_stat(self, cycles):
        """Baseline fixed-length PPU modes; mode 3 stall timing is still open."""
        ly=(cycles//456)%154;dot=cycles%456
        mode=1 if ly>=144 else (2 if dot<80 else 3 if dot<252 else 0)
        enabled=bool(self.io[0x40]&0x80)
        if not enabled:mode=0
        equal=ly==self.io[0x45]
        self.io[0x41]=(self.io[0x41]&0x78)|mode|(4 if equal else 0)
        line=enabled and bool((equal and self.io[0x41]&0x40) or
            (mode==0 and self.io[0x41]&8) or (mode==1 and self.io[0x41]&16) or
            (mode==2 and self.io[0x41]&32))
        if line and not self.stat_line:self.io[0x0F]|=2
        self.stat_line=line

    def tick(self, n=4):
        old=self.io[0x44]
        self.timer_reloaded_this_cycle=False
        if not (self.io[0x07]&4) and not self.timer_reload_delay:
            # Most software leaves TIMA disabled. This fast path is exactly
            # equivalent because a disabled timer signal cannot have an edge.
            self.div_counter=(self.div_counter+n)&0xFFFF;self.io[0x04]=self.div_counter>>8
        else:
            for _ in range(n):
                self.timer_reloaded_this_cycle=False
                if self.timer_reload_delay:
                    self.timer_reload_delay-=1
                    if not self.timer_reload_delay:
                        self.io[0x05]=self.io[0x06];self.io[0x0F]|=4;self.timer_reloaded_this_cycle=True
                old_signal=self._timer_signal();self.div_counter=(self.div_counter+1)&0xFFFF;self.io[0x04]=self.div_counter>>8
                if old_signal and not self._timer_signal():self._timer_increment()
        self._tick_dma(n)
        start=self.cycles;end=start+n
        # Visit mode/line edges even when the caller advances a large batch.
        cursor=start
        while cursor<end:
            dot=cursor%456
            boundary=80 if dot<80 else 252 if dot<252 else 456
            cursor=min(end,cursor+boundary-dot)
            self._update_stat(cursor)
        self.cycles = end
        self.io[0x44] = (self.cycles // 456) % 154 # LY approximation for boot-path waits
        if old != 144 and self.io[0x44] == 144: self.io[0x0F] |= 1

class CPU:
    def __init__(self, memory: Memory):
        self.m = memory
        # DMG post-boot state, i.e. code begins at cartridge entry $0100.
        self.a,self.f,self.b,self.c,self.d,self.e,self.h,self.l = 1,0xB0,0,0x13,0,0xD8,1,0x4D
        self.sp,self.pc,self.ime,self.halted,self.ei_delay = 0xFFFE,0x100,False,False,0
        self.halt_bug=False
        self.last_instruction=None;self.last_pc=None;self.last_bank=0;self._instruction_bytes=None
        self.opcode_count=Counter()
    def hl(self): return (self.h << 8) | self.l
    def set_hl(self,v): self.h=(v>>8)&255; self.l=v&255
    def bc(self): return (self.b << 8) | self.c
    def de(self): return (self.d << 8) | self.e
    def set_bc(self,v): self.b=(v>>8)&255; self.c=v&255
    def set_de(self,v): self.d=(v>>8)&255; self.e=v&255
    def idle_cycle(self): self.m.tick(4)
    def read_cycle(self,a):
        self.m.tick(4)
        return self.m.read(a)
    def write_cycle(self,a,v):
        self.m.tick(4)
        self.m.write(a,v,bus_phase=4)
    def fetch8(self):
        v=self.read_cycle(self.pc)
        if self._instruction_bytes is not None:self._instruction_bytes.append(v)
        if self.halt_bug:self.halt_bug=False
        else:self.pc=(self.pc+1)&0xFFFF
        return v
    def fetch16(self): return self.fetch8() | (self.fetch8()<<8)
    def flag(self, bit): return bool(self.f & bit)
    def flags(self,z=None,n=None,h=None,c=None):
        for bit,val in ((Z,z),(N,n),(H,h),(C,c)):
            if val is not None: self.f = (self.f | bit) if val else (self.f & ~bit)
        self.f &= 0xF0
    def r(self, n): return self.read_cycle(self.hl()) if n == 6 else (self.b,self.c,self.d,self.e,self.h,self.l,0,self.a)[n]
    def set_r(self,n,v):
        v &= 255
        if n==6: self.write_cycle(self.hl(),v)
        elif n==0:self.b=v
        elif n==1:self.c=v
        elif n==2:self.d=v
        elif n==3:self.e=v
        elif n==4:self.h=v
        elif n==5:self.l=v
        else:self.a=v
    def push(self,v): self.sp=(self.sp-1)&0xFFFF; self.write_cycle(self.sp,v>>8); self.sp=(self.sp-1)&0xFFFF; self.write_cycle(self.sp,v)
    def pop(self):
        lo=self.read_cycle(self.sp); self.sp=(self.sp+1)&0xFFFF
        hi=self.read_cycle(self.sp); self.sp=(self.sp+1)&0xFFFF
        return lo | (hi<<8)
    def add_a(self,v,carry=0):
        x=self.a+v+carry; self.flags(x&255==0,False,((self.a&15)+(v&15)+carry)>15,x>255); self.a=x&255
    def sub_a(self,v,carry=0,store=True):
        x=self.a-v-carry; self.flags((x&255)==0,True,((self.a&15)-(v&15)-carry)<0,x<0)
        if store:self.a=x&255
    def cond(self,n): return (not self.flag(Z),self.flag(Z),not self.flag(C),self.flag(C))[n]
    def cb(self):
        op=self.fetch8(); n=op&7; group=op>>6; bit=(op>>3)&7; v=self.r(n)
        if group==1: self.flags(z=not bool(v&(1<<bit)),n=False,h=True); return
        if group==2: self.set_r(n,v&~(1<<bit)); return
        if group==3: self.set_r(n,v|(1<<bit)); return
        kind=(op>>3)&7; oldc=1 if self.flag(C) else 0
        if kind==0: out=((v<<1)|(v>>7))&255; c=v>>7
        elif kind==1: out=((v>>1)|((v&1)<<7))&255; c=v&1
        elif kind==2: out=((v<<1)|oldc)&255; c=v>>7
        elif kind==3: out=((v>>1)|(oldc<<7))&255; c=v&1
        elif kind==4: out=(v<<1)&255; c=v>>7
        elif kind==5: out=((v>>1)|(v&0x80))&255; c=v&1
        elif kind==6: out=((v<<4)|(v>>4))&255; c=0
        else: out=v>>1; c=v&1
        self.set_r(n,out); self.flags(out==0,False,False,bool(c))
    def step(self):
        """Execute one instruction/interrupt as explicit four-T-cycle buses."""
        self.last_pc=self.pc
        self.last_bank=self.m.rom_bank if 0x4000<=self.pc<0x8000 else 0
        self.last_instruction=None;self._instruction_bytes=[]
        self._step_base()
        if self._instruction_bytes:self.last_instruction=bytes(self._instruction_bytes)
        self._instruction_bytes=None
    def _step_base(self):
        if self.ei_delay:
            self.ei_delay -= 1
            if not self.ei_delay: self.ime=True
        pending=self.m.io[0x0F] & self.m.ie & 0x1F
        if pending:
            self.halted=False
            if self.ime:
                bit=(pending & -pending).bit_length()-1
                self.ime=False; self.m.io[0x0F] &= ~(1<<bit)
                self.idle_cycle();self.idle_cycle();self.idle_cycle();self.push(self.pc);self.pc=0x40+bit*8
                return
        if self.halted: self.idle_cycle(); return
        op=self.fetch8(); self.opcode_count[op]+=1
        if op==0xCB: self.cb(); return
        if 0x40 <= op < 0x80:
            if op==0x76:
                if pending and not self.ime:self.halt_bug=True
                else:self.halted=True
            else:self.set_r((op>>3)&7,self.r(op&7))
            return
        if 0x80 <= op < 0xC0:
            v=self.r(op&7); group=(op>>3)&7
            if group==0:self.add_a(v)
            elif group==1:self.add_a(v,1 if self.flag(C) else 0)
            elif group==2:self.sub_a(v)
            elif group==3:self.sub_a(v,1 if self.flag(C) else 0)
            elif group==4:self.a&=v; self.flags(self.a==0,False,True,False)
            elif group==5:self.a^=v; self.flags(self.a==0,False,False,False)
            elif group==6:self.a|=v; self.flags(self.a==0,False,False,False)
            else:self.sub_a(v,store=False)
            return
        # Regular 8-bit loads/inc/dec and the 16-bit register groups.
        if op in (0x00,): return
        if op in (0x01,0x11,0x21,0x31):
            v=self.fetch16(); group=(op>>4)&3
            if group==0:self.set_bc(v)
            elif group==1:self.set_de(v)
            elif group==2:self.set_hl(v)
            else:self.sp=v
            return
        if op in (0x02,0x12,0x22,0x32):
            a=(self.bc(),self.de(),self.hl(),self.hl())[(op>>4)&3]; self.write_cycle(a,self.a)
            if op==0x22:self.set_hl(a+1)
            if op==0x32:self.set_hl(a-1)
            return
        if op in (0x0A,0x1A,0x2A,0x3A):
            a=(self.bc(),self.de(),self.hl(),self.hl())[(op>>4)&3]; self.a=self.read_cycle(a)
            if op==0x2A:self.set_hl(a+1)
            if op==0x3A:self.set_hl(a-1)
            return
        if op in (0x03,0x13,0x23,0x33,0x0B,0x1B,0x2B,0x3B):
            delta=1 if op&8==0 else -1; group=(op>>4)&3; vals=[self.bc(),self.de(),self.hl(),self.sp]; vals[group]=(vals[group]+delta)&0xFFFF
            (self.set_bc(vals[0]),self.set_de(vals[1]),self.set_hl(vals[2]),setattr(self,'sp',vals[3])); self.idle_cycle(); return
        if op in (0x09,0x19,0x29,0x39):
            v=(self.bc(),self.de(),self.hl(),self.sp)[(op>>4)&3]; x=self.hl()+v; self.flags(n=False,h=((self.hl()&0xFFF)+(v&0xFFF))>0xFFF,c=x>0xFFFF); self.set_hl(x); self.idle_cycle(); return
        if op in (0x04,0x0C,0x14,0x1C,0x24,0x2C,0x34,0x3C):
            n=(op>>3)&7; v=self.r(n); out=(v+1)&255; self.set_r(n,out); self.flags(out==0,n=False,h=(v&15)==15); return
        if op in (0x05,0x0D,0x15,0x1D,0x25,0x2D,0x35,0x3D):
            n=(op>>3)&7; v=self.r(n); out=(v-1)&255; self.set_r(n,out); self.flags(out==0,n=True,h=(v&15)==0); return
        if op in (0x06,0x0E,0x16,0x1E,0x26,0x2E,0x36,0x3E): self.set_r((op>>3)&7,self.fetch8()); return
        if op==0x08: a=self.fetch16(); self.write_cycle(a,self.sp); self.write_cycle(a+1,self.sp>>8); return
        if op in (0x18,0x20,0x28,0x30,0x38):
            d=self.fetch8(); d-=256 if d&128 else 0
            if op==0x18 or self.cond((op>>3)&3): self.pc=(self.pc+d)&0xFFFF;self.idle_cycle()
            return
        if op in (0x07,0x0F,0x17,0x1F):
            c=1 if self.flag(C) else 0
            if op==0x07: out=((self.a<<1)|(self.a>>7))&255; c=self.a>>7
            elif op==0x0F: out=(self.a>>1)|((self.a&1)<<7); c=self.a&1
            elif op==0x17: out=((self.a<<1)|c)&255; c=self.a>>7
            else: out=(self.a>>1)|(c<<7); c=self.a&1
            self.a=out; self.flags(False,False,False,bool(c)); return
        if op==0x27: # DAA
            adjust=0; carry=self.flag(C)
            if not self.flag(N):
                if self.flag(H) or (self.a&15)>9: adjust|=6
                if carry or self.a>0x99: adjust|=0x60; carry=True
                self.a=(self.a+adjust)&255
            else:
                if self.flag(H): adjust|=6
                if carry: adjust|=0x60
                self.a=(self.a-adjust)&255
            self.flags(self.a==0,h=False,c=carry); return
        if op==0x2F:self.a^=255; self.flags(n=True,h=True); return
        if op==0x37:self.flags(n=False,h=False,c=True); return
        if op==0x3F:self.flags(n=False,h=False,c=not self.flag(C)); return
        if op in (0xC3,0xC2,0xCA,0xD2,0xDA):
            a=self.fetch16();
            if op==0xC3 or self.cond((op>>3)&3):self.pc=a;self.idle_cycle()
            return
        if op in (0xCD,0xC4,0xCC,0xD4,0xDC):
            a=self.fetch16()
            if op==0xCD or self.cond((op>>3)&3):self.idle_cycle();self.push(self.pc);self.pc=a
            return
        if op in (0xC9,0xC0,0xC8,0xD0,0xD8,0xD9):
            conditional=op not in (0xC9,0xD9)
            if conditional:self.idle_cycle()
            if not conditional or self.cond((op>>3)&3): self.pc=self.pop();self.idle_cycle()
            if op==0xD9:self.ime=True
            return
        if op in (0xC1,0xD1,0xE1,0xF1):
            v=self.pop(); group=(op>>4)&3
            if group==0:self.set_bc(v)
            elif group==1:self.set_de(v)
            elif group==2:self.set_hl(v)
            else:self.a=v>>8;self.f=v&0xF0
            return
        if op in (0xC5,0xD5,0xE5,0xF5): self.idle_cycle();self.push((self.bc(),self.de(),self.hl(),(self.a<<8)|self.f)[(op>>4)&3]); return
        if op in (0xC6,0xCE,0xD6,0xDE,0xE6,0xEE,0xF6,0xFE):
            v=self.fetch8(); group=(op>>3)&7
            if group==0:self.add_a(v)
            elif group==1:self.add_a(v,1 if self.flag(C) else 0)
            elif group==2:self.sub_a(v)
            elif group==3:self.sub_a(v,1 if self.flag(C) else 0)
            elif group==4:self.a&=v;self.flags(self.a==0,False,True,False)
            elif group==5:self.a^=v;self.flags(self.a==0,False,False,False)
            elif group==6:self.a|=v;self.flags(self.a==0,False,False,False)
            else:self.sub_a(v,store=False)
            return
        if op in (0xC7,0xCF,0xD7,0xDF,0xE7,0xEF,0xF7,0xFF):self.idle_cycle();self.push(self.pc);self.pc=op&0x38;return
        if op==0xE0:
            self.write_cycle(0xFF00+self.fetch8(),self.a)
            return
        if op==0xF0:self.a=self.read_cycle(0xFF00+self.fetch8());return
        if op==0xE2:self.write_cycle(0xFF00+self.c,self.a);return
        if op==0xF2:self.a=self.read_cycle(0xFF00+self.c);return
        if op==0xEA:self.write_cycle(self.fetch16(),self.a);return
        if op==0xFA:self.a=self.read_cycle(self.fetch16());return
        if op==0xE8:
            v=self.fetch8(); s=v-256 if v&128 else v; x=self.sp+s; self.flags(False,False,((self.sp&15)+(v&15))>15,((self.sp&255)+(v&255))>255);self.sp=x&0xFFFF;self.idle_cycle();self.idle_cycle();return
        if op==0xF8:
            v=self.fetch8(); s=v-256 if v&128 else v; x=self.sp+s; self.flags(False,False,((self.sp&15)+(v&15))>15,((self.sp&255)+(v&255))>255);self.set_hl(x);self.idle_cycle();return
        if op==0xF9:self.sp=self.hl();self.idle_cycle();return
        if op==0xE9:self.pc=self.hl();return
        if op==0xF3:self.ime=False;self.ei_delay=0;return
        if op==0xFB:
            # A second EI must not postpone the enable scheduled by the first.
            if not self.ime and not self.ei_delay:self.ei_delay=2
            return
        if op==0x76:self.halted=True;return
        raise NotImplementedError(f"opcode ${op:02X} at ${((self.pc-1)&0xFFFF):04X}")
