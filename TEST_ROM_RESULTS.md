# Test ROM validation snapshot — 2026-11-19

This snapshot inventories **4,510 ROMs** across 18 suites. All **5,100 files**
in the fixture tree were hashed before/after each sweep and remained unchanged.
No test ROMs were downloaded, modified or redistributed.

These are **latest measurements with different documented budgets**, not one
uniform run or a claim of full compatibility. The initial screen used300,000
instructions/240 source frames. GBMicrotest was rerun at1,000,000/24; Mooneye at
1,000,000/1,000; eleven individual Blargg CPU ROMs at10,000,000/2,400; three
combined Blargg ROMs at40,000,000/6,000. Some remaining baseline results predate
the palette correction; raw reports record each measurement's source hashes.
Limits are upper bounds. A timeout is not a demonstrated hardware failure.

| Result | Python reference | Native Genesis |
|---|---:|---:|
| PASS | 326 | 49 |
| FAIL | 331 | 4 |
| TIMEOUT | 64 | 0 |
| UNSUPPORTED | 1993 | 0 |
| NOT_RUN | 1796 | 4457 |

721 ROMs reached execution under an automated Python protocol. Native results
cover 53 distinct ROMs: the existing43-case regression set plus10 GBMicrotests.
A compiled image, successful boot or picture never counts as native PASS.
Unknown visual/audio protocols remain NOT_RUN; CGB-only/non-target model and
unsupported cartridge cases remain UNSUPPORTED.

| Suite | ROMs | Python PASS | FAIL | TIMEOUT | UNSUPPORTED | NOT_RUN |
|---|---:|---:|---:|---:|---:|---:|
| age-test-roms | 47 | 0 | 0 | 0 | 15 | 32 |
| blargg | 58 | 20 | 1 | 0 | 14 | 23 |
| bully | 1 | 0 | 0 | 0 | 0 | 1 |
| cgb-acid-hell | 1 | 0 | 0 | 0 | 1 | 0 |
| cgb-acid2 | 1 | 0 | 0 | 0 | 1 | 0 |
| dmg-acid2 | 1 | 0 | 0 | 0 | 0 | 1 |
| gambatte | 3524 | 0 | 0 | 0 | 1918 | 1606 |
| gbmicrotest | 513 | 208 | 273 | 32 | 0 | 0 |
| little-things-gb | 2 | 0 | 0 | 0 | 0 | 2 |
| mbc3-tester | 1 | 0 | 0 | 0 | 0 | 1 |
| mealybug-tearoom-tests | 35 | 0 | 0 | 0 | 0 | 35 |
| mooneye-test-suite | 115 | 52 | 23 | 13 | 24 | 3 |
| mooneye-test-suite-wilbertpol | 121 | 46 | 34 | 19 | 20 | 2 |
| rtc3test | 1 | 0 | 0 | 0 | 0 | 1 |
| same-suite | 78 | 0 | 0 | 0 | 0 | 78 |
| scribbltests | 8 | 0 | 0 | 0 | 0 | 8 |
| strikethrough | 1 | 0 | 0 | 0 | 0 | 1 |
| turtle-tests | 2 | 0 | 0 | 0 | 0 | 2 |

## Established findings

- **Native HALT fetch duplication is missing:** GBMicrotest `halt_op_dupe.gb`
  passes in Python (actual2, expected2), but native execution reports actual1,
  expected2 and failure flag255. No missing-block trap is present. Python has
  `halt_bug` fetch suppression; native HALT lowering currently only sets the
  halted state. Implementing correct native handling is the next CPU priority;
  it must preserve native recompilation, including multi-byte operand/PC effects.
