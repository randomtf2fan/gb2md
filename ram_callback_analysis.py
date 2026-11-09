"""Bounded discovery of indexed ROM records copied into RAM callback slots.

This analysis adds native coverage candidates only. It never substitutes for
the original loader, mapper writes, RAM copies or indirect call at runtime.
All table addresses, field offsets and selector operands come from validated
instructions, not cartridge titles or known application data structures.
"""
from collections import defaultdict, deque

from gb2md import instruction_length
from lr35902_lowering import family


def _word(data, offset):
    return data[offset] | data[offset + 1] << 8


def _ram(address):
    return 0xC000 <= address < 0xE000 or 0xFF80 <= address < 0xFFFF


def _ram_span(address, size):
    return (_ram(address) and _ram(address + size - 1)
            and (address < 0xE000) == (address + size - 1 < 0xE000))


class RamCallbackAnalyzer:
    def __init__(self, rom, bank_candidates, max_indices=256, max_pairs=64,
                 max_walk_steps=128):
        if min(max_indices, max_pairs, max_walk_steps) <= 0:
            raise ValueError('RAM callback analysis budgets must be positive')
        self.rom = rom
        self.bank_candidates = bank_candidates
        self.max_indices = min(max_indices, 256)
        self.max_pairs = max_pairs
        self.max_walk_steps = max_walk_steps
        self.selectors = {}
        self.contexts = {}

    def _fixed(self, pc, size):
        if not 0 <= pc or pc + size > min(len(self.rom), 0x4000):
            return b''
        return self.rom[pc:pc + size]

    def _alias(self, pc):
        seen = set()
        for _ in range(4):
            if pc in seen:
                return None
            seen.add(pc)
            raw = self._fixed(pc, 3)
            if not raw:
                return None
            if raw[0] != 0xC3:
                return pc
            pc = _word(raw, 1)
        return None

    def _banks(self, value, register):
        if len(self.rom) <= 0x147:
            return []
        if self.rom[0x147] in (0, 8, 9):
            return [1] if 0x2000 <= register < 0x4000 and len(self.rom) >= 0x8000 else []
        return self.bank_candidates(self.rom, value, register)

    def _read(self, bank, address):
        if not 0 <= address < 0x8000:
            return None
        offset = address if address < 0x4000 else bank * 0x4000 + address - 0x4000
        return self.rom[offset] if 0 <= offset < len(self.rom) else None

    def _read_word(self, bank, address):
        low, high = self._read(bank, address), self._read(bank, address + 1)
        return None if low is None or high is None else low | high << 8

    def selector(self, entry):
        if entry in self.selectors:
            return self.selectors[entry]
        self.selectors[entry] = None
        pc = self._alias(entry)
        if pc is None:
            return None
        raw = self._fixed(pc, 30)
        # Save HL/BC; BC=A; temporarily map a constant bank; read table[BC];
        # preserve that byte in HRAM; restore the prior bank; select the byte.
        if (not raw or raw[:6] != bytes.fromhex('e5c54f06003e')
                or raw[7] != 0xCD or raw[10] != 0x21
                or raw[13:16] != bytes.fromhex('097ee0')
                or raw[17] != 0xCD or raw[20] != 0xF0
                or raw[22] != 0xE0 or raw[24] != 0xEA
                or raw[27:] != bytes.fromhex('c1e1c9')):
            return None
        scratch, shadow, register = raw[16], raw[23], _word(raw, 25)
        if (scratch != raw[21] or not 0x80 <= scratch < 0xFF
                or not 0x80 <= shadow < 0xFF or scratch == shadow):
            return None
        save_pc, restore_pc = self._alias(_word(raw, 8)), self._alias(_word(raw, 18))
        if save_pc is None or restore_pc is None:
            return None
        save, restore = self._fixed(save_pc, 17), self._fixed(restore_pc, 9)
        if (not save or not restore or save[0] != 0xEA or save[3] != 0xF0
                or save[5] != 0xEA or save[8] != 0xFA
                or save[11] != 0xE0 or save[13] != 0xEA or save[16] != 0xC9
                or restore[0] != 0xFA or restore[3] != 0xE0
                or restore[5] != 0xEA or restore[8] != 0xC9):
            return None
        new_slot, old_slot = _word(save, 1), _word(save, 6)
        writes = {new_slot, old_slot, 0xFF00 | scratch, 0xFF00 | shadow}
        if (not _ram(new_slot) or not _ram(old_slot) or len(writes) != 4
                or _word(save, 9) != new_slot or _word(restore, 1) != old_slot
                or not save[4] == save[12] == restore[4] == shadow
                or not _word(save, 14) == _word(restore, 6) == register):
            return None
        table_banks = self._banks(raw[6], register)
        if not table_banks:
            return None
        info = dict(entry=pc, bank_table=_word(raw, 11), table_banks=table_banks,
                    register=register, writes=writes)
        self.selectors[entry] = info
        return info

    def _copy(self, pc, index):
        raw = self._fixed(pc, 30)
        if (not raw or raw[0] != 0x21 or raw[3] != 0xFA or _word(raw, 4) != index
                or raw[6:19] != bytes.fromhex('cb27300124856f3001242a666f')
                or raw[19] != 0x11 or raw[22] != 0x0E
                or raw[24:] != bytes.fromhex('2a12130d20fa')):
            return None
        table, destination, count = _word(raw, 1), _word(raw, 20), raw[23] or 256
        if table >= 0x8000 or not _ram_span(destination, count):
            return None
        if destination <= index < destination + count:
            return None
        return dict(pc=pc, pointer_table=table, destination=destination, size=count)

    def _consumer(self, pc):
        raw = self._fixed(pc, 7)
        if not raw or raw[0] != 0x21 or raw[3:6] != bytes.fromhex('2a666f'):
            return None
        address = _word(raw, 1)
        if not _ram_span(address, 2):
            return None
        if raw[6] == 0xE9:
            return dict(pc=pc, address=address, return_pc=None)
        raw = self._fixed(pc, 12)
        if (not raw or raw[6] != 0x11 or raw[9:] != bytes.fromhex('d5e9c9')
                or _word(raw, 7) != pc + 11):
            return None
        return dict(pc=pc, address=address, return_pc=pc + 11)

    def _stable(self, raw, index):
        """Prove no mapping or index-byte store on a context continuation."""
        op = raw[0]
        if op in (0x02, 0x12, 0x22, 0x32, 0x34, 0x35, 0x36,
                  0xC5, 0xD5, 0xE5, 0xF5, 0xE2):
            return False
        if 0x70 <= op <= 0x77 and op != 0x76:
            return False
        if op == 0xCB and raw[1] & 7 == 6 and raw[1] >> 6 != 1:
            return False
        if op in (0xEA, 0x08, 0xE0):
            address = 0xFF00 | raw[1] if op == 0xE0 else _word(raw, 1)
            size = 2 if op == 0x08 else 1
            return _ram_span(address, size) and not address <= index < address + size
        return True

    def _context(self, pc):
        if pc in self.contexts:
            return self.contexts[pc]
        result = dict(copies=[], consumers=[], exhausted=False)
        self.contexts[pc] = result
        raw = self._fixed(pc, 6)
        if not raw or raw[0] != 0xFA or raw[3] != 0xCD:
            return result
        index = _word(raw, 1)
        if not _ram(index):
            return result
        selector = self.selector(_word(raw, 4))
        if selector is None or index in selector['writes']:
            return result
        result.update(index=index, selector=selector)
        queue, seen = deque([(pc + 6, frozenset())]), set()
        while queue and len(seen) < self.max_walk_steps:
            state = queue.popleft()
            if state in seen:
                continue
            seen.add(state)
            cursor, writes = state
            head = self._fixed(cursor, 1)
            if not head:
                continue
            instruction = self._fixed(cursor, instruction_length(head[0]))
            if not instruction:
                continue
            copy = self._copy(cursor, index)
            consumer = self._consumer(cursor)
            if copy is not None:
                result['copies'].append(copy)
                continue
            if consumer is not None:
                field = {consumer['address'], consumer['address'] + 1}
                if not field & (writes | selector['writes']):
                    result['consumers'].append(consumer)
                continue
            fam = family(instruction[0])
            if fam in ('RET', 'RETI', 'CALL', 'CALL_CC', 'RST', 'JP_HL',
                       'HALT', 'STOP', 'INVALID', 'UNCLASSIFIED'):
                continue
            if not self._stable(instruction, index):
                continue
            if instruction[0] in (0xEA, 0x08, 0xE0):
                address = 0xFF00 | instruction[1] if instruction[0] == 0xE0 else _word(instruction, 1)
                size = 2 if instruction[0] == 0x08 else 1
                writes = writes | frozenset(range(address, address + size))
            fall = cursor + len(instruction)
            if fam in ('JP', 'JP_CC'):
                destinations = [_word(instruction, 1)]
                if fam == 'JP_CC':
                    destinations.append(fall)
            elif fam in ('JR', 'JR_CC'):
                delta = instruction[1] - 256 if instruction[1] & 128 else instruction[1]
                destinations = [(fall + delta) & 65535]
                if fam == 'JR_CC':
                    destinations.append(fall)
            else:
                destinations = [fall]
            queue.extend((address, writes) for address in destinations if 0 <= address < 0x4000)
        result['exhausted'] = bool(queue)
        return result

    def discover(self, reachable_keys):
        groups = defaultdict(lambda: dict(copies={}, consumers={}, selector=None))
        exhausted = []
        for bank, pc in sorted(reachable_keys):
            if bank != 0 or not 0 <= pc < 0x4000 or self.rom[pc:pc + 1] != b'\xfa':
                continue
            context = self._context(pc)
            if 'selector' not in context:
                continue
            if context['exhausted']:
                exhausted.append(pc)
            selector = context['selector']
            group = groups[(selector['entry'], context['index'])]
            group['selector'] = selector
            for item in context['copies']:
                group['copies'][item['pc']] = item
            for item in context['consumers']:
                group['consumers'][item['pc']] = item
        targets, returns, reports = set(), set(), []
        pair_limit = False
        for (entry, index), group in sorted(groups.items()):
            selector = group['selector']
            for copy in group['copies'].values():
                for consumer in group['consumers'].values():
                    offset = consumer['address'] - copy['destination']
                    if not 0 <= offset <= copy['size'] - 2:
                        continue
                    if len(reports) >= self.max_pairs:
                        pair_limit = True
                        continue
                    roots, valid = set(), 0
                    for value_index in range(self.max_indices):
                        entry_roots = set()
                        for table_bank in selector['table_banks']:
                            value = self._read(table_bank, selector['bank_table'] + value_index)
                            if value is None:
                                continue
                            for bank in self._banks(value, selector['register']):
                                record = self._read_word(bank, copy['pointer_table'] + 2 * value_index)
                                if record is None or not 0x100 <= record or record + copy['size'] > 0x8000:
                                    continue
                                target = self._read_word(bank, record + offset)
                                if target is None or not 0x100 <= target < 0x8000:
                                    continue
                                op = self._read(bank, target)
                                if op is None or family(op) in ('INVALID', 'STOP'):
                                    continue
                                size = instruction_length(op)
                                if target + size > (0x4000 if target < 0x4000 else 0x8000):
                                    continue
                                if any(self._read(bank, target + j) is None for j in range(size)):
                                    continue
                                entry_roots.add((0 if target < 0x4000 else bank, target))
                        if entry_roots:
                            valid += 1
                            roots.update(entry_roots)
                    targets.update(roots)
                    if roots and consumer['return_pc'] is not None:
                        returns.add((0, consumer['return_pc']))
                    reports.append(dict(selector=entry, index_address=index,
                        bank_table=selector['bank_table'], pointer_table=copy['pointer_table'],
                        copy_pc=copy['pc'], destination=copy['destination'], size=copy['size'],
                        consumer_pc=consumer['pc'], callback_offset=offset,
                        index_limit=self.max_indices, valid_indices=valid,
                        stop_reason='byte index range scanned' if self.max_indices == 256 else 'index budget reached',
                        unique_targets=len(roots)))
        return dict(targets=targets, returns=returns, records=reports,
                    pair_limit_reached=pair_limit, exhausted_contexts=exhausted)
