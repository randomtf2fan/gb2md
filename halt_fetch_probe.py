#!/usr/bin/env python3
"""Original HALT-fetch differential probes; native failures are real failures.

This diagnostic generates its own tiny ROMs. It does not include test-suite or
commercial ROM data. Native observation needs the usual external assembler and
an explicitly selected BlastEm executable/wrapper.
"""
from __future__ import annotations
import argparse,json,os
from pathlib import Path
from gb_cpu import CPU,Memory

CASES={'control':(1,0x42),'single_byte':(2,0x42),'immediate':(1,0x3E)}


def make_rom(case):
    if case not in CASES:raise ValueError(f'unknown probe: {case}')
    # Mask IME, disable LCD, and request an enabled interrupt before HALT.
    # The control substitutes NOP while keeping the same interrupt state.
    code=bytes.fromhex('f3afe04006003e01eaffffe00f')
    fetch_pc=0x100+len(code)+1
    code+=b'\x00' if case=='control' else b'\x76'
    if case=='immediate':
        # Suppressed opcode-PC increment reads 3E twice; the physical 04
        # operand then executes as INC B. Normal lowering skips that INC.
        code+=bytes.fromhex('3e04ea01c078ea00c0')
    else:code+=bytes.fromhex('0478ea00c03e42ea01c0')
    code+=bytes.fromhex('3ea5ea02c0f318fe')
    rom=bytearray(0x8000);rom[0x100:0x100+len(code)]=code
    return bytes(rom),fetch_pc


def reference(rom,steps=200):
    cpu=CPU(Memory(rom));history=[]
    for _ in range(steps):
        bug=cpu.halt_bug;cpu.step()
        if cpu.last_instruction is not None:
            history.append({'pc':cpu.last_pc,'bytes':cpu.last_instruction.hex(),
                            'next_pc':cpu.pc,'suppressed_opcode_increment':bug})
    return {'actual':list(cpu.m.wram[:3]),'history':history}


def native(source,out,blastem,frames,timeout):
    from build_recompiled import build
    from run_compat_tests import _run_in_pty,_blastem_values
    image=build(source,out,200)
    rc,log,timed=_run_in_pty([str(blastem.resolve()),'-d',str(image.resolve())],
        f'frames {frames}\np/x [$ff2300].b [$ff2301].b [$ff2302].b [$ff0018].l [$ff0038].l\nquit\n',timeout)
    (out/'probe-native.log').write_text(log)
    values=_blastem_values(log)
    actual=[values.get(k) for k in ('FF2300.b','FF2301.b','FF2302.b')]
    return {'artifact':str(image),'actual':actual,'exit_code':rc,'timed_out':timed,
            'missing_marker':values.get('FF0018.l'),'missing_count':values.get('FF0038.l')}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--native',action='store_true')
    parser.add_argument('--blastem',type=Path,default=Path(os.environ.get('GB2MD_BLASTEM','blastem')))
    parser.add_argument('--frames',type=int,default=120)
    parser.add_argument('--timeout',type=int,default=20)
    args=parser.parse_args()
    if args.frames<=0 or args.timeout<=0:parser.error('frame/time limits must be positive')
    if args.native and not args.blastem.is_file():parser.error('provide an external BlastEm executable or isolated wrapper')
    # Avoid silently replacing a previous reproduction or user output.
    if args.out.exists() and any(args.out.iterdir()):parser.error('output directory must be empty or new')
    args.out.mkdir(parents=True,exist_ok=True);results=[]
    for case,expected_pair in CASES.items():
        rom,fetch_pc=make_rom(case);source=args.out/(case+'.gb');source.write_bytes(rom)
        expected=[*expected_pair,0xA5];ref=reference(rom)
        result={'case':case,'fetch_pc':fetch_pc,'expected':expected,
                'python':{'status':'PASS' if ref['actual']==expected else 'FAIL',**ref},
                'native':{'status':'NOT_RUN'}}
        if args.native:
            observed=native(source,args.out/case,args.blastem,args.frames,args.timeout)
            status='TIMEOUT' if observed['timed_out'] else ('PASS' if observed['exit_code']==0 and observed['actual']==expected and observed['missing_marker']==0 and observed['missing_count']==0 else 'FAIL')
            result['native']={'status':status,**observed}
        results.append(result)
        (args.out/'report.json').write_text(json.dumps({'note':'Original synthetic ROMs; native FAIL is not an expected-pass exemption. No fixture/guest-memory patches.','results':results},indent=2)+'\n')
        print(case,'Python',result['python']['status'],'native',result['native']['status'],flush=True)
    return int(any(r['python']['status']=='FAIL' or r['native']['status'] in ('FAIL','TIMEOUT') for r in results))


if __name__=='__main__':raise SystemExit(main())