- **Reference palette initialization corrected:** `poweron_bgp_000.gb` initially
  failed in Python (0 instead of252), while native execution passed. Python
  now initializes BGP to$FC, matching existing native startup and the
  [documented DMG post-boot state](https://github.com/gbdev/pandocs/blob/master/src/Power_Up_Sequence.md#hardware-registers).
  Fresh Python/native reruns both pass. No native runtime change was required.
- **Shared PPU discrepancies:** `lcdon_to_stat0_a.gb` reports132 instead of135,
  `sprite_0_a.gb`128 instead of131, and `stat_write_glitch_l0_a.gb`224 instead
  of226 in both reference and native runs. Identical results suggest shared
  hardware-model assumptions; the exact causes are not yet established.
- **Combined CPU ROM still fails:** all11 individual Blargg CPU ROMs pass in
  Python, but `cpu_instrs/cpu_instrs.gb` reaches opcode$10 at$C302 after printing
  `01:ok  02:ok  03`. The same failure reproduces with the old palette state.
  Wrong control flow/RAM contents, mapper handling and an unsupported opcode
  need investigation before declaring a root cause. Native result NOT_RUN.
- Both combined Blargg memory-timing ROMs pass in Python at the longer budget.
- Mooneye ROM-bank tests fail broadly. Selector aliasing and MBC1 windows need
  investigation; these failures alone do not establish the exact mapper defect.
- Boot-state emulation remains incomplete: Python/native initial LCDC differ.
  That was left unchanged because display phase/LY/interrupt timing must be
  validated together. Sound, CGB and screenshot/audio comparison remain limited.

## Observer changes and verification

The runner now implements the [bundled GBMicrotest contract](https://github.com/c-sp/gameboy-test-roms/blob/master/src/howto/gbmicrotest.md):
FF82=1 means PASS; FF82=255 means FAIL. FF80 and FF81 are diagnostic only and
may be equal even on failure. Both backends require24 simulated source-clock
frames before accepting the flag, accommodating the documented380ms test.
No CPU clocks are multiplied or result bytes injected. Native observations
also check missing-block diagnostics and the source cycle counter. An initial
900-Genesis-frame probe correctly timed out before this floor;4000 frames
sufficed in the tested original fixtures. Host400% acceleration only reduces
wall time, not the emulated-cycle requirement. Other workloads may need more.

The runner also excludes manual/tools ROMs in both Mooneye variants and
explicit non-DMG model names. DMA activity no longer relabels every failure as
a DMA defect without evidence. The instantaneous serial test peer remains a
limitation for physical serial timing; Blargg serial passes use that peer.

Fast unit suites in both source copies: **215PASS /41native-only skips**
(256 methods). The focused observer suite passed7/7 with native testing enabled,
including original native programs producing deliberate PASS and FAIL flags.
The existing43 native compatibility regressions passed. These counts do not
mean all256 unit methods were rerun natively in this phase.

Preserved-coverage Tetris output remains byte-identical to ca61322a; all13
tracked protected checkpoints remain unchanged. No fresh game playthrough,
GUI interaction test, speed improvement or physical-hardware test was done.
The GUI uses the unchanged shared build interface.

## Reproduce

```sh
python3 -m unittest discover -s tests
python3 run_compat_tests.py --suite gbmicrotest --max-steps 1000000 --max-frames 24 --json compat-results/gbmicro.json
python3 run_compat_tests.py --suite mooneye --max-steps 1000000 --max-frames 1000 --json compat-results/mooneye.json
python3 run_compat_tests.py test_roms/blargg/cpu_instrs/individual --max-steps 10000000 --max-frames 2400 --json compat-results/blargg-cpu.json
```

Native testing additionally needs an external assembler and BlastEm. Set
GB2MD_BLASTEM to an isolated-display wrapper for unattended testing; no desktop
windows were used here. Use `--compile-native --run-native-blastem` and explicit
native frame/time limits. The normal CLI builds only Python-passing fixtures;
three known Python-failing PPU cases were directly built for diagnostic native
comparison while preserving their original Python FAIL status.

Full per-ROM JSON, logs, native binaries and fixture hashes remain private under
`compat-results/nov19-collection-matrix.json` and `compat-builds/`. The public
repository includes only this summary, original source and synthetic tests.
