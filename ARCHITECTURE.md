# GB2MD architecture

This guide describes the current GB2MD implementation. It is written for a
developer who knows Python but is new to native recompilers, the Game Boy
SM83/LR35902 CPU, and Motorola 68000 assembly.

## What GB2MD is

GB2MD translates discovered Game Boy instructions into Motorola 68000 machine
code and packages that code with a Genesis-side hardware runtime. It is not an
SM83 interpreter: source instructions become labelled native 68000 blocks in
`translated_trace.s`. The runtime supplies services for operations that do not
have a direct 68000 equivalent, such as cartridge banking, Game Boy memory and
I/O, interrupts, timers, controller input, and conversion of Game Boy graphics
to Genesis VDP data.

The current design is trace-guided rather than a complete ahead-of-time static
compiler. Dynamic execution finds active ROM banks, computed targets, and
RAM-resident code. Conservative static passes then add recognized reachable
code that a finite trace did not execute. Consequently, a successful build is
not proof that every future path was compiled.

## End-to-end pipeline

The normal command is implemented by `build_recompiled.py`:

```text
owned .gb/.gbc ROM
        |
        v
Python execution and trace discovery (`compile_trace`)
        |
        +-- dynamic (bank, PC) instruction entries
        +-- controller/input exploration snapshots
        +-- direct control-flow and pointer-table closure
        v
semantic instruction records (`trace-profile.json`)
        |
        v
native lowering (`native_body`) -> `translated_trace.s`
        |
        +-- Genesis runtime (`runtime_68000.s`)
        +-- source cartridge data (`gb_cart_rom`)
        +-- generated colour/frame/renderer tables
        v
vasm Motorola syntax assembler
        |
        v
Genesis header, padding, checksum -> `recompiled.md`
```

`build_recompiled.build()` coordinates these stages. It calls
`trace_recompiler.compile_trace()`, writes generated assembly includes, embeds
the input ROM as cartridge data for runtime reads, invokes `vasmm68k_mot`, pads
the image, updates the Genesis ROM extent and checksum, and writes
`build-report.json`.

`gb2md.py` is an older, deliberately conservative bank-0 decoder and title-ROM
scaffold. Its `instruction_length()`, cartridge tables, and memory-plan helpers
are still shared, but the playable native path is `build_recompiled.py` plus
`trace_recompiler.py`.

## The Python execution oracle

`gb_cpu.py` contains the reference `CPU` and `Memory` classes used during
discovery and compatibility testing.

- `CPU.step()` executes one instruction or interrupt and applies its T-cycle
  cost from `instruction_cycles()`.
- `CPU._step_base()` implements SM83 instruction semantics, flags, delayed
  `EI`, `DI`, `HALT`, interrupt entry, stack operations, and control flow.
- `Memory.read()` and `Memory.write()` implement the Game Boy address map,
  JOYP, mapper registers, WRAM/VRAM/OAM/HRAM, timer registers, and interrupt
  registers.
- `Memory.tick()` advances DIV/TIMA, approximate LY, and VBlank state.

This is an executable reference for tracing and tests, not a frontend included
in the generated ROM. CPU bus activity is expressed as explicit four-T-cycle
machine cycles. OAM DMA uses a request/start pipeline, transfers one byte per
machine cycle, supports restart while the old transfer remains active, and
blocks CPU OAM access during an active transfer. PPU modes and VRAM access
restrictions remain incomplete, OAM corruption is not modeled, and LY is a
scanline approximation.

`gb_memory.py` contains a more explicit `MBC3` model, including RAM/RTC select
and latching, used as specification/test code. The native runtime currently
implements only a subset of those MBC3 services.

## Dynamic tracing and block identity

`trace_recompiler.compile_trace()` starts a fresh `Memory` and `CPU` for the
ordinary no-input scenario and for every manual `--input-script` scenario. A
fixed `--steps N` budget is per scenario. `--auto-steps` continues the same
scenario state in chunks while dynamic coverage grows, bounded by its maximum
and plateau settings.

