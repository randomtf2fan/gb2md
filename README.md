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

```sh
python3 gb2md_gui.py
```

PyQt5 is already available as `python-pyqt5` on the current Manjaro development
machine. On another Arch/Manjaro installation use `sudo pacman -S python-pyqt5`.
On Windows or other Python environments, use
`python -m pip install -r requirements-gui.txt` before launching the GUI.

The resulting Genesis image is `<output folder>/recompiled.md`. The CLI remains
fully usable and is the stable boundary beneath the GUI.

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
and are ignored by the repository safety rules. The 56 focused unit tests use
synthetic data and do not require commercial ROMs. Compatibility-suite runs
require the user to supply the relevant test ROMs separately.

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

The follow-up `build-tetris-auto-input-v3/recompiled.md` adds conservative
closure for an exact SM83 `RST` inline table-call convention. It fixes the
reproduced Tetris game-over missing-block route without adding a title, hash,
or address rule. The separate `run_tetris_gameover_regression.py` tool can
reproduce the reference loss path and audit a generated trace profile.

`build-tetris-auto-input-v4/recompiled.md` is the current-runtime rebuild,
SHA-1 `2f41da094676bd7bf95d5d485eeff084dbbf1870`. Its forced-top-out native
regression returns to the normal state with zero missing blocks. The matching
checkpoint is `checkpoints/tetris-halt-fast-forward-2f41da09.md`.

## What the two cited “ports” establish

I could not locate a Genesis homebrew port of either *Super Mario Land* or
*Metroid II* to audit. The readily available *Super Mario Land* project is a
Watara Supervision (65C02) rewrite, and AM2R is a modern PC remake—not Genesis
implementations. Treating either as evidence of a Genesis hardware mapping would
be a false premise. This repository therefore documents an independent mapping,
based on the official Genesis memory map and Pan Docs.

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

- Native memory helpers, bank-aware dispatch, MBC1/MBC3 ROM selection, timer
  scheduling, interrupts, a DMG-to-VDP renderer, controller input, Genesis ROM
  headers/checksums, and bounded automatic input exploration are implemented.
- OAM DMA is still atomic and lacks the real 160-machine-cycle CPU bus lock.
- PPU modes, STAT behavior, window rendering, access restrictions, audio,
  complete cartridge RAM/RTC/persistence, and some indirect control flow are
  incomplete.
- Tetris v4 is the strongest gameplay regression. Super Mario Land v3 renders
  World 1-1 but remains at native dispatcher state `$0F`/`IE=$03`, while the
  Python oracle reaches state `$11`/`IE=$07`.
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
