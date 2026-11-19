"""Reference expectations for the original, game-independent HALT probes."""
import unittest
from halt_fetch_probe import make_rom,reference,CASES


class HaltFetchProbeTests(unittest.TestCase):
    def test_reference_control_and_duplicate_fetch_results(self):
        for case,expected in CASES.items():
            with self.subTest(case=case):
                rom,_=make_rom(case)
                self.assertEqual(reference(rom)['actual'],[*expected,0xA5])

    def test_single_byte_fetch_repeats_at_same_pc(self):
        rom,pc=make_rom('single_byte');history=reference(rom)['history']
        rows=[x for x in history if x['pc']==pc]
        self.assertEqual(len(rows),2)
        self.assertEqual([x['next_pc'] for x in rows],[pc,pc+1])
        self.assertEqual([x['suppressed_opcode_increment'] for x in rows],[True,False])

    def test_immediate_fetch_changes_operand_and_following_instruction(self):
        rom,pc=make_rom('immediate');history=reference(rom)['history']
        first=next(x for x in history if x['pc']==pc)
        self.assertEqual(rom[pc:pc+2].hex(),'3e04')
        self.assertEqual(first['bytes'],'3e3e')
        self.assertEqual(first['next_pc'],pc+1)
        following=next(x for x in history if x['pc']==pc+1)
        self.assertEqual(following['bytes'],'04')
        self.assertFalse(following['suppressed_opcode_increment'])
