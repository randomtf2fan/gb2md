# GB2MD compatibility status

Last measured: 2026-11-07. A PASS means the ROM's documented serial or
register signature was observed. Booting or drawing an image is not a PASS.
`Native NOT_RUN` means no Genesis-side success protocol was observed, even if
the ROM assembled successfully.

## Automatic-input Tetris milestone

`build-tetris-auto-input-v2/recompiled.md` was generated from the ordinary
no-input trace plus bounded `--auto-inputs`; it used no manual input scripts or
memory pokes. SHA-1 is `5edb0e43249cb38e1c30d6f1defe7cc481056bd6`.

| Level | Result |
|---|---|
| Compilation | 4,792/4,792 blocks native; no unlowered families |
| Guided coverage comparison | All 3,864 guided-build blocks included |
| Boot/rendering | Title, menus, level selection and playfield rendered |
| Gameplay | A-Type entered; movement, rotation, soft drop, scoring, three Tetrises, and approximately 25,000 points observed in an extended manual session |
| Missing-block diagnostic | Marker and counter remained zero after the final stress sequence |
| Full compatibility | **Not claimed**: current-runtime v4 completes the reproduced game-over route, but performance is slow and pause/B-Type/top clipping remain unverified |

The earlier 3,922-block candidate entered gameplay but trapped at bank 1 PC
`$67DC` during the control stress. That target was a valid entry in a ROM
pointer dispatch table. General bounded pointer-table closure fixed the cause;
no Tetris address or title check was added. Capture:
`build-tetris-auto-input-v2/gameplay-stress.png`.

### Game-over follow-up

The stronger v3 candidate is `build-tetris-auto-input-v3/recompiled.md`, SHA-1
`7d4ecc1c326c4a3a7ac80f892f789687801ad218`. A general recognizer for a bounded
SM83 `RST` inline pointer-table convention fixed the observed game-over freeze.
It contains 7,187/7,187 native blocks: 2,295 dynamic, 37 HL pointer-table
targets, and 60 RST-inline table targets before recursive static closure.

The deterministic oracle route reached the loss animation and game-over state,
returned to the normal state, and executed 2,434 unique blocks with none absent
from v3. An automated native BlastEm run filled the same board region, completed
the transition, restored state `$04`, and left both missing-block marker and
counter at zero. This validates the previously failing route; pause, B-Type,
top-border clipping, audio, and full hardware timing remain outside the claim.

Measured native pacing is 17.5-23.9 simulated GB fps depending on workload,
with a gameplay/top-out average of 18.4 fps. This is a native-throughput limit,
not a 60 Hz BlastEm display failure.

The current-runtime v4 rebuild is
`build-tetris-auto-input-v4/recompiled.md`, SHA-1
`2f41da094676bd7bf95d5d485eeff084dbbf1870`, checkpointed as
`checkpoints/tetris-halt-fast-forward-2f41da09.md`. It has exactly the same
7,187 block keys as v3. The native forced-top-out regression again returned to
state `$04`, cleared the board, and left both missing-block diagnostics zero.
Its HALT fast-forward counter stayed zero on this route.

The current source adds progressive bulk OAM DMA and expanded mapper state. On
the identical forced-top-out route it advances 111,441,356 simulated T-cycles,
13.76% above the original 97,961,204-cycle runtime, while still restoring state
`$04`, clearing both sampled board cells, and leaving both missing-block
diagnostics zero. The older atomic-DMA renderer checkpoint reached 120,219,100
cycles, so DMA correctness currently costs about 7.30% on this workload.
Commercial-ROM artifacts are not published.

Current-session regression reports:

- `compat-results/blargg-cpu-auto-input-session.json`: Python 11 PASS; native 11 NOT_RUN
- `compat-results/mooneye-timer-auto-input-session.json`: Python 13 PASS; native not rerun in this report
- `compat-results/mooneye-reg-f-auto-input-session-native.json`: Python PASS; native Genesis PASS
- `compat-results/mooneye-timer-halt-fast-forward.json`: Python 13 PASS;
  native 12 PASS and one budget TIMEOUT at 600 observation frames
