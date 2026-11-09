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
and are ignored by the repository safety rules. The 151 focused unit tests use
synthetic data and do not require commercial ROMs. Compatibility-suite runs
require the user to supply the relevant test ROMs separately.

Nine additional native integration methods use original diagnostic ROMs
generated from test source: controller rows, static dispatch discovery, compact
scheduler interrupt/mapper paths, missing dispatch slots/pages/banks, and
far-call bank restoration, indexed record/RAM callbacks and preserving indexed calls. Enable them with `GB2MD_NATIVE_TESTS=1`, `GB2MD_BLASTEM=/path/to/blastem` and
`GB2MD_VASM=/path/to/vasmm68k_mot` when running the unit suite. They open BlastEm
windows and check result memory plus missing-block diagnostics.

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
tries profile-ranked compact scheduler stubs while retaining every translated
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
`test_roms/`, recognizes Blargg serial and Mooneye register protocols, applies
instruction/frame limits, and writes machine-readable JSON outside the fixture
tree. Python and native Genesis results are deliberately separate.

```sh
python3 run_compat_tests.py test_roms/blargg/cpu_instrs/individual \
  --max-steps 12000000 --json compat-results/blargg-cpu.json
python3 run_compat_tests.py test_roms/mooneye-test-suite/acceptance/timer \
  --max-steps 1000000 --json compat-results/mooneye-timer.json
```

An opt-in native stage compiles Python-passing fixtures. For Mooneye protocols,
it can open BlastEm, inspect the terminal source loop and emulated GB registers,
and close the emulator automatically:

```sh
python3 run_compat_tests.py test_roms/mooneye-test-suite/acceptance/bits/reg_f.gb \
  --max-steps 150000 --compile-native --native-steps 150000 \
  --run-native-blastem --native-frames 600
```

Current measured results and limitations are in [COMPATIBILITY.md](COMPATIBILITY.md).

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
- Pokémon Red and the tested Bad Apple demo do not yet produce playable native
  results. See [COMPATIBILITY.md](COMPATIBILITY.md) for measured evidence.

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
--run-native-blastem` now observes supported Mooneye and Blargg serial protocols.
Blargg builds use an explicit diagnostic instantaneous serial peer, not a full
hardware serial implementation. The standalone `--test-serial` build option is
for diagnostics only and is disabled in normal builds and the GUI. Finite
observed WRAM/echo code variants are now compiled natively; unknown variants
still trap and arbitrary self-modifying code is not fully supported.
