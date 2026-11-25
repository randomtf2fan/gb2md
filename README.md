# GB2MD

An intentionally conservative, trace-guided recompiler for converting a
legally obtained Game Boy ROM into native Genesis 68000 assembly. The current
Tetris v4 milestone reaches A-Type gameplay, supports movement, rotation, soft
drop, locking, scoring and line clears, and completes the reproduced game-over
route. Full compatibility is not claimed: performance, audio, pause, B-Type,
top-border clipping, and unvisited execution paths remain incomplete.

The Genesis presentation centers the 160x144 GB viewport inside a Game Boy-style
bezel. `build_recompiled.py` accepts `--color-profile green` (default), `dmg`,
`pocket`, or `amber`. This profile boundary is ready for future Super Game Boy
palette packets, but automatic SGB command decoding is not implemented yet.

## Graphical converter

The optional PyQt5 interface is a thin wrapper around `build_recompiled.py`.
It selects a `.gb`/`.gbc` file, output folder, and trace budget, then streams the
compiler's output and errors into the window. Generated files default to
`gui-builds/<rom-name>/`; the original ROM is never modified.

### AI assistance disclosure

GB2MD was developed with substantial assistance from AI coding tools,
primarily OpenAI Codex. AI assistance was used for code generation, debugging,
optimization, testing, and documentation. Project direction, requirements,
physical-hardware testing, and development decisions were guided and reviewed
by the project maintainer.

As with any software developed using automated tools, bugs and inaccuracies may
remain. Contributions, bug reports, and independent code reviews are welcome.

```sh
python3 gb2md_gui.py
```

Install the optional GUI dependency with
`python -m pip install -r requirements-gui.txt` before launching the GUI.

The resulting Genesis image is `<output folder>/recompiled.md`. The CLI remains
fully usable and is the stable boundary beneath the GUI.

The GUI starts `build_recompiled.py` from its own directory with the current
Python interpreter. Keep the project files together, restart the GUI after an
update, and recompile: existing ROM outputs do not update automatically. When
switching input ROMs, the suggested destination follows the ROM unless you
chose a custom destination.

The current GUI/build checks were run on Linux (Manjaro). Windows packaging
and emulator integration have not been verified in this update.

For programs needing longer input sequences, the optional **Long input sweep**
GUI setting alternates Start/A with varied holds and releases during discovery.
It is off by default. Its steps come from **Input safety limit**, so increase
that limit when reserving time for both the sweep and short branches. The CLI
uses `--auto-inputs --input-sweep-steps N --input-max-steps TOTAL`.
This heuristic can discover RAM-loaded callbacks, but does not prove complete
coverage or guarantee gameplay. Generated ROMs always use live controller input.

## Controller mapping

GB2MD reads Genesis controller port 1. With BlastEm's default keyboard bindings:

| Game Boy input | Genesis input | Keyboard |
|---|---|---|
| D-pad | D-pad | Arrow keys |
| A / B | B / C | S / D |
| Select | A | A |
| Start | Start | Enter |

Custom emulator mappings can differ. Click the game window to give it keyboard
focus. In original Tetris, Select hides/restores NEXT; keyboard A therefore
toggles that display rather than rotating a piece. Use S/D for rotation.

An optional native controller regression requires external tools and a display:

```sh
GB2MD_NATIVE_TESTS=1 GB2MD_BLASTEM=/path/to/blastem GB2MD_VASM=/path/to/vasmm68k_mot python3 -m unittest discover -s tests -q
```

Ordinary unit tests skip that external-emulator test.

## Local dependencies and private inputs

Python 3 is required. The native build expects an external vasm
Motorola-syntax M68k assembler (`vasmm68k_mot`) on `PATH`, through
`GB2MD_VASM`, or through `--assembler /path/to/vasmm68k_mot`. vasm is not part
of the intended public GB2MD source tree: its local terms allow unmodified
non-commercial redistribution and contain additional module copyrights, so it
should be obtained and built separately unless redistribution permission and
all obligations are reviewed. BlastEm is optional and likewise treated as an
external local test dependency.

The `test_roms/` collection and all input `.gb`/`.gbc` files are local fixtures
and are ignored by the repository safety rules. The 177 focused unit tests use
synthetic data and do not require commercial ROMs. Compatibility-suite runs
require the user to supply the relevant test ROMs separately.

