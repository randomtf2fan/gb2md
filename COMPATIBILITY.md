# GB2MD compatibility status



## General native CPU validation and writable code — 2026-11-09

This pass focuses on reusable CPU-test infrastructure rather than any game.
An optional `--test-serial` build now pairs diagnostic reference tracing with a
native instantaneous serial receiver. The compatibility runner enables it for
Blargg serial fixtures and observes the actual native message in BlastEm.
Normal builds and the GUI leave it disabled. This is a diagnostic link peer,
not hardware-accurate serial timing or serial-interrupt support.

Blargg `08-misc instrs` initially failed compilation because the native emitter
only handled multiple observed code variants in OAM/HRAM. Finite WRAM/echo-RAM
variants now each get native bodies and byte-match selection; unknown variants
trap, and cross-window multi-variant instructions are rejected. Original
fixtures verify WRAM, echo aliasing and an intentionally unseen variant trap.
Arbitrary self-modifying code and unobserved RAM entry points remain incomplete.

Current independently observed CPU results (all listed cases pass Python):

| Blargg individual ROM | Native Genesis | Detail |
|---|---|---|
| 01-special | PASS | Native diagnostic serial Passed |
| 03-op sp,hl | PASS | Native diagnostic serial Passed |
| 06-ld r,r | PASS | Native diagnostic serial Passed |
| 07-jr,jp,call,ret,rst | PASS | Native diagnostic serial Passed |
| 08-misc instrs | PASS | Previously compilation FAIL; fixed WRAM variant support |
| 02-interrupts | FAIL | Missing native RAM entry `$C1B9`; root cause still unresolved |

The interrupt trap does not prove that more steps alone will fix it; an
underlying execution difference could enter an untraced reporting path.
The remaining five individual CPU tests are NOT_RUN natively in this pass.
Across the six tested ROMs: five native PASS and one native FAIL; all six
fresh Python runs pass.
Python-only results from earlier sections remain distinct.

The native observer rejects uninstrumented builds, invalid/truncated buffers,
overflow, emulator failures and missing-block traps. Native failures now give
the runner a nonzero exit code. Original native serial fixtures produce both
Passed and Failed and exercise the busy-wait completion path. The buffer has a
512-byte safety limit and mode selection is recorded in reports.

**160/160 tests PASS with native integration enabled** (151 ordinary and nine
opt-in native methods), completed in385 seconds. The public fast suite passes
151 with nine native methods skipped. With instrumentation disabled,14 timer/reg_f images are byte-
identical to the earlier verified native binaries, and the preserved Tetris
metadata emits byte-identical assembly with its original tree dispatcher.
The GUI's actual build and cancellation checks pass. No commercial ROMs,
generated game assembly, test ROM binaries or trace files are published.

Reproduce a supported native serial check with external vasm and BlastEm:

```sh
python3 run_compat_tests.py 'test_roms/blargg/cpu_instrs/individual/08-misc instrs.gb' \
  --max-steps 400000 --compile-native --native-steps 400000 \
  --run-native-blastem --blastem /path/to/blastem --native-frames 3600 \
  --native-timeout 75 --native-output compat-builds/blargg-serial \
  --json compat-results/blargg-native-serial.json
```


## Indexed callbacks and additional native room progression — 2026-11-09

**150/150 tests PASS with native integration enabled** (143 ordinary and
seven opt-in native methods exercising original diagnostic ROMs under BlastEm).
The full run completed in 369 seconds. An actual GUI subprocess build and
cancellation check pass using the current compiler. All 14 timer/reg_f images
rebuild byte-identically to their earlier protocol-verified native versions;
this parity check is not a claim of new native protocol executions.

A bounded ROM-record/RAM-callback analyzer now derives bank selectors, record
copy spans and callback offsets from verified instructions. It does not assume
an application layout. Original fixtures cover relocated operands, ROM-only
mapping, MBC3, MBC5 bank zero, alias rejection and bounded analysis. Static
closure also handles a verified indexed-call helper preserving HL/DE/BC and
its restoring return trampoline. Scans stop at forward code boundaries to
avoid treating adjacent functions as additional pointers. These are candidate
coverage improvements, not a full reachability or points-to analysis.