- `compat-results/mooneye-div-write-halt-fast-forward.json`: the budget
  outlier `div_write` PASS in Python and native at 2,500 observation frames,
  completing the current-runtime native timer result at 13/13

## Super Mario Land investigation

### Jump, collision, and writable-memory dispatch (2026-11-07)

The native runtime now prioritizes WRAM, I/O, HRAM, and IE in its memory
dispatch tree. On identical SML routes this yields roughly 5% more simulated
progress without changing the gameplay endpoint. A sampled jump moved Mario's
OAM Y from 128 to 113 and visibly rendered him airborne. A separate no-jump
route reached the collision/death-bounce animation and continued without a
missing block. Normal active gameplay remains only about 5-7 GB fps, so this
is a verified path and modest performance milestone, not full compatibility.

All 65 focused tests pass. Native Mooneye timer remains 13/13 PASS.

### VRAM dirty-class renderer split (2026-11-07)

Tile-map writes no longer trigger conversion of all 640 Genesis patterns, and
Plane A is cleared to its transparent tile only once. On the identical SML
movement interval, simulated throughput rose from 6.60 to 7.40 GB fps
(+12.1%) with the same rendered endpoint and zero missing blocks. On the exact
Tetris forced-top-out route, simulated cycles rose from 97,961,204 to
120,219,100 (+22.72%) while the validated result remained unchanged.

Focused tests remain 65/65 PASS and native Mooneye timer remains 13/13 PASS.
This improves throughput but does not establish real-time execution.

### Earliest-event HALT scheduler and movement (2026-11-05)

Once World 1-1 enables the timer interrupt (`IE=$07`), the earlier runtime
fell back to four-cycle HALT polling. The general scheduler now calculates the
earlier of the next VBlank and the next TIMA overflow/reload, advances there
through the ordinary event-driven `gb_tick`, and lets normal interrupt entry
wake the CPU.

A private validation build reusing the 7,476/7,476 native block set reached
gameplay, advanced TIME from 400 to 393, moved Mario from OAM X 43 to 74 under
Right, and visibly scrolled a stable World 1-1 scene. Python reaches the same
movement endpoint on the corresponding route. Missing-block marker and counter
stayed zero. Commercial-ROM build artifacts are not published.

The 58 focused tests pass. Native Mooneye timer remains 13/13 PASS: 12 within
600 observation frames and `div_write` within its established 2,500-frame
window. This establishes level movement and timer progress, not full game
compatibility; extended play, jump/collision paths, audio, and exact pacing
remain unverified.

### Timer-active HALT follow-up (2026-11-05)

The state `$0F` route was reproduced with scripted native controller bindings.
TAC was enabled (`$07`) but its interrupt was masked in `IE=$03`; the CPU was
halted at source PC `$0297`. The old scheduler therefore rejected its VBlank
fast path and advanced peripherals four T-cycles at a time. `$C0D7` did make
progress, so the observed freeze was principally native throughput rather than
missing coverage.

The runtime now batches this masked-timer case through the normal timer event
logic and handles every DIV/scanline boundary crossed by a large batch. This
paragraph records the preceding milestone; the earliest-event scheduler above
supersedes its timer-IRQ-enabled fallback. A private candidate leaves state
`$0F` and renders World 1-1 without a missing-block trap. The later
initialization countdown is still slow and the timer remains at 400, so
gameplay is not a PASS. Commercial-ROM build artifacts are not published.

All 58 focused tests pass. Mooneye timer remains 13/13 native PASS (12 at 600
observation frames and `div_write` at its established 2,500-frame window).
This is a performance/correctness improvement, not a full resolution of the
previously documented native/Python route differences.

The older GUI build had 6,892 blocks and two unlowered `LDH A,(C)` (`F2`)
instructions. General direct native lowering now covers that instruction. The
same automatic exploration settings discover 7,476 valid blocks, all native,
including 584 not present in the older profile.

