#!/usr/bin/env python3
"""Trace, assemble, and checksum a first-stage recompiled Genesis ROM."""
from __future__ import annotations
import argparse,json,os,pathlib,shutil,subprocess,struct
from trace_recompiler import compile_trace,parse_input_script
from color_profiles import COLOR_PROFILES

ROOT=pathlib.Path(__file__).parent

def find_assembler(explicit=None):
    """Resolve an external vasmm68k_mot without requiring a bundled copy."""
    candidates=[]
    if explicit:candidates.append(pathlib.Path(explicit).expanduser())
    if os.environ.get("GB2MD_VASM"):candidates.append(pathlib.Path(os.environ["GB2MD_VASM"]).expanduser())
    if found:=shutil.which("vasmm68k_mot"):candidates.append(pathlib.Path(found))
    # Development compatibility only; the public repository does not bundle it.
    candidates.append(ROOT/"vasm"/"vasmm68k_mot")
    for candidate in candidates:
        if candidate.is_file():return candidate.resolve()
    raise FileNotFoundError("vasmm68k_mot not found; use --assembler, GB2MD_VASM, or PATH")

def build(source,out,steps=100000,color_profile="green",input_scripts=(),auto_steps=False,auto_max_steps=50_000_000,auto_chunk_steps=None,auto_plateau_chunks=3,auto_min_new_blocks=1,auto_inputs=False,input_max_branches=128,input_max_depth=4,input_branch_steps=150_000,input_max_steps=20_000_000,input_hold_frames=4,input_snapshot_interval_frames=4,input_max_snapshots=1024,input_bridge_states_per_depth=8,assembler=None):
    out.mkdir(parents=True,exist_ok=True); rom_data=source.read_bytes(); scenarios=[parse_input_script(s) if isinstance(s,str) else s for s in input_scripts];blocks=compile_trace(source,out,steps,scenarios,auto_steps,auto_max_steps,auto_chunk_steps,auto_plateau_chunks,auto_min_new_blocks,auto_inputs,input_max_branches,input_max_depth,input_branch_steps,input_max_steps,input_hold_frames,input_snapshot_interval_frames,input_max_snapshots,input_bridge_states_per_depth)
    profile=COLOR_PROFILES[color_profile]
    equates=[f"gb_shade{i} equ ${v:04X}" for i,v in enumerate(profile["shades"])]
    equates += [f"gb_shell{i} equ ${v:04X}" for i,v in enumerate(profile["shell"])]
    (out/"color_profile.s").write_text("\n".join(equates)+"\n")
    plane=[]
    for y in range(32):
        for x in range(64):
            word=0x2000|641
            if 8<=x<=31 and 3<=y<=24: word=0x2000|642
            # The LCD backing is a low-priority Plane B colour-4 tile. Plane
            # A leaves GB colour 0 transparent, allowing GB priority sprites
            # to sit behind colours 1-3 but in front of this backing.
            if 10<=x<=29 and 5<=y<=22: word=643
            plane.append(word)
    frame=["\teven","gb_frame_plane:"]
    for row in range(0,2048,8): frame.append("\tdc.w "+",".join(f"${v:04X}" for v in plane[row:row+8]))
    frame += ["gb_frame_tiles:","\tdc.l $12121212,$21212121,$12121212,$21212121,$12121212,$21212121,$12121212,$21212121","\tdcb.l 8,$33333333","\tdcb.l 8,$44444444"]
    (out/"frame_data.s").write_text("\n".join(frame)+"\n")
    missing=sorted({b["family"].lower() for b in blocks if not b["native_lowered"]})
    stub=["; Unlowered families stop with a diagnostic marker in Genesis RAM."]
    for number,name in enumerate(missing,1): stub += [f"gbop_{name}:",f"\tmove.l #${0xBAD00000|number:08X},$FF0018","\tbra.w gb_unimplemented"]
    stub += ["gb_unimplemented:",
             "; Green backdrop means translated GB initialization reached the first unfinished family.",
             "\tmove.w #$8104,$C00004","\tmove.l #$C0000000,$C00004","\tmove.w #$0000,$C00000","\tmove.w #$00E0,$C00000",
             "\tmove.w #$8701,$C00004","\tmove.w #$8174,$C00004",".status_loop:","\tbra.s .status_loop"]
    (out/"unimplemented_68000.s").write_text("\n".join(stub)+"\n")
    # Lookup table used by the live renderer.  The index is HHLL where HH is
    # four GB high-plane bits and LL is four low-plane bits; the value is four
    # Genesis 4bpp pixels in display order.
    chunky=[]
    for index in range(256):
        lo=index&15; hi=index>>4; word=0
        for bit in range(3,-1,-1): word=(word<<4)|(((hi>>bit)&1)*2+((lo>>bit)&1))
        chunky.append(word)
    table=["\teven","gb_2bpp_nibble_table:"]
    for row in range(0,256,8): table.append("\tdc.w "+",".join(f"${v:04X}" for v in chunky[row:row+8]))
    (out/"renderer_table.s").write_text("\n".join(table)+"\n")
    main=f'''gb_mapper_type equ ${rom_data[0x147]:02X}
\tinclude "{(out/'color_profile.s').absolute().as_posix()}"
\tsection rom,code
\torg $000000
\tdc.l $00FFFFFC,reset
\tdcb.l 62,0
\torg $000100
\tdc.b "SEGA GENESIS    "
\torg $000120
\tdc.b "GB2MD RECOMPILED GAME CORE"
\torg $000150
\tdc.b "GB2MD RECOMPILED GAME CORE"
\torg $000180
\tdc.b "GM 00000001-00"
\torg $00018E
\tdc.w 0
\torg $0001A0
\tdc.l $00000000,$0007FFFF,$00FF0000,$00FFFFFF
\torg $0001F0
\tdc.b "JUE"
\torg $000200
reset:
\tmove.w #$2700,sr
\tmove.w #$8004,$C00004
\tmove.w #$8104,$C00004
\tmove.w #$8230,$C00004
\tmove.w #$833C,$C00004
\tmove.w #$8407,$C00004
\tmove.w #$8578,$C00004
\tmove.w #$8700,$C00004
\tmove.w #$8B00,$C00004
\tmove.w #$8C81,$C00004
\tmove.w #$8D3F,$C00004
\tmove.w #$8F02,$C00004
\tmove.w #$9001,$C00004
\tmove.l #$40000000,$C00004
\tmoveq #0,d0
\tmove.w #$7FFF,d1
.clear_vdp:
\tmove.w d0,$C00000
\tdbf d1,.clear_vdp
\tmove.l #$50200001,$C00004
\tlea gb_frame_tiles,a0
\tmove.w #47,d1
.copy_frame_tiles:
\tmove.w (a0)+,$C00000
\tdbf d1,.copy_frame_tiles
\tmove.l #$60000003,$C00004
\tlea gb_frame_plane,a0
\tmove.w #2047,d1
.copy_frame_plane:
\tmove.w (a0)+,$C00000
\tdbf d1,.copy_frame_plane
\tmove.l #$C0000000,$C00004
\tmove.w #$0000,$C00000
\tmove.w #$000E,$C00000
\tmove.l #$C0080000,$C00004
\tmove.w #gb_shade0,$C00000
\tmove.l #$C0200000,$C00004
\tmove.w #gb_shell0,$C00000
\tmove.w #gb_shell1,$C00000
\tmove.w #gb_shell2,$C00000
\tmove.w #gb_shell3,$C00000
\tmove.l #$C0400000,$C00004
\tmove.w #0,$C00000
\tmove.w #gb_shade0,$C00000
\tmove.w #$8700,$C00004
\tmove.w #$8174,$C00004
\tmove.b #$40,$A10009
\tmove.b #$40,$A10003
\tlea $FF0000,a0
\tmoveq #0,d0
\tmove.w #$3FFF,d1
.clear_ram:
\tmove.l d0,(a0)+
\tdbf d1,.clear_ram
\tmove.b #1,gb_a
\tmove.b #$B0,gb_f
\tmove.b #$13,gb_c
\tmove.b #$D8,gb_e
\tmove.b #1,gb_h
\tmove.b #$4D,gb_l
\tmove.w #$FFFE,gb_sp
\tmove.w #1,gb_rom_bank
\tmove.b #gb_mapper_type,gb_mapper_kind
\tmove.b #$CF,gb_io
\tmove.b #$91,gb_io+$40
\tmove.b #$FC,gb_io+$47
\tmoveq #0,d7
\tmove.l #$C0000000,$C00004
\tmove.w #$0000,$C00000
\tmove.w #$0E00,$C00000
\tjmp gb_compiled_entry
\tinclude "{(ROOT/'runtime_68000.s').as_posix()}"
\tinclude "{(out/'translated_trace.s').absolute().as_posix()}"
\tinclude "{(out/'unimplemented_68000.s').absolute().as_posix()}"
	include "{(out/'renderer_table.s').absolute().as_posix()}"
	include "{(out/'frame_data.s').absolute().as_posix()}"
\teven
gb_cart_rom:
\tincbin "{source.absolute().as_posix()}"
'''
    assembly=out/"recompiled_rom.s";assembly.write_text(main)
    binary=out/"recompiled.md";assembler=find_assembler(assembler)
    raw_binary=out/"recompiled.raw.bin"
    subprocess.run([str(assembler),"-m68000","-Fbin",str(assembly),"-o",str(raw_binary)],check=True)
    image=bytearray(raw_binary.read_bytes()); size=max(0x80000,(len(image)+1)&~1)
    if size>0x400000:
        raise ValueError(f"native image needs {size:,} bytes, exceeding the supported 4 MiB cartridge window; "
                         "larger Genesis cartridge mapping is not implemented. Existing recompiled.md was preserved.")
    image.extend(bytes(size-len(image)))
    struct.pack_into(">I",image,0x1A4,size-1)
    checksum=sum(struct.unpack_from(">H",image,i)[0] for i in range(0x200,size,2))&0xFFFF;struct.pack_into(">H",image,0x18E,checksum);binary.write_bytes(image)
    trace_report=json.loads((out/"trace-profile.json").read_text())
    build_report={
        "source":str(source),"steps_per_scenario":steps,"auto_steps":auto_steps,"auto_inputs":auto_inputs,
        "trace_steps_executed":trace_report["total_steps_executed"],
        "dynamic_unique_blocks":trace_report["dynamic_unique_blocks"],
        **{name:trace_report.get(name,0) for name in (
            "indirect_table_targets","hl_pointer_table_targets","rst_inline_table_targets",
            "constant_bank_call_targets","banked_pointer_table_targets","bank_context_targets")},
        "trace_stop_reasons":[s["stop_reason"] for s in trace_report["scenarios"]],
        "input_exploration":trace_report["input_exploration"],"input_scripts":list(input_scripts),
        "color_profile":color_profile,"blocks":len(blocks),
        "native_blocks":sum(b["native_lowered"] for b in blocks),"unlowered_families":missing,
        "rom_bytes":size,"checksum":checksum}
    (out/"build-report.json").write_text(json.dumps(build_report,indent=2)+"\n")
    return binary
