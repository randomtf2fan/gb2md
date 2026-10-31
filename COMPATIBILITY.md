# GB2MD compatibility status

Last measured: 2026-10-30. A PASS means the ROM's documented serial or
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
`compat-results/mooneye-reg-f-native-final.json`. The expanded Python run is
`compat-results/mooneye-cpu-control-expanded.json`.

Python PASS: `reg_f`, `daa`, `di_timing-GS`, `div_timing`, `ei_sequence`,
`ei_timing`, `halt_ime0_ei`, `halt_ime0_nointr_timing`, `halt_ime1_timing`,
`halt_ime1_timing2-GS`, `if_ie_registers`, `intr_timing`, `rapid_di_ei`, and
`reti_intr_timing`.

Python FAIL: `add_sp_e_timing`, `call_cc_timing`, `call_cc_timing2`,
`call_timing`, `call_timing2`, `jp_cc_timing`, `jp_timing`,
`ld_hl_sp_e_timing`, `pop_timing`, `push_timing`, `ret_cc_timing`,
`ret_timing`, `reti_timing`, and `rst_timing`. These ROMs start OAM DMA and
observe instruction bus activity while it is active. GB2MD currently performs
an atomic OAM copy and does not enforce the 160-machine-cycle DMA bus lock, so
the failure category is `oam_dma_model`, not an opcode-specific patch target.
Native execution for this group has not been claimed.

## Not yet run or not automatically verifiable

- Mooneye PPU/OAM-DMA acceptance and emulator-only mapper suites beyond the
  CPU subset above.
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