The private longer-traced Pokémon image successfully boots, completes player
and rival naming, enters the room, responds to movement and interaction, and
**descends the stairs into the downstairs room**. Talking to the mother
character then traps on missing native entry `$12:$4170`, inside a text stream
that transfers control into inline code. This is limited indoor progression;
not a complete playable game. The tested image is byte-identical to a fresh
ordinary CLI build. Its SHA1 is
`7f54a513a5df01deb2e8d76f34e78017d01898f6`.

A separate fresh default-settings build (`--steps 15000000 --auto-inputs`)
executes 34,200,000 trace instructions and emits 37,927 entries. It matches the
static replay byte for byte, but native boot reaches missing entry
`$01:$42B7`, with a blank viewport and diagnostic marker/count set. It still
misses 127 entries present in the longer trace, despite adding other paths.
**Do not treat a successful build, more entries, or GUI defaults as complete
coverage.** Longer exploration remains necessary and still cannot guarantee
all conversations, outdoor paths or battles are compiled.

That default-settings image initially exceeded 4 MiB. Omitting the unused
8-byte-per-entry ROM debug catalog saves 303,416 bytes, allowing it to fit at
4,152,552 bytes while preserving all 2,262 hot chains, native code and live
dispatch. The builder tries catalog omission before reducing inline scheduler
stubs; `--keep-rom-catalog` preserves the export for external tools. Trace JSON
still lists entries. Native original fixtures verify the relocated ROM data
and callback/register behavior. No speedup measurement is claimed.

CPU, timers, DMA and Genesis runtime semantics are unchanged in this pass.
Known-good Tetris and Pokémon checkpoints remain intact. Other games were not
newly playtested; earlier statuses remain in the historical sections below.


## Long input exploration and native room movement — 2026-11-09

**126/126 tests PASS with native integration enabled** (121 ordinary and five
opt-in native methods). Fresh Python/frontend/native timer/reg_f checks pass
**14/14 in both domains with every scheduler chain forced compact**. Original
fixtures verify live controller input, RAM callbacks, initial-state bridges,
IRQ/mapper stack handling and bounded capacity retries. The GUI completed a
real original-ROM build with the sweep setting and cancelled a running build.

Optional `--input-sweep-steps` (GUI: Long input sweep) now follows a longer
Start/A trajectory with varied holds and explicit releases before short forks.
It consumes the existing input safety budget and is off by default. Snapshot
hashes now include pending DMA state and held inputs; useful non-novel states
are retained from initial snapshots as well as deeper branches. These are
general exploration changes; generated ROMs still read live controllers.

The private Pokémon candidate reached the opening room, displayed the SNES
interaction, and responded to Right, Down and Up. Camera/OAM endpoints matched
the corresponding reference room tests, including boundary stops. Missing-block
markers stayed zero during those actions. Walking to the staircase then traps
at `$12:$4168` when loading the downstairs callback. The reference reaches that
same target and continues. This is **limited room gameplay, not complete game
compatibility**; downstairs, outdoors, battles, saves and audio are unverified.

The deeper trace visited the older `$17:$40B0` callback 133 times. Its first
native image exceeded 4 MiB because many newly visited paths gained duplicated
scheduler stubs. The builder now halves a profile-ranked inline-stub quota and
reassembles without discarding any entries or retracing. It stops at zero and
preserves previous ROMs if no layout fits. The tested candidate retains every
entry from the previous build and adds 126. This is a capacity fallback, not a
speedup claim. A room interval measures about 11.64 source GB frames/second when
normalized to 60 Genesis frames/second; it is not wall-clock FPS at accelerated
BlastEm speed. Performance work remains pending.

Other games were not newly playtested. Earlier sections record historical
results. No commercial ROMs, generated game code, screenshots or state files
are included in the public source repository.

## Bounded discovery milestone — 2026-11-08

**119/119 tests PASS with native integration enabled**: 114 ordinary tests
and five opt-in native methods. Fresh frontend traces, builds and documented
protocol checks also pass **14/14 Mooneye timer/reg_f cases in both Python and
native BlastEm execution**. Extra native checks verify callback return writes
and restored ROM-bank data. CPU, timer, DMA and Genesis runtime sources are
unchanged. Native Blargg serial observation was open at this historical milestone;
the current matrix above supersedes that limitation. Broader PPU/DMA reruns remain open.

Pokémon's former `$03:$7113` target is entry 65 of a bank/address table whose
reader stopped at 64. The verified helper's aligned byte-index range supports
128 entries; discovery now uses that bound and reports each scan's stop reason.
The actual table has 99 valid entries and 93 targets. This was a coverage limit,
not an established mapper defect.