def main():
    p=argparse.ArgumentParser();p.add_argument("rom",type=pathlib.Path);p.add_argument("--out",type=pathlib.Path,default=pathlib.Path("build-recompiled"));p.add_argument("--steps",type=int,default=100000,help="fixed steps per scenario, or initial auto-step chunk");p.add_argument("--auto-steps",action="store_true",help="extend scenarios while new blocks are discovered");p.add_argument("--auto-max-steps",type=int,default=50_000_000);p.add_argument("--auto-chunk-steps",type=int);p.add_argument("--auto-plateau-chunks",type=int,default=3);p.add_argument("--auto-min-new-blocks",type=int,default=1);p.add_argument("--auto-inputs",action="store_true",help="branch from JOYP reads using bounded controller exploration");p.add_argument("--input-max-branches",type=int,default=128);p.add_argument("--input-max-depth",type=int,default=4);p.add_argument("--input-branch-steps",type=int,default=150_000);p.add_argument("--input-max-steps",type=int,default=20_000_000);p.add_argument("--input-hold-frames",type=int,default=4);p.add_argument("--input-snapshot-interval-frames",type=int,default=4);p.add_argument("--input-max-snapshots",type=int,default=1024);p.add_argument("--input-bridge-states-per-depth",type=int,default=8);p.add_argument("--color-profile",choices=sorted(COLOR_PROFILES),default="green");p.add_argument("--assembler",type=pathlib.Path,help="external vasmm68k_mot path (or set GB2MD_VASM)");p.add_argument("--input-script",action="append",default=[],metavar="PULSES",help="merge an input-guided trace, e.g. start@512:8,a@560:4");a=p.parse_args();print(build(a.rom,a.out,a.steps,a.color_profile,a.input_script,a.auto_steps,a.auto_max_steps,a.auto_chunk_steps,a.auto_plateau_chunks,a.auto_min_new_blocks,a.auto_inputs,a.input_max_branches,a.input_max_depth,a.input_branch_steps,a.input_max_steps,a.input_hold_frames,a.input_snapshot_interval_frames,a.input_max_snapshots,a.input_bridge_states_per_depth,a.assembler))
if __name__=="__main__":main()