The dominant observed boot/level slowdown was a VBlank `HALT` polling loop.
The native dispatcher previously advanced a halted CPU four T-cycles at a
time. A conservative VBlank-only `gb_halt_wait` changes the measured probe
from 1.32 to 33.4 simulated GB fps (about 25x) when LCD and VBlank IRQ are
enabled and TIMA is disabled. A 1,200-host-frame before/after probe showed only
three renders before the fix, ruling out continuous full rendering as the
primary cause. Missing-block diagnostics remained zero. A subsequent clean v3
build visually verified recognizable World 1-1 rendering, but timer advance
and controls still fail, so this remains a performance/rendering milestone
rather than a gameplay PASS.

Clean candidate: `build-sml-auto-v3/recompiled.md`, SHA-1
`9ee66ad4c9731f827bc33be586aa38a5dfa6c532`, 7,476/7,476 native blocks. The
captured native frame now shows a recognizable World 1-1 rather than the old
mostly empty turquoise frame (`build-sml-auto-v3/native-route-capture.png`).
However, the timer remains 400 and movement does not advance gameplay.

The native core repeatedly services VBlank (about 644 observed writes to the
source `$FF85` frame flag), has no missing-block trap, but remains at dispatcher
state `$FFB3=$0F` and `IE=$03`. With the same source-input route, the Python
oracle reaches `$FFB3=$11` and executes PC `$054F`, changing `IE` to `$07`.
This establishes a native execution divergence in the `$0F` initialization
path. It is not yet localized to one instruction or flag operation.

## Automated fixture inventory

The immutable `test_roms/` tree contains 4,510 ROMs: 3,524 Gambatte, 513
GBMicrotest, 236 across the two Mooneye trees, 78 SameSuite, 58 Blargg, 47 AGE,
35 Mealybug Tearoom, and smaller acid/RTC/MBC/diagnostic suites. Generated
files live under `compat-results/`, never under `test_roms/`.

## Blargg CPU instructions

Report: `compat-results/blargg-cpu-individual-final.json`

| ROM | Python | Native Genesis | Detail |
|---|---:|---:|---|
| 01-special | PASS | NOT_RUN | Serial `Passed` |
| 02-interrupts | PASS | NOT_RUN | Serial `Passed`; initially failed before timer implementation |
| 03-op sp,hl | PASS | NOT_RUN | Serial `Passed` |
| 04-op r,imm | PASS | NOT_RUN | Serial `Passed` |
| 05-op rp | PASS | NOT_RUN | Serial `Passed` |
| 06-ld r,r | PASS | NOT_RUN | Serial `Passed` |
| 07-jr,jp,call,ret,rst | PASS | NOT_RUN | Serial `Passed` |
| 08-misc instrs | PASS | NOT_RUN | Serial `Passed` |
| 09-op r,r | PASS | NOT_RUN | Serial `Passed` |
| 10-bit ops | PASS | NOT_RUN | Serial `Passed` |
| 11-op a,(hl) | PASS | NOT_RUN | Serial `Passed` |

The standalone Blargg `halt_bug.gb`, sound, OAM-bug, and similar screenshot
tests are classified as manual visual protocols and are not promoted to PASS
from reaching a loop. The Python core has a focused HALT-bug regression.

## Mooneye timer acceptance

Every ROM below passes both the Python oracle and recompiled 68000 execution in
BlastEm. Native PASS was verified from the Fibonacci registers
`B/C/D/E/H/L = 3/5/8/13/21/34` while the source PC was in the terminal `JR -2`.

| ROM | Python | Native Genesis |
|---|---:|---:|
| div_write | PASS | PASS |
| rapid_toggle | PASS | PASS |
| tim00 | PASS | PASS |
| tim00_div_trigger | PASS | PASS |
| tim01 | PASS | PASS |
| tim01_div_trigger | PASS | PASS |
| tim10 | PASS | PASS |
| tim10_div_trigger | PASS | PASS |
| tim11 | PASS | PASS |
| tim11_div_trigger | PASS | PASS |
| tima_reload | PASS | PASS |
| tima_write_reloading | PASS | PASS |
| tma_write_reloading | PASS | PASS |

Native reports are split by execution budget:

