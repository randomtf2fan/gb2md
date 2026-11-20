"""Validate optional local coverage inputs; never load emulator state or code.

ROM instructions must match the exact cartridge. RAM instruction bytes are
user-supplied observations, not authenticated by the cartridge digest. Their
normal runtime byte guards remain mandatory after import.
"""
import hashlib
import json
from pathlib import Path

from gb2md import instruction_length


def load_coverage_profiles(rom, paths):
    paths = list(paths)
    if len(paths) > 16:
        raise ValueError('at most 16 coverage profiles may be imported')
    digest = hashlib.sha256(rom).hexdigest()
    result, seen = [], set()
    for path in paths:
        path = Path(path).resolve()
        if path in seen:
            continue
        seen.add(path)
        if path.stat().st_size > 128 * 1024 * 1024:
            raise ValueError('coverage profile exceeds 128 MiB safety limit')
        profile = json.loads(path.read_text())
        if not isinstance(profile, dict) or profile.get('source_sha256') != digest:
            raise ValueError(f'{path}: coverage source SHA-256 does not match ROM')
        blocks = profile.get('blocks')
        if not isinstance(blocks, list) or len(blocks) > 1_000_000:
            raise ValueError(f'{path}: invalid coverage block list')
        entries, keys = [], set()
        for block in blocks:
            if not isinstance(block, dict):
                raise ValueError(f'{path}: invalid coverage entry')
            bank, pc, hits = (block.get(k) for k in ('bank', 'pc', 'hits'))
            if (type(bank) is not int or type(pc) is not int or type(hits) is not int
                    or not 0 <= bank <= 511 or not 0 <= pc <= 65535
                    or not 0 <= hits < 2**63 or (bank, pc) in keys):
                raise ValueError(f'{path}: invalid or duplicate coverage identity')
            keys.add((bank, pc))
            variants = block.get('observed_variants', [])
            if not isinstance(variants, list) or len(variants) > 256:
                raise ValueError(f'{path}: invalid coverage variants')
            values = []
            for value in [block.get('bytes'), *variants]:
                try:
                    if not isinstance(value, str) or not 2 <= len(value) <= 6:
                        raise ValueError()
                    raw = bytes.fromhex(value)
                    if not raw or instruction_length(raw[0]) != len(raw):
                        raise ValueError()
                except ValueError:
                    raise ValueError(f'{path}: invalid instruction bytes at {bank:02X}:{pc:04X}') from None
                end = pc + len(raw)
                if pc < 0x8000:
                    limit = 0x4000 if pc < 0x4000 else 0x8000
                    offset = pc if pc < 0x4000 else bank * 0x4000 + pc - 0x4000
                    if ((pc < 0x4000 and bank != 0)
                            or (0x4000 <= pc < 0x8000 and bank == 0 and not 0x19 <= rom[0x147] <= 0x1E)
                            or end > limit
                            or rom[offset:offset + len(raw)] != raw):
                        raise ValueError(f'{path}: ROM bytes/bank mismatch at {bank:02X}:{pc:04X}')
                elif bank != 0 or not (0xC000 <= pc < end <= 0xFEA0
                                       or 0xFF80 <= pc < end <= 0xFFFF):
                    raise ValueError(f'{path}: unsupported RAM-code location')
                if raw not in values:
                    values.append(raw)
            halt_raw=None;halt_hits=block.get('halt_fetch_hits',0)
            if type(halt_hits) is not int or not 0<=halt_hits<2**63:
                raise ValueError(f'{path}: invalid HALT fetch hit count')
            if 'halt_fetch_bytes' in block:
                encoded=block['halt_fetch_bytes'];normal=values[0]
                expected=normal[:1]+normal[:len(normal)-1]
                if pc>=0x8000 or not isinstance(encoded,str) or encoded!=expected.hex():
                    raise ValueError(f'{path}: invalid HALT fetch context at {bank:02X}:{pc:04X}')
                halt_raw=expected
            elif halt_hits:
                raise ValueError(f'{path}: HALT hits without fetch context')
            entries.append((bank, pc, hits, values, halt_raw, halt_hits))
        result.append((path, entries))
    return result


def merge_coverage_profiles(profiles, first, hits, observed, observed_banks, dynamic_values,halt_observed=None):
    reports = []
    for path, entries in profiles:
        before = len(first)
        for bank, pc, count, values, halt_raw, halt_hits in entries:
            key = bank, pc
            if halt_raw is not None and halt_observed is not None:
                halt_observed[key][halt_raw]+=halt_hits
            first.setdefault(key, values[0])
            hits[key] += count
            for raw in values:
                observed[key][raw] += max(1, count if raw == values[0] else 1)
                if pc >= 0x8000:
                    for offset, byte in enumerate(raw):
                        dynamic_values[pc + offset].add(byte)
            if 0x4000 <= pc < 0x8000 and count:
                observed_banks[key].add(bank)
        reports.append({'path': str(path), 'entries': len(entries), 'observed_entries': sum(count > 0 for _, _, count, _, _, _ in entries),
                        'new_entries': len(first) - before})
    return reports