Twenty additional native integration methods use original diagnostic ROMs
generated from test source: controller rows, static dispatch discovery, compact
scheduler interrupt/mapper paths, missing dispatch slots/pages/banks, and
far-call bank restoration, indexed record/RAM callbacks, preserving indexed calls,
interrupt-entry cancellation, cross-window byte guards, timed stack reads, phased stack writes, exact IRQ-boundary checks, RMW bus phases, and guarded register-run equivalence. Enable them with `GB2MD_NATIVE_TESTS=1`, `GB2MD_BLASTEM=/path/to/blastem` and
`GB2MD_VASM=/path/to/vasmm68k_mot` when running the unit suite. They check result memory plus missing-block diagnostics. BlastEm normally opens
a window. For unattended testing on a shared desktop, use an isolated virtual
display and explicitly select the X11 SDL driver; setting `DISPLAY` alone may
leave SDL using the desktop Wayland session. `GB2MD_BLASTEM` can point to a
local wrapper that enforces this isolation and fails if it is unavailable.

Static coverage now includes bounded bank/address tables, bank shadow stores,
verified bank-setter helpers, and consecutive calls through proven
bank-preserving leaf routines. Verified B/HL far calls include the callback
and return trampoline; exact input-bit dispatchers include return/callback
pairs. A bounded record-copy analyzer derives RAM callback fields from verified
bank selectors and copy/caller instructions, without application layouts. Recognized bank/address tables have a 128-entry bound derived from the
helper arithmetic and report truncation. These improve coverage but do not
guarantee that every computed jump is discovered. Cold native scheduler stubs
share code to reduce output size. If an image exceeds the supported 4 MiB
layout, the builder first omits an unused duplicate ROM debug catalog, then
tries packed and bounded dispatch leaves before profile-ranked compact
scheduler stubs, retaining every translated
entry. `--keep-rom-catalog` retains the export for external debugging tools. If it still cannot fit, compilation fails before
replacing an existing `recompiled.md`. Larger cartridge mapping is unsupported.

Dense programs can use a bank/page native dispatch table; small or sparse
programs retain the decision tree automatically. An original dispatch-heavy
benchmark measured 1.216x throughput; actual game speedups remain unmeasured.
Run `python3 benchmark_dispatch.py --blastem /path/to/blastem` with an external
assembler configured to reproduce it. Output defaults to ignored
`compat-builds/dispatch-benchmark/`; no commercial ROM is needed.

Generated `recompiled.md` files are Mega Drive ROM binaries, not Markdown.
They include source cartridge data needed by runtime banked reads and therefore
must not be published when built from a commercial game. Build directories,
checkpoints, traces, screenshots, logs, and compatibility results are private
generated artifacts and are ignored by `.gitignore`.

GB2MD does not include or grant rights to commercial game ROMs or Nintendo
assets, and it is not affiliated with or endorsed by Nintendo or Sega. Users
are responsible for obtaining and using ROMs and third-party tools lawfully.

### Automatic trace budget

`--steps` remains an exact instruction budget applied separately to the
no-input trace and every input scenario. Optional auto mode treats it as the
initial chunk and extends the live scenario while basic-block coverage grows:

```sh
python3 build_recompiled.py game.gb --out build-game --steps 250000 \
  --auto-steps --auto-max-steps 50000000
```

`--auto-chunk-steps`, `--auto-plateau-chunks`, and
`--auto-min-new-blocks` tune the policy. Scheduled input/memory events prevent
plateau termination until their frame is reached. A plateau is reported as a
heuristic stop, not proof of complete coverage. Exact counts and stop reasons
are written to `trace-profile.json` and `build-report.json`.

### Reusing coverage between builds (advanced CLI)

`--coverage-profile` merges a previous `trace-profile.json` for the **exact same
ROM** before static closure. Repeat the option to merge several runs:

```sh
python3 build_recompiled.py owned-game.gb --out build-next --steps 15000000 \
  --coverage-profile build-previous/trace-profile.json
```

New profiles contain a source SHA-256. Imports reject a different cartridge,
incorrect ROM instruction bytes/banks and malformed entries. Legacy profiles
without that digest are rejected. RAM-code observations retain native byte
checks, including traps for unseen modifications. Import trusted local profiles;
a cartridge digest cannot authenticate user-supplied RAM observations.

