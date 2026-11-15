#!/usr/bin/env python3
"""Original-code HRAM A/B: source-cycle throughput, not game or wall-clock FPS."""
import argparse,json,os,re,shutil
from pathlib import Path
from build_recompiled import build
from run_compat_tests import _run_in_pty,_blastem_values


def benchmark_rom(workload):
    setup=bytes.fromhex('f331fedfafe040e0073e5ae0f00601')
    body=bytes.fromhex({'read':'f0f080','write':'e0f03c',
                        'absolute':'faf0ffeaf1ff','io-control':'f07fe07f3c'}[workload])
    code=setup+body+bytes([0x18,(-len(body)-2)&255])
    rom=bytearray(0x8000);rom[0x100:0x103]=bytes.fromhex('c35001')
    rom[0x150:0x150+len(code)]=code
    return bytes(rom)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=Path('compat-builds/hram-benchmark'))
    parser.add_argument('--frames',type=int,default=180)
    parser.add_argument('--blastem',type=Path,default=Path(os.environ.get('GB2MD_BLASTEM') or shutil.which('blastem') or 'blastem'))
    args=parser.parse_args()
    if not 60<=args.frames<=1800:parser.error('frames must be60..1800')
    if 'test_roms' in args.out.resolve().parts:parser.error('immutable fixture tree cannot be output')
    if args.out.exists() and any(args.out.iterdir()):parser.error('choose a new empty output directory')
    args.out.mkdir(parents=True,exist_ok=True);results={}
    for workload in ('read','write','absolute','io-control'):
        source=args.out/(workload+'.gb');source.write_bytes(benchmark_rom(workload));modes={};identities=[]
        for enabled in (False,True):
            mode='direct' if enabled else 'generic';out=args.out/workload/mode
            image=build(source,out,2000,optimize_hram=enabled)
            query='p/x [$ff0002].w [$ff0010].w [$ff0018].l [$ff0038].l [$ff0020].l\n'
            command=f'frames {args.frames}\n'+query+f'frames {args.frames}\n'+query+'quit\n'
            rc,log,timed=_run_in_pty([str(args.blastem.resolve()),'-d',str(image.resolve())],command,max(30,args.frames//30+15))
            (out/'native.log').write_text(log);v=_blastem_values(log)
            samples=[int(x,16) for x in re.findall(r'\[\$ff0020\]\.l:\s*([0-9a-f]+)',log,re.I)]
            if timed or rc or len(samples)!=2 or v.get('FF0018.l')!=0 or v.get('FF0038.l')!=0:
                raise RuntimeError(f'{workload}/{mode}: failed observation; inspect native.log')
            if v.get('FF0010.w')!=0xDFFE or not 0x150<=v.get('FF0002.w',0)<0x180:
                raise RuntimeError('CPU escaped original benchmark loop')
            profile=json.loads((out/'trace-profile.json').read_text());stats=json.loads((out/'native-codegen-report.json').read_text())
            identities.append([(b['bank'],b['pc'],b['bytes'],b.get('observed_variants',[])) for b in profile['blocks']])
            delta=(samples[1]-samples[0])&0xFFFFFFFF
            modes[mode]={'interval_cycles':delta,'source_cycles_per_genesis_frame':delta/args.frames,
                         'normalized_gb_fps_at_60hz':delta/args.frames/70224*60,
                         'direct_hram_sites':stats['direct_hram_sites'],'rom_bytes':image.stat().st_size}
        assert identities[0]==identities[1],'coverage changed between modes'
        modes['throughput_ratio']=modes['direct']['interval_cycles']/modes['generic']['interval_cycles'];results[workload]=modes
        print(workload,modes['throughput_ratio'],flush=True)
    report={'scope':__doc__,'genesis_frames_per_interval':args.frames,'results':results}
    (args.out/'benchmark.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