`trace_step()` calls `CPU.step()` and records the bytes actually returned by
the instruction fetch bus together with the pre-step `(bank, PC)`. This matters
when DMA contention makes executable OAM read as `$FF`, and avoids tracing a
stale direct memory peek. HALT and interrupt-only cycles have no fetched
instruction and do not invent a trace entry. Bank zero identifies the fixed
`$0000-$3FFF` window; the selected mapper bank identifies execution in
`$4000-$7FFF`. The fetched bytes, hit counts, dynamic HRAM values, register
state, and stopping reason feed `trace-profile.json`.

Dynamic tracing is essential for computed control flow and RAM/HRAM code, but
it cannot establish whole-program reachability. Games may wait indefinitely
for input or select a target from data that a particular run never exercised.

## Automatic controller exploration

Automatic input exploration is enabled with `--auto-inputs`.

`reads_joypad()` recognizes instructions whose effective read address is
`$FF00` (P1/JOYP). Immediately before eligible reads,
`capture_input_state()` saves a deep copy of the CPU and memory. Snapshots are
deduplicated with `exploration_state_key()`, which includes CPU registers,
interrupt/HALT state, mapper state, timing phase, writable memory, I/O, and
external RAM. Excluding relevant state here could incorrectly merge snapshots
whose future behavior differs.

The explorer branches from selected snapshots using bounded actions from
`AUTO_INPUT_ACTIONS`, including individual buttons, directions, and a small set
of useful combinations. Each press is followed by release because
`joypad_state` returns to `$FF` after `input_hold_frames`. New `(bank, PC)`
blocks merge into the global trace.

Paths sometimes require two inputs even when the first input executes no new
code. The explorer therefore retains a small quota of deduplicated non-novel
**bridge states** per depth. Novel states remain higher priority. Branch count,
depth, instructions per branch, total exploration instructions, hold duration,
snapshot interval/count, and bridge quota bound the search. The generated ROM
does not replay exploration inputs; it polls the real Genesis controller.

## Static control-flow closure

After tracing, `compile_trace()` runs a worklist over discovered ROM entries.
It follows fallthroughs and both outcomes of direct conditional branches, plus
direct jumps, calls, returns-with-fallthrough, reset vectors, and safe constant
successors. This is why collision outcomes need not all occur in an exact
input trace.

Separate conservative recognizers handle two ROM dispatch shapes. The first is:

```text
LD HL, pointer_table
CALL index_helper
JP (HL)
```

It reads no more than 64 little-endian entries, requires at least two valid ROM
code pointers, and stops at the first invalid candidate. Targets are reported
separately as `indirect_table_targets`. This fixed an indirect Tetris piece
dispatch path, but it is not a general solution for all computed jumps or bank
tracking. Expanding it requires false-positive and banking regressions.

`hl_dispatch_table()` additionally recognizes a bounded variant with a forward
`JR` and intervening `LD BC,nn` / `LD DE,nn` setup. It follows at most 12
instructions within 32 bytes, requires an exact zero- or one-based pointer
lookup helper, and rejects unknown calls, HL writes, backward jumps and
ambiguous banked helpers. These discoveries use the same bounded table reader
and `hl_pointer_table_targets` counter. This covers more dispatch shapes; it
does not resolve arbitrary computed jumps.

`constant_bank_call_targets()` recognizes fixed-window `LD A,n / LD (mapper),A /
CALL nn` or `JP nn`. Valid MBC1/MBC3/MBC5 low-bank register writes yield a
bounded set of physically present target banks. Unwritten MBC1 high bits and
the MBC5 ninth bit are enumerated rather than assumed zero. Partial high-bit
writes, other stores and upper-window callers are rejected. Targets are counted
separately in `constant_bank_call_targets` in trace/build reports. This adds
coverage only: live native bank dispatch still determines which code executes.

The second recognizes an exact SM83 inline table-call handler reached through
`RST`: the handler pops the stacked return address, indexes the pointer table
immediately following the `RST`, and jumps to the selected routine. Once this
exact handler and at least two valid bounded pointers are present, the inline
bytes are treated as data rather than ordinary RST fallthrough. Reports split
these discoveries into `hl_pointer_table_targets` and
`rst_inline_table_targets`, while `indirect_table_targets` remains the unique
aggregate.

For dynamically copied HRAM and executable OAM, the trace retains every
observed byte sequence for a `(bank, PC)`. Generated bounded selectors compare
the live backing bytes and dispatch only to variants observed during tracing;
OAM selectors also choose the observed `$FF` instruction while DMA blocks the
bus. An unseen value enters `gb_missing_block`. Conflicting executable variants
outside these explicitly supported writable regions raise an error rather than
silently compiling the wrong bytes. This is finite variant compilation, not an
SM83 interpreter.