This reuses code coverage, not an emulator snapshot or controller playback.
Current trace steps and fresh dynamic entries are reported separately from
imported observations and static candidates. Missing paths can still trap, and
merged code may exceed the Genesis image-size limit. Imports currently require
the CLI; existing GUI settings and fresh tracing remain unchanged. Profiles
contain instruction bytes: keep commercial-game profiles private, outside the
public source tree, along with generated ROMs.

### Automatic controller exploration

`--auto-inputs` branches from deduplicated emulator snapshots taken before
JOYP reads. It explores bounded button presses and releases, prioritizes paths
that add executable `(bank, PC)` targets, and retains a small quota of ordinary
state-changing transitions so useful multi-input sequences are not discarded.

```sh
python3 build_recompiled.py game.gb --out build-game --steps 7500000 \
  --auto-inputs --input-max-branches 128 --input-max-depth 4 \
  --input-max-steps 20000000
```

The PyQt5 GUI exposes these primary limits and enables the experimental feature
by default. This exploration is bounded and cannot prove whole-game coverage.
Manual `--input-script` scenarios remain available for advanced regression
routes. Missing native coverage writes `$BADB10C0` at Genesis RAM `$FF0018`;
the requested GB bank and PC remain at `$FF0000` and `$FF0002`.

## Compatibility testing

`run_compat_tests.py` recursively discovers the immutable ROM fixtures under
`test_roms/`, recognizes Blargg serial, Mooneye register and GBMicrotest RAM
protocols, applies
instruction/frame limits, and writes machine-readable JSON outside the fixture
tree. Python and native Genesis results are deliberately separate.

```sh
python3 run_compat_tests.py test_roms/blargg/cpu_instrs/individual \
  --max-steps 12000000 --json compat-results/blargg-cpu.json
python3 run_compat_tests.py test_roms/mooneye-test-suite/acceptance/timer \
  --max-steps 1000000 --json compat-results/mooneye-timer.json
```

An opt-in native stage compiles Python-passing fixtures. It can open BlastEm,
inspect supported register, serial or GBMicrotest RAM protocols, and close
the emulator automatically:

```sh
python3 run_compat_tests.py test_roms/mooneye-test-suite/acceptance/bits/reg_f.gb \
  --max-steps 150000 --compile-native --native-steps 150000 \
  --run-native-blastem --native-frames 600
```

Current measured results and limitations are in [COMPATIBILITY.md](COMPATIBILITY.md).
The broader collection snapshot is [TEST_ROM_RESULTS.md](TEST_ROM_RESULTS.md).
`halt_fetch_probe.py --out compat-results/halt-fetch` generates original
reference probes for the known HALT bug; add `--native --blastem PATH` to
verify native fetch semantics. The control, one-byte and immediate probes now
pass in both backends; writable-code suppressed fetch remains unsupported.
GBMicrotest requires at least24 simulated source frames before its RAM flag
is accepted; use `--suite gbmicrotest --max-steps 1000000 --max-frames 24`.
Native observation also enforces this source-clock floor. Increase the native
frame budget if it times out before reaching it.

### Original homebrew diagnostic

`make_homebrew_test_rom.py` generates a small original MBC3 external-RAM test.
It contains no commercial ROM data, Nintendo boot-logo bytes, or extracted
assets. The diagnostic is intended for GB2MD's documented post-boot execution
model and checks two RAM banks plus RAM disable/re-enable behavior.

```sh
python3 make_homebrew_test_rom.py homebrew-mbc3-test.gb
python3 build_recompiled.py homebrew-mbc3-test.gb \
  --out build-homebrew-mbc3 --steps 10000
```

The generated `.gb` and `.md` files are ignored build fixtures, not repository
source. The Python unit suite verifies the diagnostic's register protocol; the
native result must still be observed separately through BlastEm.

## Recompiled gameplay build

Input-dependent paths can be merged without baking input into the output ROM:

```sh
python3 build_recompiled.py tetris.gb --out build-tetris-gameplay \
  --steps 7500000 \
  --input-script 'start@512:8,start@700:8,start@800:8,a@860:8,left@880:8,right@900:8,down@920:8,a@940:8,b@960:8,up@980:8' \
  --input-script 'start@512:8,start@700:8,start@800:8,down@860:140'
```

