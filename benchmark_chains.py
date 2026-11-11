#!/usr/bin/env python3
"""A/B native scheduler throughput using original bounded benchmark fixtures.

Measures source T cycles per Genesis frame, not host wall-clock speed or game
FPS. Baseline and optimized modes compile identical dynamically traced entries.
"""
import argparse,json,os,re,shutil
from pathlib import Path
from build_recompiled import build
from run_compat_tests import _run_in_pty,_blastem_values


def benchmark_rom(workload):
    prefix=bytes.fromhex('f3afe040') if workload!='video' else b'\xf3'
    setup,loop={'register':('06010e021603','040d78a957'),
                'memory':('2100c00601','347e807704'),
                'video':('2100800601','787704')}[workload]
    program=prefix+bytes.fromhex(setup);body=bytes.fromhex(loop)
    program+=body+bytes([0x18,(-len(body)-2)&255])
    rom=bytearray(0x8000);rom[0x100:0x103]=bytes.fromhex('c35001');rom[0x150:0x150+len(program)]=program
    return bytes(rom)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=Path('compat-builds/chain-benchmark'))
    parser.add_argument('--frames',type=int,default=180)
    parser.add_argument('--blastem',type=Path,default=Path(os.environ.get('GB2MD_BLASTEM') or shutil.which('blastem') or 'blastem'))
    args=parser.parse_args()
    if not 60<=args.frames<=1800:parser.error('frames must be60..1800')
    if 'test_roms' in args.out.resolve().parts:parser.error('immutable fixture tree cannot be output')
    args.out.mkdir(parents=True,exist_ok=True);results={}
    for workload in ('register','memory','video'):
        source=args.out/(workload+'.gb');source.write_bytes(benchmark_rom(workload));modes={}
        for enabled in (False,True):
            name='optimized' if enabled else 'baseline';out=args.out/workload/name
            artifact=build(source,out,2000,optimize_pure_chains=enabled)
            query='p/x [$ff0002].w [$ff0010].w [$ff0018].l [$ff0038].l [$ff0020].l\n'
            commands=f'frames {args.frames}\n'+query+f'frames {args.frames}\n'+query+'quit\n'
            code,output,timed=_run_in_pty([str(args.blastem.resolve()),'-d',str(artifact.resolve())],commands,max(30,args.frames//30+15))
            (out/'native.log').write_text(output);values=_blastem_values(output)
            cycles=[int(v,16) for v in re.findall(r'\[\$ff0020\]\.l:\s*([0-9a-f]+)',output,re.I)]
            if timed or code or len(cycles)!=2 or values.get('FF0018.l')!=0 or values.get('FF0038.l')!=0:
                raise RuntimeError(f'{workload}/{name}: failed observation; inspect native.log')
            if not 0x150<=values.get('FF0002.w',0)<0x170 or values.get('FF0010.w')!=0xFFFE:
                raise RuntimeError('CPU escaped benchmark loop')
            profile=json.loads((out/'trace-profile.json').read_text());stats=json.loads((out/'native-codegen-report.json').read_text())
            delta=(cycles[1]-cycles[0])&0xFFFFFFFF
            modes[name]={'cycles':cycles,'interval_cycles':delta,'source_cycles_per_genesis_frame':delta/args.frames,'rom_bytes':artifact.stat().st_size,'entries':len(profile['blocks']),'constant_cycle_chain_targets':stats['constant_cycle_chain_targets'],'elided_cycle_stores':stats['elided_cycle_stores']}
        modes['throughput_ratio']=modes['optimized']['interval_cycles']/modes['baseline']['interval_cycles'];results[workload]=modes
    report={'scope':'Original loops only; not measured game FPS or whole-system profiling','genesis_frames_per_interval':args.frames,'results':results}
    (args.out/'benchmark.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