Selecting NEW NAME then exposed an untraced B/HL far callback at `$1C:$576C`.
Verified far-call discovery now includes both callback and bank-restoring return
trampoline. The next keyboard-selection trap at `$01:$6692` used an MSB-first
bit scan over return/callback pairs; bounded recognition now covers that exact
instruction pattern. All operands remain variable; no game addresses select
compiler behavior. ROM-only upper-window pointer tables are also handled.

The latest private native build accepts letters, confirms a custom player name,
accepts a preset rival name and advances through the final introduction without
those older traps. It then traps at `$17:$40B0` during room initialization.
The current bank and bank shadow agree; a fixed-ROM dispatcher loads its callback
from WRAM and jumps through HL. That unresolved data-driven target needs further
coverage analysis. **The room, overworld and playable Pokémon gameplay remain
unverified.** The image has 32,254 native blocks and is close to the supported
4 MiB limit; no game-speed improvement is claimed.

Existing checkpoints are unchanged. The GUI uses its sibling compiler and
receives these fixes after updating and recompiling; this does not update old
ROM outputs. Other games were not freshly playtested in this pass. Older
sections below are historical results, not current regression claims.

## Paged dispatch and naming follow-up — 2026-11-08

**110/110 unit/native tests PASS** (106 ordinary, four opt-in native methods).
Fresh native backend replay of the preserved timer/reg_f traces passes14/14;
Python results were carried forward, not rerun. Sparse programs keep their
tree; dense programs may use bank/page dispatch. Missing slots/pages/banks,
IRQ/mapper transitions, MBC5 bank zero and a large-program branch-range case
have native regressions. The original dispatch benchmark measures1.21608x
throughput, not a game FPS claim.

The unchanged Pokémon dialogue build accepts preset player/rival names and
reaches final introductory text, then traps at $03:$7113 toward the opening
room. Custom naming and overworld gameplay remain unverified. The smaller
paged Pokémon artifact has not been game-playtested. No known-good ROM was
overwritten. GUI builds use the new dispatcher automatically after updating.
Testing stopped at user request; older results below describe earlier passes.

## Banked discovery and code-size milestone — 2026-11-08

**109/109 tests PASS with native integration enabled**: 106 ordinary tests
plus three opt-in native methods. Original native fixtures cover banked tables,
bank shadows/setters, consecutive calls, inline pointer tables, controller
rows, and compact scheduler interrupt/mapper redirection.

Mooneye timers and `reg_f`: **14/14 Python and native PASS**. The first native
batch had 13 passes and a `div_write` timeout at 600 host frames; that ROM passes
at 2,500. Those attempts remain separate in the private reports. All fourteen
assemblies reproduce byte-identically with the final emitter. Native Blargg
serial verification and broader CPU/PPU/DMA reruns remain open.

The compiler now recognizes bounded bank/address tables, validated bank setters
and RAM shadows, inline BC-indexed tables, and returns through bank-preserving
leaf routines. Unknown effects still stop discovery. Native dispatch continues
to check the active bank; there are no game-title/address patches.

Untraced edges share native scheduler code. Identical 22,205-block coverage
shrunk from 5,015,608 to 3,488,384 bytes (30.45%). This is a code-size result,
not a measured performance improvement. Oversized output now fails before
replacing a previous ROM. Larger-than-4-MiB cartridge mapping is unsupported.

Tetris's preserved 7,187-block coverage was re-emitted and tested in BlastEm:
movement, rotation and fast drops placed pieces and advanced the score to 16;
Select hid/restored NEXT. Missing-block markers remained zero. This was a
backend regression, not a new frontend trace or extended line-clear/top-out test.
Known-good checkpoints remain unchanged.

Pokémon's final inline-table build reaches Professor Oak and advances readable
introductory dialogue in response to input. All four native samples have zero
missing-block markers and advancing source cycles. The former $00:$1B8A trap
is fixed. Player/rival naming, the initial room and overworld are unverified.
This is an introduction milestone, not a gameplay PASS. Link's Awakening
supports name entry/file creation, but its latest probe still traps at
$14:$5000 during file entry. Neither game has verified playable gameplay.
Current probes used a temporary BlastEm speed preset to shorten testing;
their wall time is not a native performance measurement.

