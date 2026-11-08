#!/usr/bin/env python3
"""Compare native dispatchers on an original CALL/RET/JP(HL) workload.

Unused original NOP entries create a configurable lookup-table workload. This
measures backend throughput at equal Genesis frame counts, not game FPS.
Requires external vasm and BlastEm. Never uses downloaded/commercial ROMs.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import re
import shutil
from unittest.mock import patch

import build_recompiled as compiler
from run_compat_tests import _run_in_pty, _blastem_values
from trace_recompiler import compile_trace, emit_native_blocks


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=Path('compat-builds/dispatch-benchmark'))
    parser.add_argument('--blocks',type=int,default=24000)
    parser.add_argument('--frames',type=int,default=600)
    parser.add_argument('--blastem',type=Path,default=Path(os.environ.get('GB2MD_BLASTEM') or shutil.which('blastem') or 'blastem'))
    args=parser.parse_args()
    if not 1<=args.blocks<=0x7C00 or not 1<=args.frames<=6000:parser.error('blocks/frames exceed safety bounds')
    if 'test_roms' in args.out.resolve().parts:parser.error('output must be outside immutable test_roms')
    args.out.mkdir(parents=True,exist_ok=True)
    source=args.out/'original.gb';rom=bytearray(0x8000)
    rom[0x100:0x103]=bytes.fromhex('c35001')
    program=bytes.fromhex('f3afe04031feffcd6001215701e9')
    rom[0x150:0x150+len(program)]=program;rom[0x160]=0xC9;source.write_bytes(rom)
    seed=args.out/'seed';blocks=compile_trace(source,seed,1000)
    profile=json.loads((seed/'trace-profile.json').read_text())
    for pc in range(0x400,0x400+args.blocks):
        blocks.append(dict(bank=0 if pc<0x4000 else 1,pc=pc,opcode=0,operand=0,
                           bytes='00',family='NOP',hits=0,observed_variants=[],native_lowered=True))
    blocks.sort(key=lambda b:(b['bank'],b['pc']))
    results={}
    for mode in ('tree','paged'):
        out=args.out/mode
        def replay(*unused,**kwargs):
            entries=copy.deepcopy(blocks);out.mkdir(parents=True,exist_ok=True)
            (out/'trace-profile.json').write_text(json.dumps(dict(profile,blocks=entries,
                total_blocks_after_static_closure=len(entries),synthetic_unused_entries=args.blocks),indent=2)+'\n')
            emit_native_blocks(entries,out,dispatch_format=mode);return entries
        with patch.object(compiler,'compile_trace',side_effect=replay):compiler.build(source,out,1000)
        query='p/x [$ff0002].w [$ff0010].w [$ff0018].l [$ff0038].l [$ff0020].l\n'
        commands=f'frames {args.frames}\n'+query+f'frames {args.frames}\n'+query+'quit\n'
        code,output,timed=_run_in_pty([str(args.blastem.resolve()),'-d',str((out/'recompiled.md').resolve())],commands,max(45,args.frames//30+15))
        (out/'native.log').write_text(output);values=_blastem_values(output)
        cycles=[int(v,16) for v in re.findall(r'\[\$ff0020\]\.l:\s*([0-9a-f]+)',output,re.I)]
        if timed or code or len(cycles)!=2 or values.get('FF0018.l')!=0 or values.get('FF0038.l')!=0:
            raise RuntimeError(f'{mode}: incomplete/failed native observation; inspect native.log')
        if values.get('FF0002.w') not in (0x157,0x15A,0x15D,0x160) or values.get('FF0010.w') not in (0xFFFC,0xFFFE):
            raise RuntimeError(f'{mode}: CPU left the expected original loop')
        delta=(cycles[1]-cycles[0])&0xFFFFFFFF
        results[mode]=dict(cycles=cycles,interval_cycles=delta,cycles_per_genesis_frame=delta/args.frames,
                           rom_bytes=(out/'recompiled.md').stat().st_size)
    report=dict(scope='original dispatch-heavy CPU loop, not game FPS',frames_per_interval=args.frames,
                unused_blocks=args.blocks,results=results,
                paged_throughput_ratio=results['paged']['interval_cycles']/results['tree']['interval_cycles'])
    (args.out/'benchmark.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