## Native SM83-to-68000 lowering

`lr35902_lowering.family()` maps SM83 opcodes into semantic families such as
`LD_R_R`, `ADD_A_R`, `CALL`, `CB`, and `DAA`. `native_body()` in
`trace_recompiler.py` lowers supported families into Motorola syntax.

Game Boy registers and flags live in fixed Genesis work-RAM locations such as
`gb_a`, `gb_f`, `gb_h`, and `gb_sp`; the 68000 CCR is not treated as the Game
Boy flag register. Memory operations call `gb_read8` or `gb_write8`. Direct
constant successors are threaded through generated `gb_chain_*` stubs to avoid
the general dispatcher on every instruction. Returns, indirect jumps, mapper
changes, interrupts, and uncertain control flow use a balanced `(bank, PC)`
dispatch tree.

Generated blocks publish their Game Boy T-cycle cost in `gb_step_cycles`.
Straight-line chains accumulate up to `SCHEDULER_BATCH_T_CYCLES` in 68000
register `d7`, then call `gb_tick` at a scheduling boundary. Timing-sensitive
I/O, delayed `EI`, HALT, branches, and possible interrupts force earlier
synchronization.

## Genesis runtime and memory mapping

`runtime_68000.s` owns all target-side Game Boy state. Important regions are:

| Game Boy concept | Genesis implementation |
|---|---|
| CPU registers, PC, SP, flags | Fixed fields beginning at `$FF0000` |
| I/O registers | `gb_io` at `$FF0100` |
| HRAM | `gb_hram` at `$FF0180` |
| OAM shadow | `gb_oam` at `$FF0200` |
| 8 KiB VRAM shadow | `gb_vram` at `$FF0300` |
| 8 KiB WRAM/echo backing | `gb_wram` at `$FF2300` |
| 32 KiB volatile cartridge RAM | `gb_eram` at `$FF4300` |
| Cartridge ROM | `gb_cart_rom` in the Genesis ROM image |

`gb_read8` and `gb_write8` route logical 16-bit Game Boy addresses to these
regions. ROM-window reads use `gb_rom_bank`; writes below `$8000` update the
implemented mapper state. The native runtime implements low ROM-bank selection
and volatile external-RAM enable/banking for its current MBC1/MBC3 paths, plus
MBC5 low/high ROM-bank and RAM-bank controls. MBC1 size masks and multicart
edge behavior, MBC3 RTC selection/latching, battery-backed save persistence,
and broader mapper semantics remain incomplete.

There is intentionally no direct mapping from Game Boy VRAM to `$C00000`.
`$C00000` is the Genesis VDP data port, not byte-addressable video memory.

The native `gb_read8` and `gb_write8` decision trees split the writable
`$C000-$FFFF` half first, then split I/O/HRAM at `$FF00`. Generated code embeds
ROM operands, while live game state repeatedly accesses WRAM and high memory,
so this ordering removes comparisons from the common path. It is only a search
ordering change: every region still reaches the same backing store and helper.

## Timing, interrupts, HALT, and polling loops

`gb_tick` consumes `gb_step_cycles` plus batched straight-line cycles. It
advances the divider, TIMA overflow/reload events, approximate scanlines and
LY, raises VBlank, applies delayed `EI`, wakes HALT, and enters the highest
priority enabled interrupt. The current timer model passes the project’s
Mooneye timer subset in both Python and native execution.

`gb_idle_wait` and `gb_idle_ly` accelerate recognized read-only polling loops
to an event boundary. They are deliberately conservative: timer-active or
interrupt-incompatible cases fall back to normal translated execution. The
current frame scheduler advances simulated Game Boy time as fast as native
work completes; there is not yet a calibrated real-time pacing layer. Native
throughput is therefore a compatibility and performance concern.