Each pulse is `button@start_frame:duration`; simultaneous buttons use `|`.
Scripts affect discovery only. The generated Genesis ROM still reads the real
controller at runtime. The preserved guided build contains 3,864 native blocks.
The independently generated automatic-input candidate contains all 3,864 of
those blocks within 4,792/4,792 native blocks and reached A-Type gameplay in
BlastEm without manual trace scenarios. See `COMPATIBILITY.md` for the exact
artifact, verification level, and remaining limitations.

Discovery scripts may also include a generic reference-only memory event such
as `poke:0xCA22-0xCA2B=0x8C@850`. This is useful for deterministic rare-state
coverage; it is never embedded in or replayed by the generated ROM.

## Architecture decision

| Game Boy region | Genesis implementation |
|---|---|
| ROM/MBC ($0000-$7FFF) | Source image plus MBC state in the 68000 runtime; a bank is not a Genesis address. |
| VRAM/tile maps ($8000-$9FFF) | 68000 shadow and a converter feeding the VDP’s 64 KiB VRAM. GB 2bpp tiles can be expanded to Genesis 4bpp. |
| WRAM/HRAM/OAM | 68000 work RAM ($FF0000-$FFFFFF); OAM is converted to the VDP sprite table. |
| I/O ($FF00-$FF7F) | Service calls: controller, timer/interrupt scheduler, PPU registers, and YM2612/PSG audio backend. |
| Genesis Z80 | Audio driver only, with its 8 KiB RAM at $A00000-$A01FFF; it is neither compatible enough nor large enough to run GB code. |

This is a 68000-first design. The sound Z80 controls YM2612/PSG; the 68000 owns
game simulation and VDP updates. Never map GB `$8000` directly to `$C00000`:
the latter is a VDP **port**, not byte-addressable VRAM.

## Legacy scaffold tool

```sh
python3 gb2md.py /path/to/owned-game.gb --out build
```

This older `gb2md.py` path is a bank-0 analysis/title-ROM smoke tool, not the
current gameplay recompiler. Use `build_recompiled.py` (directly or through the
GUI) for the trace-guided native pipeline described above.

For the currently implemented end-to-end target milestone, append
`--emit-title-rom`. It creates `build/title_screen.md`: a bootable Genesis ROM
whose native title screen uses the input cartridge's header title. This proves
the conversion pipeline and target ROM generation, but does not yet run the
source game's gameplay code.

The tool recursively follows only fixed control flow in bank 0 and emits
`build/translated_bank0.s` and `build/memory-plan.json`. Unknown opcodes, flags,
banked targets, and peripherals are deliberately reported rather than silently
miscompiled. It does not copy the input ROM into output artifacts.

## Current implementation boundaries

