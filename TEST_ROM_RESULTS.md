# Test ROM validation snapshot — 2026-11-19


## 2026-11-22 background raster follow-up

New original tests validate BG scanline composition, palette cache values and
fallback behavior. These generated fixtures are separate from the immutable
4510-ROM collection. A Bad Apple animation capture is a visual regression
observation, not a test-suite protocol PASS. Final native-enabled suite: 277/277
unit methods pass after an unchanged retry of one host-JIT startup failure;
the original failure is retained. Fast private/public suites: 231 PASS / 46
native skips. All 43 selected fixture ROMs pass Python/native execution.
The 160M-step Bad Apple reference audit spans all 64 banks without missing
entries/OOB reads, but is not a documented test-completion protocol or full
native video/audio PASS. No downloaded fixture or old checkpoint was changed.
See [the renderer status](COMPATIBILITY.md#background-scanline-composition--bad-apple--2026-11-22).



## 2026-11-22 LCD/VBlank follow-up

SameSuite `interrupt/ei_delay_halt.gb` now passes in Python and native execution
with the existing explicit diagnostic serial peer. Native observation checks
Fibonacci registers immediately after the original completion marker, with no
missing-block trap and emulator exit 0. This is one additional explicit fixture
observation; the full collection tables below have not been rerun or recomputed.
The general runner still does not automatically classify the SameSuite suite.
Five original LCD/VBlank native programs pass; they are separate from the
immutable downloaded collection. Native-enabled unit validation passes 273/273
methods, zero failures/skips; fast private/public runs pass 229 with 44 native-only
skips. All eleven individual Blargg CPU ROMs pass fresh Python serial-protocol
runs; their native results remain NOT_RUN. Fresh 43-ROM reference checks pass,
with div_write using a bounded 1M-instruction budget after the prior 300k timeout
(the shorter result is retained). All 43 native fixtures also pass, with emulator/helper exits 0. Tetris native
SDL regression observed gameplay, score 57, GAME OVER and menu return without
missing blocks across 14942 Genesis frames. No fresh hardware or speed claim.
See [current limitations](COMPATIBILITY.md#lcd-off-vblank-requests--2026-11-22).



## 2026-11-20 HALT follow-up

The native `halt_op_dupe.gb` failure below is now fixed: fresh Python and
native execution both report actual 2, expected 2, success flag 1. The three
original reduced probes also pass natively. The 2026-11-19 tables are historical
latest-measurement results. Fresh 43-ROM regressions pass in Python and native
execution. Updating those measurements plus the HALT fixture gives native
**50 PASS / 3 FAIL / 4457 NOT_RUN** across the same 4510-ROM inventory; the
three remaining observed native failures are the shared PPU discrepancies.
This is not a fresh sweep of every ROM, and the Python totals below have not
been recomputed for the separate SameSuite diagnostic.
Final unit validation: **267/267 PASS** with native tests enabled, zero
failures/skips. Fast suites in private/public copies: 224 PASS / 43 native-only
skips. Both native unit batch processes exit 0. All 43 native protocol emulator
children exit 0; the outer protocol shell reports 143 after writing complete
results, so that shell is not claimed to have exited successfully. A fresh
Python Blargg interrupt ROM also passes; its native result remains NOT_RUN.
All 5100 fixture files and 13 protected checkpoint hashes remain unchanged.

See [the current HALT status](COMPATIBILITY.md#native-halt-fetch-correction--2026-11-20).


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

## Established findings (2026-11-19; HALT superseded above)

- **Native HALT fetch duplication was missing (fixed 2026-11-20):** GBMicrotest `halt_op_dupe.gb`
  passes in Python (actual2, expected2), but native execution reports actual1,
  expected2 and failure flag255. No missing-block trap is present. Python has
  `halt_bug` fetch suppression; native HALT lowering then only set the
  halted state at that time. Correct native handling was the next CPU priority;
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
- Boot-state emulation remained incomplete: Python/native initial LCDC differed.
  This mismatch was later corrected on 2026-11-22; phase/LY/interrupt startup
  alignment and other post-boot register values still need validation. Sound, CGB and screenshot/audio comparison remain limited.

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


## Historical reduced HALT-fetch probes — small follow-up

`halt_fetch_probe.py` generates three entirely original ROMs; these are separate
from the4510-ROM collection above. A pending interrupt with IME disabled is
held constant, with a NOP control and two HALT cases. All programs write a
completion marker and results to WRAM. No guest-memory debugger writes or
commercial/test-suite program bytes are used.

| Case | Reference result | Native result | Native status |
|---|---|---|---|
| NOP control | B result1 |1 |PASS |
| HALT then INC B | B result2 |1 |FAIL |
| HALT then LD A,$04 | B result1,A=$3E | B result0,A=$3E |FAIL |

All three native runs completed with emulator exit0, completion marker$A5 and
zero missing-block diagnostics. The immediate case demonstrates a second
problem: the suppressed opcode-PC increment fetches `3E 3E` from physical ROM
bytes `3E 04`, then executes the exposed `$04` as INC B. The compiler records
fetched bytes but normally calculates fallthrough as PC+instruction length,
so it skips that INC. A correct general fix needs a fetch-context representation,
the adjusted fallthrough/relative-branch/return PCs, and distinct ordinary
versus bugged execution at the same ROM entry. Merely duplicating one native
instruction would not implement this behavior correctly.

```sh
python3 halt_fetch_probe.py --out compat-results/halt-fetch-reference
# GB2MD_BLASTEM should point to an isolated-display wrapper for unattended use.
python3 halt_fetch_probe.py --out compat-results/halt-fetch-native --native --blastem "$GB2MD_BLASTEM"
```

The output directory must be empty or new. JSON records expected/reference/
native results and reference fetch history. The native command currently exits1
because two probes fail; those are real failures, not exempted passes. This
follow-up changes no compiler, CPU or native runtime behavior. Three new
reference regressions pass; the complete fast suite is218PASS/41native-only
skips (259methods) in both copies. This historical failure was fixed and
revalidated on 2026-11-20; see the follow-up above.