`gb_halt_wait` handles a separate, very common case: a halted CPU waiting for
an interrupt. With TIMA disabled it advances directly to the next LY 144
boundary. With TIMA enabled, it calculates the earlier of VBlank and the next
enabled timer interrupt from TIMA, TAC, DIV phase, and any pending reload. It
advances in bounded chunks through `gb_tick`, preserving DIV, TIMA
overflow/reload, LY, VBlank, rendering, and interrupt state, then lets normal
interrupt selection wake the CPU. If the timer interrupt is masked, VBlank is
the next modeled wake event. `gb_tick` consumes every DIV and scanline boundary
crossed by a large batch. The counter at `$FF0044` records uses of these paths.
This is event batching, not an artificial clock multiplier.

OAM DMA is progressive in both oracle and runtime. A write to `$FF46` enters a
two-stage request/start pipeline; the transfer then copies 160 bytes at one byte
per machine cycle. A restart keeps the old transfer active until the replacement
starts. CPU reads from OAM return `$FF` and writes are ignored while DMA is
active. The native scheduler handles pipeline edges one machine cycle at a time
but bulk-copies a stable contiguous run within a scheduler batch, preserving
the modeled boundaries without paying one 68000 helper dispatch per byte.

The model intentionally stops short of full hardware bus arbitration. It does
not yet restrict all non-HRAM CPU accesses during DMG DMA, emulate OAM
corruption, or model CGB DMA buses. Those remaining gaps should be tested
separately from the now-passing targeted Mooneye DMA/start/restart/source cases.

## Graphics and controller input

Game Boy VRAM and OAM writes set dirty flags. At a VBlank-like boundary,
`gb_render_frame` converts 2bpp Game Boy tiles through
`gb_2bpp_nibble_table`, uploads the selected 32x32 background map into the
centered 160x144 viewport, maps DMG palettes into Genesis CRAM, applies scroll,
and converts 40 OAM objects into Genesis sprite attributes. OAM-only changes
skip tile and background conversion. Tile-map writes (`$9800-$9FFF`) dirty
only the map; pattern writes (`$8000-$97FF`) dirty pattern data. Scroll,
palette, and map-only refreshes therefore avoid converting and uploading all
640 Genesis patterns. Plane A's transparent outside area is initialized once.

The renderer supports backgrounds, scroll, DMG palettes, and basic 8x8/8x16
sprites with flips and behind-background priority. A full-screen Game Boy
window (WX=7/WY=0) selects the window map without BG scroll. Full-width
windows starting on a tile row (WX=7, WY=8..136 in steps of 8) use the Genesis
window plane at D000-DFFF; Plane A occupies C000-CFFF, Plane B E000-EFFF,
and the sprite table F000. The Genesis vertical window boundary is positioned
at viewport row 5 plus WY/8, so window tiles ignore SCX/SCY while the background
above still scrolls. Original native diagnostics verify the two map planes.
Other partial windows,
accurate PPU modes, per-scanline effects, access restrictions, and strict
viewport sprite clipping remain incomplete. These gaps can be visually
significant even when CPU execution continues. The private experimental
renderer now tracks individual dirty pattern tiles and updates their sprite
copies; broader visual/gameplay validation is still pending.

`gb_read_joypad` converts the Genesis pad’s active-low signals into the selected
Game Boy JOYP row. Genesis B/C map to Game Boy A/B and Genesis A/Start map to
Select/Start. Trace discovery inputs never appear in this routine.

## Missing-native-block diagnostics

If dispatch cannot find `(gb_bank, gb_pc)`, `gb_missing_block` writes marker
`$BADB10C0` at `$FF0018`, increments `gb_missing_count` at `$FF0038` once, and
loops while preserving the Game Boy bank, PC, and registers. This distinguishes
incomplete trace coverage from a slow transition, a deliberate wait loop, or a
rendering defect. It is a diagnostic trap, not a recovery mechanism.

## GUI

`gb2md_gui.py` is a thin PyQt5 wrapper, not a second compiler. `compiler_command()`
constructs the `build_recompiled.py` invocation. `ConverterWindow` uses
`QProcess` to stream logs, cancel a build, and open its output directory. It
exposes fixed/automatic step budgets and automatic-input limits. Generated GUI
outputs default under `gui-builds/`; output inside immutable `test_roms/` is
rejected.

## Testing infrastructure

Focused unit and smoke tests live in `tests/`. They cover CPU semantics,
lowering, automatic budgets and inputs, static closure, generated runtime
properties, GUI command construction, and build behavior.