DMG VBlank entry now includes the OAM-enabled STAT request. Native acceleration
of the recognized LY equality loop preserves its 32T iteration and 12T read
phase instead of snapping to a scanline boundary; differential checks verify
source-cycle agreement with ordinary execution. This improves timing correctness,
not complete PPU compatibility. See [the implementation details](ARCHITECTURE.md#dmg-vblank-stat-event-and-ly-polling-cadence-2026-11-25).

The earlier LCD stop/restart correction added an independent display clock,
retained STAT comparison state, and native PPU read/write synchronization.
Mooneye `stat_lyc_onoff` passes on both backends. That change reduced source-clock
advancement in the fixed video benchmark by about 11%; the subsequent VBlank/LY
correction leaves throughput essentially unchanged from that baseline. Exact
PPU timing and game speed remain incomplete; see [current results](COMPATIBILITY.md).

Standard MBC1 cartridges with complete, matching power-of-two ROM headers now
resolve both ROM windows, disconnected address lines, mode changes, and RAM
mirrors consistently in Python and native code. Multicart MBC1M wiring remains
unimplemented, and malformed/truncated MBC1 images retain the earlier scope.
This does not guarantee complete trace coverage or fix PPU/startup timing.
See [compatibility results](COMPATIBILITY.md) and [mapping details](ARCHITECTURE.md).

- Native memory helpers, bank-aware dispatch, partial MBC1/MBC3/MBC5 mapping, timer
  scheduling, interrupts, a DMG-to-VDP renderer, controller input, Genesis ROM
  headers/checksums, and bounded automatic input exploration are implemented.
- Tile maps and tile patterns have separate dirty paths, avoiding redundant
  full pattern uploads during scrolling and map-only updates.
- OAM DMA progresses over 160 machine cycles after its startup pipeline in the
  Python oracle and native runtime. CPU OAM accesses are blocked during an
  active transfer, restart timing is modeled, and the targeted Mooneye OAM-DMA
  acceptance set passes on both paths.
- Native cartridge RAM supports volatile RAM enable/banking for the currently
  modeled MBC1/MBC3/MBC5 paths. Save-file persistence and MBC3 RTC behavior are
  not implemented.
- Baseline PPU modes/STAT and full-width tile-aligned windows (WX=7, WY a
  multiple of 8 below 144) are implemented
  in the current development runtime and covered by original diagnostics.
  Precise PPU timing, partial/raster window rendering, access restrictions, audio,
  complete mapper/RTC/persistence behavior, OAM corruption, and some indirect
  control flow are incomplete.
- Tetris v4 is the strongest gameplay regression. The current Super Mario Land
  candidate leaves the former timer-active stalls, renders World 1-1, advances
  its timer, and executes movement, jump, and collision/death paths; extended
  gameplay and exact pacing are not verified.
- Pokémon Red has verified starter acquisition and multiple Scratch battle
  exchanges on an imported-coverage route. Growl and other animation paths
  still have uncovered code. Full battles, gameplay and normal GUI coverage
  remain unverified. Bad Apple remains incomplete.
  See [COMPATIBILITY.md](COMPATIBILITY.md) for measured evidence.

Native scheduler bookkeeping avoids redundant interrupt-deadline work and
register saves while preserving the existing 200-T-cycle cap and event
semantics. This is enabled for new CLI and GUI builds; existing ROMs require
recompilation. See [COMPATIBILITY.md](COMPATIBILITY.md) for measured results.
To compare against an older runtime using original synthetic programs, run
`python3 benchmark_scheduler.py --reference-runtime /path/to/old/runtime_68000.s
--out compat-builds/scheduler-comparison` with external vasm and BlastEm
configured. Results measure simulated source-clock throughput, not host FPS.

Large paged images can use a capacity fallback that stores native leaf
addresses in three bytes. The builder tries this automatically after optional
catalog omission and before reducing inline scheduler quotas; all code and
missing-block diagnostics remain present. Fitting images keep their existing
four-byte leaf format. The final cartridge window remains limited to 4 MiB.

If the packed image is still oversized, the builder can bound each leaf table
to its first and last populated instruction slots. Explicit bounds checks trap
outside that range; missing slots inside it keep their diagnostic pointers.
Every discovered entry remains compiled. Bank/page directories stay aligned,
and packed addresses use byte reads. This is an automatic capacity fallback
used by both CLI and GUI builds, not a coverage or universal speed guarantee.

If a bounded packed image remains oversized, nonzero execution-bank page
directories can be restricted to the normalized upper ROM window. Bank zero
keeps its complete directory, including MBC5 upper bank zero and RAM code.
This fallback preserves all entries and diagnostic traps and needs no GUI
setting. The final 4 MiB limit still applies.

Static discovery also accepts a bounded byte-offset ROM lookup when its index
was prepared before loading the table base. It does not prove complete computed
jump or script coverage; imported coverage remains an advanced CLI option.


## Sources

- Sega’s [Genesis Software Manual](https://fabiensanglard.net/another_world_polygons_Genesis/GenesisSoftwareManual.pdf) documents the 68000/Z80/VDP address spaces.
- [Pan Docs memory map](https://gbdev.io/pandocs/Memory_Map.html) documents the Game Boy address-space regions and echo RAM.
- The [GB platform overview](https://reverseengineering.wiki/index.php/Platform:Game_Boy) summarizes SM83 differences and cartridge bank switching.

## License

Original GB2MD source is offered under GPLv3 or later; see [LICENSE](LICENSE)
and [NOTICE.md](NOTICE.md). External tools, GUI frameworks, test suites, ROMs,
game data, and trademarks remain under their respective owners' terms. See
[THIRD_PARTY.md](THIRD_PARTY.md). This project is not affiliated with Nintendo
or Sega.

For compatibility tests, `run_compat_tests.py --compile-native
--run-native-blastem` observes supported Mooneye, Blargg serial and GBMicrotest
RAM protocols.
Blargg builds use an explicit diagnostic instantaneous serial peer, not a full
hardware serial implementation. The standalone `--test-serial` build option is
for diagnostics only and is disabled in normal builds and the GUI. Finite
observed WRAM/echo code variants are now compiled natively; unknown variants
still trap and arbitrary self-modifying code is not fully supported.

Native builds now specialize fixed-cycle register-only chain edges when all
statically linked predecessors agree on the cost. Normal GUI/CLI builds enable
this automatically after recompilation. `--no-chain-opt` restores the prior
scheduler for comparison. Timing boundaries, interrupt checks and memory/I/O
paths retain their existing behavior. `native-codegen-report.json` reports
specialized targets and omitted cycle-cost stores. Short hot register runs can
also share one guard when their entire cost fits before the next scheduler or
enabled interrupt boundary. All original entries and flag updates are retained;
memory/I/O and CPU-control instructions are excluded. Reports include selected
regions and their costs. `--no-chain-opt` disables both optimizations.
`benchmark_chains.py --fusion-only` compares register grouping while keeping
constant-cycle chains enabled in both modes. `benchmark_chains.py` uses
original synthetic ROMs to compare throughput; those ratios are not game FPS.

Interrupt-request and interrupt-enable writes now synchronize the native
scheduler so a newly eligible interrupt is checked before the next source
instruction. This fixes the reproduced native Blargg interrupt-test failure
without adding test-specific coverage or game patches. Broader interrupt
edge cases and incomplete trace coverage remain limitations.

If vasm reaches its layout pass limit, the builder retries once with `-no-opt`
and records that assembler mode in the build report. Normal builds retain
assembler optimization; syntax errors and repeated failures still stop without
replacing an existing ROM.

Enable **Speed counter** in the GUI or add `--show-fps` to display simulated
Game Boy clock FPS in the upper-left border. It is optional and off by default;
recompile to add it. The rate is sampled over50 PAL or60 NTSC Genesis VBlanks,
not the emulator's display FPS or a count of unique rendered images. It uses
nominal hardware time even during emulator fast-forward. See COMPATIBILITY.md
for measurement scope and tested overhead.

Known constant Game Boy high-RAM loads/stores now use direct native memory
access. Source timing, flags, write counters and mutable-code guards remain;
I/O, IE and indirect accesses keep their original paths. The GUI's **Faster
high RAM access** checkbox enables this by default. Disable it, or use
`--no-hram-opt`, for a compatibility comparison. Restart the GUI and rebuild
to use the update. `benchmark_hram.py` provides original-code A/B workloads;
see [COMPATIBILITY.md](COMPATIBILITY.md) for scoped results and limitations.

### Scanline background effects

The backend automatically uses scanline composition for visible SCX/SCY/BGP
changes in background-only scenes. The GUI uses this through the ordinary
compiler command. Static scenes return to the normal renderer; raster sprite
and window composition remain unsupported. This improves effects such as
palette/scroll-driven video, but is currently slow and can tear. See
[compatibility results](COMPATIBILITY.md) before assuming complete playback.


Raster composition reuses a row only when its full resolved pixel-plane inputs
and palette match. Tile/map changes and initial empty rows are checked before
reuse. This is enabled automatically, including GUI builds. For an A/B diagnostic
build, add `--no-raster-cache`; `build-report.json` records `raster_row_cache`.
Source timing is unchanged. Rebuild existing outputs to use the optimization;
it does not make video playback real time or speed up normal-renderer scenes.


MBC5 ROM-bank selection now resolves physical aliases consistently in tracing
and native execution while preserving the full nine-bit register. The GUI
uses this automatically; restart it and rebuild existing outputs. Standard
complete images use their connected bank bits. Incomplete MBC5 data reads are
bounds-checked instead of silently wrapping or reading beyond the embedded
ROM. Nonstandard cartridge wiring, other mapper types, RAM/rumble and the
current native 4 MiB image limit retain their documented limitations.

A recognized old-vasm branch-relaxation crash can trigger one recorded `-no-opt`
retry. Warnings are not suppressed, and other/repeated errors still fail.
See [the implementation guide](ARCHITECTURE.md) and
[measured compatibility](COMPATIBILITY.md) for validation and remaining gaps.
