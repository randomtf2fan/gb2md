#!/usr/bin/env python3
"""Compare scheduler throughput against a supplied runtime using original ROMs.

Requires an external assembler and BlastEm. Results measure simulated Game Boy
cycles per fixed Genesis-frame interval, not host speed or commercial-game FPS.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import build_recompiled as compiler
from run_compat_tests import _blastem_values, _run_in_pty


def benchmark_rom(workload):
    code = bytes.fromhex('f331fedfafe040e007e00feaffff')
    if workload != 'masked':
        code += bytes.fromhex('3e91e040')
    if workload == 'vblank':
        code += bytes.fromhex('3e01eafffffb00')
    if workload == 'mixed':
        code += bytes.fromhex('3e78e0413e05e0073e07eafffffb00')
    code += bytes.fromhex('040d78a918fa')
    rom = bytearray(0x8000)
    for vector in (0x40, 0x48, 0x50):
        rom[vector] = 0xD9  # RETI
    rom[0x100:0x103] = bytes.fromhex('c35001')
    rom[0x150:0x150 + len(code)] = code
    return bytes(rom)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-runtime', type=Path, required=True)
    parser.add_argument('--out', type=Path, default=Path('compat-builds/scheduler-benchmark'))
    parser.add_argument('--frames', type=int, default=180)
    parser.add_argument('--blastem', type=Path, default=Path(
        os.environ.get('GB2MD_BLASTEM') or shutil.which('blastem') or 'blastem'))
    args = parser.parse_args()
    if not 60 <= args.frames <= 1800:
        parser.error('frames must be 60..1800')
    if not args.reference_runtime.is_file():
        parser.error('reference runtime must be an existing assembly file')
    if 'test_roms' in args.out.resolve().parts:
        parser.error('immutable fixture tree cannot be output')
    if args.out.exists() and any(args.out.iterdir()):
        parser.error('choose a new empty output directory')
    args.out.mkdir(parents=True, exist_ok=True)
    report = {
        'scope': __doc__, 'genesis_frames_per_interval': args.frames,
        'runtime_sha256': {
            'reference': hashlib.sha256(args.reference_runtime.read_bytes()).hexdigest(),
            'current': hashlib.sha256((compiler.ROOT / 'runtime_68000.s').read_bytes()).hexdigest(),
        }, 'results': {},
    }
    # ROOT selects the runtime; GB2MD_VASM/PATH selects the external assembler.
    current_root = compiler.ROOT
    with tempfile.TemporaryDirectory(prefix='gb2md-reference-runtime-') as folder:
        reference_root = Path(folder)
        shutil.copyfile(args.reference_runtime, reference_root / 'runtime_68000.s')
        for workload in ('masked', 'vblank', 'mixed'):
            source = args.out / (workload + '.gb')
            source.write_bytes(benchmark_rom(workload))
            modes, coverage = {}, []
            for mode, root in (('reference', reference_root), ('current', current_root)):
                out = args.out / workload / mode
                with patch.object(compiler, 'ROOT', root):
                    image = compiler.build(source, out, 20000)
                query = 'p/x [$ff0002].w [$ff0010].w [$ff0020].l [$ff0018].l [$ff0038].l\n'
                rc, log, timed = _run_in_pty(
                    [str(args.blastem.resolve()), '-d', str(image.resolve())],
                    f'frames {args.frames}\n' + query + f'frames {args.frames}\n' + query + 'quit\n',
                    max(30, args.frames // 30 + 15))
                (out / 'native.log').write_text(log)
                values = _blastem_values(log)
                samples = re.findall(r'\[\$ff0020\]\.l:\s*([0-9a-f]+)', log, re.I)
                if (timed or rc or len(samples) != 2 or values.get('FF0018.l') != 0
                        or values.get('FF0038.l') != 0 or values.get('FF0010.w') not in (0xDFFC, 0xDFFE)
                        or not (0x40 <= values.get('FF0002.w', 0) <= 0x50
                                or 0x150 <= values.get('FF0002.w', 0) < 0x190)):
                    raise RuntimeError(f'{workload}/{mode}: invalid observation; inspect {out}/native.log')
                delta = (int(samples[1], 16) - int(samples[0], 16)) & 0xFFFFFFFF
                modes[mode] = {'source_cycles': delta,
                               'normalized_gb_fps_at_60hz': delta / args.frames / 70224 * 60}
                profile = json.loads((out / 'trace-profile.json').read_text())
                coverage.append([(b['bank'], b['pc'], b['bytes'], b.get('observed_variants', []))
                                 for b in profile['blocks']])
            if coverage[0] != coverage[1]:
                raise RuntimeError('coverage changed between runtime comparisons')
            if modes['reference']['source_cycles'] == 0:
                raise RuntimeError('reference runtime made no execution progress')
            modes['throughput_ratio'] = modes['current']['source_cycles'] / modes['reference']['source_cycles']
            report['results'][workload] = modes
            (args.out / 'benchmark.json').write_text(json.dumps(report, indent=2) + '\n')
            print(workload, modes['throughput_ratio'], flush=True)


if __name__ == '__main__':
    main()