`run_compat_tests.py` discovers immutable ROM fixtures and keeps Python and
native results separate:

- `run_python()` executes documented Blargg serial or Mooneye register
  protocols with instruction/frame/loop limits and records full diagnostics.
- `compile_native()` assembles only Python-passing tests but leaves them
  `NOT_RUN` until a native success condition is observed.
- `run_native_blastem()` currently observes Mooneye Fibonacci register
  signatures through the BlastEm debugger.
- `write_report()` produces JSON status counts and per-ROM details.

A ROM drawing a recognizable image or reaching a loop is not automatically a
PASS. Screenshot suites, native Blargg serial observation, and broad native
differential testing remain unfinished.

## Polling and bank safety update (2026-11-08)

The compiler only marks known WRAM/HRAM flags or exact LY-equality waits for
skipping. Hardware, unknown-address and incrementing-memory predicates run
normally. New flag loops call `gb_idle_flag_wait`; legacy `gb_idle_wait`
flushes timing without skipping. `is_inline_rst_dispatch()` recognizes two
exact stack-consuming table dispatch forms through bounded fixed-ROM JP
trampolines. Immediate banked tail jumps can use observed RST caller mappings;
other bank dataflow remains unresolved. Trace reports separate banked thunk
targets from dynamically discovered blocks.

`gb_normalize_bank` derives execution identity from PC and the selected mapper
bank. Mapper stores force a charged boundary/resynchronization. A unique
observed address is never sufficient for a fixed-ROM caller to bypass bank
dispatch. Missing code remains a diagnostic rather than executing another
bank's bytes. MBC5 bank zero is a valid upper-window identity.

## Current capability boundary

Working and verified at the time of writing:

- All 84 focused unit/smoke tests pass.
- Eleven individual Blargg CPU tests pass in the Python oracle.
- Thirteen Mooneye timer tests and `bits/reg_f` pass in Python and verified
  native Genesis execution.
- The expanded 28-ROM Mooneye CPU/control set passes in Python. The targeted
  six-ROM OAM-DMA set passes in both Python and verified native execution.
- GB2MD's original generated MBC3 diagnostic passes in Python and native
  execution for two volatile RAM banks and RAM disable/re-enable behavior.
- The automatic Tetris checkpoint boots, accepts real controller input, enters
  A-Type play, scores, clears lines, survived an extended manual session, and
  completes the reproduced forced-top-out/game-over route.

Incomplete or unresolved:

- Tetris still runs below real Game Boy speed; measured throughput is the
  current bottleneck. Pause, B-Type, audio, and exact top clipping remain
  unverified.
- Trace/static closure cannot yet prove or discover all computed targets.
- Full DMA bus arbitration/corruption, precise PPU timing/window/clipping,
  audio, complete mapper RTC/save persistence, and native Blargg serial
  observation are missing.
- Super Mario Land's HALT-loop slowdown is fixed and its last known `F2`
  instructions lower natively. World 1-1 now renders, advances its timer, and
  responds to sustained Right movement; jump and collision/death paths have
  also executed without missing blocks. Longer gameplay and exact pacing still
  need verification. Pokémon Red has a user-reported title boot with severe
  slowdown and incorrect graphics. Bad Apple's first interrupt wait was
  missing STAT generation; see `COMPATIBILITY.md` for measured progress.

`Memory._update_stat()` and native `gb_stat_sync` now model baseline PPU modes
(80-dot OAM, fixed 172-dot transfer, remaining HBlank, and VBlank), coincidence,
and a rising edge on the combined enabled STAT sources. Native `gb_tick`
visits mode boundaries even in larger batches. `gb_halt_wait` stops at the
next mode boundary when STAT is enabled and the timer is inactive; timer-active
STAT waits retain the conservative path. This is not a pixel FIFO: variable
transfer length, LCD start/stop phase, line-153 details, STAT-write glitches,
and accurate access restrictions remain incomplete. Native mode-register
reads still inherit scheduler batching granularity. `stat_diagnostic_rom()`
in `tests/test_smoke.py` is an original interrupt/HALT regression fixture.

The design rule for all fixes is to reproduce the smallest general hardware or
compiler error, repair the shared implementation, and add a regression. Game
titles, hashes, individual PCs, and game-state addresses must not enter the
general compiler/runtime as compatibility shortcuts.