GUI code is unchanged and uses its sibling compiler, including the new
`bank_analysis.py` module. Restart the GUI and recompile after updating.
The sections below are historical results for earlier source snapshots.

## Development update — 2026-11-08

Latest dispatch follow-up: **92 ordinary tests PASS, two opt-in native tests
PASS (94/94 with native enabled)**. Native integration checks two original
dispatch fixtures, compiled from two traced instructions, against their WRAM
result and zero missing-block marker. The compiler now recognizes bounded
HL-table lookup across forward jumps/BC/DE setup with exact verified helpers,
and fixed-ROM constant mapper-store + CALL/JP patterns. Unknown upper bank bits
are enumerated rather than assumed zero. No CPU/runtime changes in this pass.
Python Mooneye timers plus `reg_f`: **14/14 PASS**; their native results are
**NOT_RUN in this pass**, separate from historical native timer results below.

Link's Awakening now verifies name entry and in-session file creation. Selecting
the file first trapped at $14:$5326; the subsequent bank-call discovery build
passes that target and traps at $14:$523C. Save persistence and gameplay remain
unverified. Pokémon's NEW GAME selection reproducibly traps at $03:$7850,
supplied by a banked three-byte function table; general far-call discovery is
the next coverage investigation. Neither title is claimed playable.

No fresh extended Tetris gameplay regression was run in this pass. Its known
checkpoints remain unchanged. The GUI invokes its sibling compiler and uses
these coverage changes without new options; restart and recompile after update.
The following controller and earlier-runtime counts are historical snapshots.

Controller follow-up: **86 unit tests plus one opt-in native integration test
PASS**. Both selected JOYP rows now combine by active-low AND. A native tight
scan records the expected D7/EE/C6 for Start+Right; aggregate tracking finds
stable values with the tested six-button pad. An isolated X11 keyboard test
also reaches those values through SDL. The user's desktop focus/USB/Wayland
case remains unconfirmed. Default mappings are listed in README.

In the tested private Tetris build, NEXT is visible, Select hides it and a
second Select restores it, with missing markers zero. That is original game
behavior, not a demonstrated rendering regression. No game-specific fix was
added. Original ROMs and checkpoints are preserved.

The earlier source snapshot passed **84/84 focused tests**. The older dated results
below describe their respective revisions, not a full-suite rerun today.

- Fixed unsafe VBlank skipping for STAT polls, LY inequalities/register
  comparisons, and incrementing memory scans. Original HBlank-poll and memory
  scan fixtures pass in Python/native execution without invented interrupts.
- Added baseline STAT mode/edge handling and full-width tile-aligned windows.
  Original full/partial-window native probes verify map selection and scroll
  independence. Precise/raster PPU behavior remains incomplete.
- Extended bounded RST table discovery through fixed-ROM trampolines and
  observed-bank tail jumps. Fixed-to-banked calls no longer assume a unique
  observed address proves the active bank. Mapper writes resynchronize the
  execution bank before the next instruction. Native original MBC1 switch and
  banked RST fixtures pass; static MBC5 bank-zero discovery has regression
  test coverage.
- Pokémon Red reaches a recognizable title and NEW GAME / OPTION menu in a
  private runtime rebuild. Further gameplay is unverified.
- Link's Awakening's earlier build reached PLAYER SELECT then trapped at
  $1F:$469D. The latest dispatch follow-up above supersedes that limitation;
  gameplay remains unverified. No game addresses, names or hashes select
  compiler behavior.
- GUI output suggestions now follow a changed ROM while preserving custom
  destinations. The GUI always launches its sibling compiler with the current
  Python interpreter; restart the GUI and recompile after updating.

The polling-safe revision passed all 13 Mooneye timers in Python/native
execution (12 at 600 observation frames, div_write at 2,500 with 1M discovery
steps). A 200k-discovery div_write artifact timed out and remains a separate
result. The final bank-hardening changes have targeted native fixtures but
still need full timer/DMA/Tetris gameplay regression reruns. Native Blargg
serial verification, audio, save persistence and complete coverage remain open.

No commercial ROMs, compiled commercial outputs, screenshots, traces or
downloaded test fixtures accompany these reports.

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
- Native Blargg cases beyond the five explicit passes in the current matrix.
  The diagnostic serial observer is implemented; full serial hardware behavior
  remains unsupported. Python results are never copied into the native column.

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
