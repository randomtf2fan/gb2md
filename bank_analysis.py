"""Bounded ROM-bank effect proofs used only for static coverage discovery.

These helpers do not alter CPU semantics or replace the live native bank check.
They deliberately reject calls, computed jumps and unproven indirect stores in
leaf proofs. Unknown effects terminate context propagation rather than guessing.
"""
from collections import deque

from gb2md import instruction_length
from lr35902_lowering import family


def _instruction(rom, bank, pc):
    if not 0 <= pc < 0x8000:
        return None
    offset = pc if pc < 0x4000 else bank * 0x4000 + pc - 0x4000
    if offset >= len(rom):
        return None
    size = instruction_length(rom[offset])
    end = 0x4000 if pc < 0x4000 else 0x8000
    if pc + size > end or offset + size > len(rom):
        return None
    return rom[offset:offset + size]


def _effect(raw, hl):
    """Return (proven not to write ROM, resulting constant HL or None)."""
    op = raw[0]
    if op in (0x02, 0x12, 0xC5, 0xD5, 0xE5, 0xF5):
        return False, None  # Unknown BC/DE or stack write address.
    if op in (0x08, 0xEA):
        address = raw[1] | raw[2] << 8
        if address < 0x8000 or (op == 0x08 and address == 0xFFFF):
            return False, None
    hl_write = op in (0x22, 0x32, 0x34, 0x35, 0x36)
    hl_write |= 0x40 <= op < 0x80 and op != 0x76 and (op >> 3) & 7 == 6
    hl_write |= op == 0xCB and raw[1] & 7 == 6 and raw[1] >> 6 != 1
    if hl_write and (hl is None or hl < 0x8000):
        return False, None
    if op == 0x21:
        hl = raw[1] | raw[2] << 8
    elif op in (0x22, 0x23, 0x2A, 0x2B, 0x32, 0x3A):
        if hl is not None:
            hl = (hl + (1 if op in (0x22, 0x23, 0x2A) else -1)) & 0xFFFF
    elif op in (0x09, 0x19, 0x29, 0x39, 0xE1, 0xF8, 0x24, 0x25, 0x2C, 0x2D):
        hl = None
    elif op in (0x26, 0x2E):
        if hl is not None:
            hl = (raw[1] << 8 | hl & 255) if op == 0x26 else (hl & 0xFF00 | raw[1])
    elif 0x40 <= op < 0x80 and (op >> 3) & 7 in (4, 5):
        if (op >> 3) & 7 != op & 7:
            hl = None
    elif op == 0xCB and raw[1] & 7 in (4, 5) and raw[1] >> 6 != 1:
        hl = None
    return True, hl


def _successors(raw, pc):
    op = raw[0]
    fall = pc + len(raw)
    if op in (0xC3, 0xC2, 0xCA, 0xD2, 0xDA):
        target = raw[1] | raw[2] << 8
        return [target] if op == 0xC3 else [fall, target]
    if op in (0x18, 0x20, 0x28, 0x30, 0x38):
        target = (fall + (raw[1] - 256 if raw[1] & 128 else raw[1])) & 0xFFFF
        return [target] if op == 0x18 else [fall, target]
    return [fall]


def leaf_preserves_rom_bank(rom, bank, pc, max_steps=256):
    """Prove all explored paths in a direct leaf routine avoid mapper writes.

    Constant HL permits ordinary WRAM/VRAM stores; an unknown HL store fails
    the proof. Both conditional outcomes are checked. Budgets and unknown
    control flow fail closed. Entry registers are otherwise unknown.
    """
    queue = deque([(pc, None)])
    seen = set()
    returned = False
    while queue:
        state = queue.popleft()
        if state in seen:
            continue
        if len(seen) >= max_steps:
            return False
        seen.add(state)
        pc, hl = state
        raw = _instruction(rom, bank, pc)
        if raw is None:
            return False
        fam = family(raw[0])
        if fam in ('CALL', 'CALL_CC', 'RST', 'JP_HL', 'HALT', 'STOP', 'INVALID', 'UNCLASSIFIED'):
            return False
        safe, hl = _effect(raw, hl)
        if not safe:
            return False
        if fam in ('RET', 'RETI', 'RET_CC'):
            returned = True
            if fam != 'RET_CC':
                continue
        queue.extend((target, hl) for target in _successors(raw, pc))
    return returned


def fixed_bank_context_targets(rom, bank, pc, max_steps=128):
    """Follow a proven active bank in fixed ROM across bank-preserving leaves.

    Upper-window calls/jumps produce coverage candidates, while only fixed-ROM
    continuations are explored here. This does not infer mapping after an
    arbitrary call. The existing static closure handles discovered upper code.
    """
    queue = deque([(pc, None)])
    seen, targets = set(), set()
    while queue and len(seen) < max_steps:
        state = queue.popleft()
        if state in seen:
            continue
        seen.add(state)
        pc, hl = state
        if not 0 <= pc < 0x4000:
            continue
        raw = _instruction(rom, bank, pc)
        if raw is None:
            continue
        fam = family(raw[0])
        if fam in ('RET', 'RETI', 'RST', 'JP_HL', 'HALT', 'STOP', 'INVALID', 'UNCLASSIFIED'):
            continue
        if fam in ('CALL', 'CALL_CC'):
            destination = raw[1] | raw[2] << 8
            if 0x4000 <= destination < 0x8000 and _instruction(rom, bank, destination) is not None:
                targets.add((bank, destination))
            if fam == 'CALL_CC' or leaf_preserves_rom_bank(rom, bank, destination):
                queue.append((pc + len(raw), None))
            continue
        safe, hl = _effect(raw, hl)
        if not safe:
            continue
        for destination in _successors(raw, pc):
            if 0x4000 <= destination < 0x8000:
                if _instruction(rom, bank, destination) is not None:
                    targets.add((bank, destination))
            elif destination < 0x4000:
                queue.append((destination, hl))
    return sorted(targets)