- `compat-results/mooneye-native-timer-frequency-verified.json`
- `compat-results/mooneye-native-timer-event-verified.json`
- `compat-results/mooneye-native-timer-edge-verified.json`
- `compat-results/mooneye-rapid-toggle-native-glitch-verified.json`
- `compat-results/mooneye-div-write-native-verified.json`

## Other Mooneye CPU/control tests

`bits/reg_f.gb` passes in Python and natively on the current runtime; see
`compat-results/mooneye-reg-f-native-final.json`. The current expanded Python
run is `compat-results/mooneye-cpu-control-dma-final.json`: all 28 selected
CPU/control ROMs pass, including the fourteen instruction-timing cases that
previously failed while executing from OAM during DMA.

The fix was general: CPU operations now expose their actual four-T-cycle bus
reads, writes, and idle cycles; OAM DMA progresses one byte per machine cycle;
and the tracer records the bytes actually fetched after bus effects rather than
peeking before execution. This is a Python-oracle result for the complete
28-ROM group. Do not infer 28 native passes: native execution has only been
verified for the subsets explicitly listed below.

## Mooneye OAM DMA acceptance

The six targeted DMG/MGB-compatible OAM-DMA ROMs pass in the Python oracle and
as recompiled Genesis ROMs observed through BlastEm:

| ROM | Python | Native Genesis |
|---|---:|---:|
| oam_dma/basic | PASS | PASS |
| oam_dma/reg_read | PASS | PASS |
| oam_dma/sources-GS | PASS | PASS |
| oam_dma_restart | PASS | PASS |
| oam_dma_start | PASS | PASS |
| oam_dma_timing | PASS | PASS |

`basic` and `sources-GS` require a 1,800-frame native observation window; the
other four pass in the 600-frame batch. Current reports include
`compat-results/mooneye-oam-dma-bulk-basic-1800.json`,
`compat-results/mooneye-oam-dma-bulk-sources-1800.json`, and
`compat-results/mooneye-oam-dma-bulk-native-suite.json` (whose older 600-frame
`basic` TIMEOUT is superseded by the explicit 1,800-frame PASS).

These results validate progressive start/restart timing, OAM register reads,
and tested DMA source mappings. They do not establish complete DMG bus
arbitration, OAM corruption, or CGB DMA behavior.

## Original MBC3 RAM diagnostic

`make_homebrew_test_rom.py` generates an original post-boot MBC3 diagnostic
with no Nintendo logo or third-party data. It writes distinct values to RAM
banks 0 and 1, verifies both values, checks that disabled RAM reads as `$FF`,
and verifies bank contents after re-enabling RAM. The generated fixture passes
in the Python oracle and as a recompiled Genesis ROM observed through BlastEm.
Report: `compat-results/original-mbc3-ram-native.json`.

This verifies the tested volatile RAM enable/bank path. It does not verify
battery save persistence, MBC3 RTC registers/latching, or every mapper edge
case.

## Not yet run or not automatically verifiable

- Mooneye PPU, OAM-corruption, and emulator-only mapper suites beyond the
  explicitly listed subsets above.
- DMG-acid2 and all screenshot-only tests; image comparison is not implemented.
- CGB-only ROMs, which are reported as UNSUPPORTED rather than attempted as DMG.
- Gambatte, GBMicrotest, SameSuite, AGE, Mealybug, RTC/MBC and audio suites.
- Native Blargg serial results; the Genesis runtime has no automated serial
  output observer, so Python PASS is never copied into the native column.

## Reproduction

```bash
python3 -m unittest discover -s tests -q
python3 run_compat_tests.py test_roms/blargg/cpu_instrs/individual \
  --max-steps 12000000 --json compat-results/blargg-cpu.json
python3 run_compat_tests.py test_roms/mooneye-test-suite/acceptance/timer \
  --max-steps 1000000 --json compat-results/mooneye-timer.json
python3 run_compat_tests.py test_roms/mooneye-test-suite/acceptance/bits/reg_f.gb \
  --max-steps 150000 --compile-native --native-steps 150000 \
  --run-native-blastem --native-frames 600 \
  --json compat-results/reg-f-native.json
```

`--run-native-blastem` opens an emulator window. It uses BlastEm's debugger,
checks the source terminal loop and native GB register state, then quits.
