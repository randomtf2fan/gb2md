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

The key also includes DMA request/start/active state, source, index and phase,
plus the currently held input byte. Equal memory arrays do not imply equal
future bus reads or JOYP values while those fields differ. Original regressions
check each field independently; CPU/peripheral semantics are unchanged.

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

Bridge states are eligible from initial snapshots as well as deeper branches.
A first press can latch a RAM flag without executing any novel PC; dropping it
would prevent a later press from reaching a new computed target. An original
branchless Start-then-A fixture covers this case with the same quotas and depth
limits. Deduplication and budget checks still bound those initial bridges.

An optional `--input-sweep-steps N` adds a longer trajectory before those short
forks. `InputSweep` alternates Start and A, with explicit release intervals and
five bounded hold scales relative to `input_hold_frames`. Release lengths vary
as well, avoiding a single fixed sampling phase. It starts from the completed
no-input CPU state and records real execution, so ROM data copied into RAM and
later used as a callback is discovered without knowing its addresses or format.
This heuristic does not recognize menus or guarantee progress in every game.

The sweep is off by default and requires `--auto-inputs`. It consumes one
branch and at most `min(N, input_max_steps)` instructions from the existing
input budget; it is not extra execution outside the safety limit. Depth limits
apply to subsequent forks, while the macro trajectory has its own instruction
bound. A bounded deque retains recent JOYP states for ordinary exploration
afterward. Reports identify sweep steps, new blocks, press count, endpoint and
stop reason separately. The GUI exposes the same optional budget as "Long input
sweep"; cancellation remains the existing compiler-process cancellation path.
An original ROM requires three separate A edges before calling a pointer stored
in WRAM; its test verifies discovery and the shared instruction cap.

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

The same helper also verifies inline BC-indexed lookups with optional BC
save/restore: double A, form a BC index, add it to the ROM table in HL, load
the little-endian target and JP(HL). Unknown instruction sequences do not
qualify. These use the existing bounded table reader and HL-target counter.

`constant_bank_call_targets()` recognizes fixed-window `LD A,n / LD (mapper),A /
CALL nn` or `JP nn`. Valid MBC1/MBC3/MBC5 low-bank register writes yield a
bounded set of physically present target banks. Unwritten MBC1 high bits and
the MBC5 ninth bit are enumerated rather than assumed zero. Partial high-bit
writes, other stores and upper-window callers are rejected. Targets are counted
separately in `constant_bank_call_targets` in trace/build reports. This adds
coverage only: live native bank dispatch still determines which code executes.

The constant-bank recognizer also permits bounded WRAM/HRAM shadow stores and
fixed-ROM setter helpers verified by `_bank_setter_register()`. A setter must
contain only one supported bank write, optional shadow stores and RET; changes
to A, unknown calls, hardware I/O shadows and partial high-bit writes reject it.
`constant_bank_call_site()` returns the actual call/jump PC for subsequent
context propagation instead of assuming all accepted sequences have equal size.

`banked_pointer_table_targets()` recognizes a verified three-byte lookup
sequence that returns an address in HL and stores a selected bank in WRAM or
HRAM. Each ROM table entry contains `bank, address_low, address_high`. It reads
at most 128 entries and requires two valid entries, validates physical bank and
ROM bounds, and rejects unknown code or I/O state operands. It
does not infer arbitrary far-call conventions. Its targets have a separate
`banked_pointer_table_targets` counter and join the indirect-target aggregate.

The 128-entry ceiling follows this helper's exact arithmetic: doubling a byte
index is non-overflowing for indices 0..127. Higher byte values produce
misaligned offsets and are not inferred as aligned triples. An optional
`diagnostics` dictionary records the table, effective budget, valid entry
count, unique targets and stop reason. Trace/build reports expose these as
`banked_pointer_tables`. Entry limits produce a warning; invalid pointers,
unmapped/unsupported targets and window boundaries have distinct stop reasons.
This prevents a bounded scan from silently looking like complete coverage.

`constant_far_call_targets()` handles constant B=bank / HL=address setup in
either order followed by CALL or JP through a verified fixed-ROM helper. The
helper must save its bank, select B, push a self-consistent return trampoline,
JP(HL), restore the bank and RET; bounded fixed-ROM aliases are accepted.
Discovery includes both the callee and that return entry, since ordinary
fallthrough stops at JP(HL). Counts appear as `constant_far_call_targets`
and `constant_far_call_returns`. Original native fixtures verify the callback,
restored data bank, ROM-only behavior and MBC5 bank zero. These are coverage
additions: the helper's instructions still execute as native code.

`bitmask_dispatch_targets()` recognizes an exact MSB-first input-bit scan.
An SLA/conditional-loop sequence advances a ROM pointer by four bytes per
unset bit; the selected record holds a return address followed by a callback.
The dispatcher pushes the return address and jumps to the callback. Static
closure therefore seeds both addresses, not just the callback. Eight input
bits bound the scan to eight records, and invalid pointers terminate it.
Unknown upper-window mappings and altered instruction sequences are rejected.
The separate `bitmask_dispatch_targets` count is included in trace/build
reports. Original tests exercise bit priority, the last bit, return execution,
signature rejection and ROM-only versus unknown bank mapping. This is bounded
pattern recognition, not general computed-jump analysis.

ROM-only code may also index a pointer table in the fixed upper ROM window.
The table reader maps that window directly instead of requiring an inferred
selected bank.

`ram_callback_analysis.py` connects one validated indexed record-copy convention
with RAM-loaded indirect calls. `RamCallbackAnalyzer.selector()` verifies a
fixed-ROM helper that saves HL/BC, reads a byte bank table through a temporary
bank, restores the prior bank, then selects the result. Save/restore slots,
shadow, scratch byte and mapper operands must agree and must not alias.

The analyzer then follows bounded bank/index-preserving fixed-ROM continuations.
It recognizes a doubled-index ROM pointer lookup followed by a literal-size
byte copy into RAM, and a caller loading a RAM word into HL before JP(HL).
Both contexts must use the same selector and index variable. The callback word
must lie inside the copied record; its offset is computed from the two RAM
operands. Unknown calls/stores, index overwrites and changed helper sequences
reject the proof. No application record layout or game addresses are supplied.

`discover()` examines at most256 byte indices and validates mapped ROM bounds,
record spans and callback instruction bytes. Invalid records are skipped,
allowing gaps; candidates are not proof of actual reachability. MBC1/5 unknown
upper bank bits are enumerated through the existing bank-candidate function.
ROM-only mapping and MBC5 bank zero have original native tests. This is not a
general points-to analysis and does not cover arbitrary copy/helper conventions.

When ordinary static closure drains, `compile_trace()` adds these candidates
and explicit consumer-return entries, then resumes closure to a fixed point.
Trace/build reports expose `ram_callback_targets`, `ram_callback_returns`,
`ram_callback_records` and `ram_callback_analysis_limits`. Context walks and
record pairs have bounded budgets (defaults128 and64); exhausted budgets warn.
The original loader, RAM contents, bank selection and calls still execute as
native instructions. The analysis supplies coverage only.

`hl_dispatch_table()` also recognizes a verified indexed-call helper that
saves HL/DE/BC, doubles A in an eight-bit register, loads a table pointer,
pushes its own restoring trampoline, and jumps through HL. Both CALL and tail
JP setup are supported; bounded JP aliases must resolve to the same verified
helper. The restoring return is a separate executable root. The eight-bit
index bounds the table to 128 pointers; changed helpers, unknown mappings,
and instructions that overwrite HL are rejected. For this helper, scanning
stops before a forward code target in the table's physical ROM bank, avoiding
misreading adjacent function bytes as more pointers into padding. This is
candidate discovery, not proof that every accepted entry is reachable.
Reports separate `indexed_call_targets`, `indexed_call_returns` and
`indexed_call_tables`, including entry limits and stop reasons. Legacy table
recognizers keep their existing scan rules.

`bank_analysis.py` adds a limited bank-effect proof. Starting after a constant
mapper write, `fixed_bank_context_targets()` follows fixed-ROM control flow for
up to 128 distinct states. `leaf_preserves_rom_bank()` checks both branch
outcomes of a leaf routine, tracking constant HL for safe RAM stores. Unknown
stores, nested calls, computed jumps and exhausted budgets reject the proof.
Only a proven leaf return permits unconditional context propagation to the
next call. This improves consecutive banked calls without assuming that an
arbitrary callee preserves mapping. Candidates are reported as
`bank_context_targets`; these are coverage facts, not changes to live dispatch.

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

After discovery and idle-loop annotations, `emit_native_blocks()` emits the
native assembly from block metadata. Tests can re-emit identical coverage to
compare code-generation policies without repeating reference execution. Normal
CLI/GUI compilation still runs discovery; there is no unchecked trace-cache
option exposed to users.

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

The dispatcher now uses a bank/page pointer lookup when its estimated table
size plus 96 bytes is smaller than 24 bytes per block; sparse programs retain
the original tree. Each populated 256-byte PC page holds 256 native pointers.
Holes share diagnostic pages, and a bank bound check protects the root lookup.
The entry name remains `gb_dispatch_tree` for runtime ABI compatibility.
`emit_native_blocks(..., dispatch_format='tree'|'paged'|'auto')` supports
controlled backend tests; normal compilation uses auto. New codegen-report
fields identify the chosen format, allocated page count and table size.

`benchmark_dispatch.py` generates an entirely original call/return workload
with bounded unused entries and compares both formats over equal Genesis frame
counts. A 24,000-entry run measured 1.21608x simulated-cycle throughput. This
synthetic result does not establish a game FPS improvement.

Generated blocks publish their Game Boy T-cycle cost in `gb_step_cycles`.
Straight-line chains accumulate up to `SCHEDULER_BATCH_T_CYCLES` in 68000
register `d7`, then call `gb_tick` at a scheduling boundary. Timing-sensitive
I/O, delayed `EI`, HALT, branches, and possible interrupts force earlier
synchronization.

Targets with zero reference hits use a small edge stub feeding shared
`gb_chain_compact` code; normally traced targets retain inline fast stubs.
`emit_native_blocks(..., max_hot_chains=N)` can limit duplicated stubs to the
N most frequently traced targets, with bank/PC breaking ties deterministically.
Every translated instruction and dispatch entry remains present. The default
None retains the original layout; this API changes layout, not CPU semantics.
The compact edge passes expected PC/bank in d0/d1 and pushes the native entry
address on the 68000 stack. On a fast step, RTS enters that native block. On a
scheduling boundary, the helper saves expected PC/bank across `gb_tick`, checks
for HALT/interrupt/bank redirection, and either enters the native destination
or unwinds its temporary stack before general dispatch. d7 remains the cycle
accumulator. This shares generated code, not SM83 instruction interpretation.

`native-codegen-report.json` records compact/hot chain counts and the limit.
It also reports `block_catalog_included` and `block_catalog_bytes`. The catalog
at `gb_compiled_block_table` is an eight-byte-per-entry debug export; live
execution uses the separate tree/page dispatcher and direct chain labels.
The default emitter retains the catalog for existing debugging workflows.

If an assembled image exceeds the supported 4 MiB cartridge window, `build()`
first omits the duplicate catalog without removing code or altering dispatch.
The exported label and sentinel remain. Trace/build JSON still lists entries.
`--keep-rom-catalog` requires retaining the catalog, for external tools that
may consume it. If more space is required, the builder halves the duplicated
inline-stub quota, ranking hot targets by dynamic hits and bank/PC tie breaks.
Each retry preserves every executable entry and does not retrace the ROM.
`native_layout_attempts` records sizes, catalog presence and stub quotas.
If even the fully compact layout cannot fit, the build fails before writing
`recompiled.md`, preserving any previous ROM. Larger Genesis cartridge mapping
is not implemented. Original native callback fixtures test execution and ROM
data reads after catalog omission; mixed/all-compact IRQ/mapper tests cover
scheduler equivalence. Capacity fallback is not a speedup claim.

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
- `run_native_blastem()` observes Mooneye Fibonacci register signatures or an
  explicitly instrumented native diagnostic serial stream through BlastEm.
- `write_report()` produces JSON status counts and per-ROM details.

A ROM drawing a recognizable image or reaching a loop is not automatically a
PASS. Screenshot suites and broad instruction-boundary native differential
testing remain unfinished.

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

## Optional native serial test peer and writable code variants

`serial_test.SerialTestMemory` is an explicit diagnostic model, matching the
runner's established instantaneous receiver: a write to SC ($FF02) with bits
7 and 0 set captures SB and clears SC bit7 immediately. It does not implement
serial bit timing, link-cable behavior or serial interrupts. Normal tracing
continues using `gb_cpu.Memory`; diagnostic tracing selects the test subclass.

`build(..., test_serial=True)` / `--test-serial` defines `GB2MD_TEST_SERIAL`
for assembly. Only that build includes a matching native peer in `gb_write8`.
The native buffer is bounded to512 bytes at `$FFD000`, with a word count at
`$FFC600` and overflow flag at `$FFC602`. These regions are above cartridge
RAM and tile-dirty state and below the Genesis stack. Normal builds assemble
no observer instructions;14 timer/reg_f images rebuilt byte-identically with
the diagnostic option disabled. Both trace and build reports record the mode.
The GUI does not enable this test-only setting.

`compile_native()` automatically selects this instrumentation for recognized
Blargg serial fixtures. `run_native_blastem()` refuses uninstrumented builds,
reads the native count/buffer, validates bounds/overflow, and requires the
actual Passed/Failed message. Python PASS does not imply native PASS. Missing
blocks, emulator errors and observer failures take precedence; prefix output
is retained for missing-block investigations. Native failures now also make
the compatibility CLI return a nonzero exit code.

The same pass extends `emit_native_blocks()`'s finite byte-variant resolver
to WRAM and echo RAM, using their shared `gb_wram` storage and distinct logical
PCs. Each observed sequence is translated to a separate native body; runtime
byte comparisons select that body. Unknown sequences trap instead of decoding
new SM83 instructions. Uniform-opcode/length variants crossing a WRAM/echo
window now use sampled bus fetches (see below); mixed opcode/length boundary
variants are still rejected. This is finite specialization, not an interpreter or complete
support for arbitrary self-modifying code. Single observed variants and
unobserved RAM entry points remain coverage limitations.

## Constant-cycle native chain specialization (2026-11-11)

`emit_native_blocks(..., optimize_pure_chains=True)` first lowers each observed
instruction variant and collects the statically linked predecessors of each
chain target. A target qualifies only if it is selected as hot by the existing
quota and every linked predecessor has the same, fixed instruction cost.
An explicit register-only opcode classification and rejection of service calls
exclude memory/I/O access, mapper changes, EI/DI, control flow, HALT and STOP.
A mixed-cost or unsafe predecessor makes the target use the existing scheduler.
Cold targets continue using `gb_chain_compact` with the existing cost stores.

For an eligible edge, the source omits its `gb_step_cycles` RAM write. The
specialized target still checks `gb_force_tick` and `gb_ei_delay`, then compares
`d7` against `SCHEDULER_BATCH_T_CYCLES - cost`. The fast path adds the immediate
cost directly to `d7`. On a flush it first restores the exact cost to
`gb_step_cycles` and runs the original `gb_tick`/IRQ/bank/PC validation tail.
The existing 200-T-cycle boundary and its unsigned comparison are preserved;
there is no clock multiplier, larger batch, skipped instruction or interpreter.
The pending-cost RAM byte is authoritative again before any timing service.

`native-codegen-report.json` records `optimize_pure_chains`,
`constant_cycle_chain_targets` and `elided_cycle_stores`. Normal builds enable
the optimization, including builds launched by the unchanged GUI wrapper.
`build(..., optimize_pure_chains=False)` / `--no-chain-opt` restores the previous
scheduler for A/B comparisons. Capacity retries retain the selected mode and
may reduce specialization as their hot-stub quota decreases.

`benchmark_chains.py` creates three original ROMs and measures source T-cycles
per Genesis frame with the option off/on. It warms each run, checks missing-
block markers and PC/SP bounds, and keeps fixture, codegen and native logs in
its output directory. The reported ratios describe these workloads only;
they are not game FPS or a full-system bottleneck profile. Original native
regressions compare timer-read results, register/stack state, EI/IRQ/HALT and
mapper behavior with both modes. Existing timer and integration suites remain
required before accepting backend changes.

## Interrupt stack entry and cancellation (2026-11-11)

In `CPU._step_base`, accepting an interrupt clears IME, spends two idle
machine cycles, pushes the high return-PC byte, then selects and acknowledges
an enabled request using the current IF and IE. The low byte is pushed next;
a final machine cycle completes entry. Total cost is 20 T-cycles, with writes
at T12 and T16 in the reference bus model. If the upper stack write disables
all pending requests through IE, entry still consumes IME and the stack writes
but selects address $0000. A low-byte IE write happens after selection.

The native `gb_tick` follows the same sequence. `gb_irq_advance` advances the
existing peripheral scheduler in 12/4/4-T-cycle phases while preserving native
temporaries. `gb_irq_entry` at $FF0058 suppresses an extra IF/IE write-barrier
tick during those already charged writes; `gb_defer_irq` prevents recursive
arbitration. Both are cleared before execution resumes at the selected vector.
Previously the native stack push charged no source interrupt-entry cycles.
This correction does not change instruction budgets or introduce game rules.

`tests/test_irq_entry.py` builds original synthetic programs for normal entry,
upper-push cancellation, a late low-push IE change, and priority reselection.
Reference tests also assert the two bus-write times, SP, IME and pending IF.
Opt-in native tests independently compare recorded memory and diagnostic state.
The external Mooneye `interrupts/ie_push` fixture is a further compatibility
check; its binary is not bundled. This is not a claim that every IF edge,
DMA interaction or interrupt timing corner is cycle-exact.

## IF/IE write ordering barrier (2026-11-11)

Interrupt request IF ($FF0F) and enable IE ($FFFF) writes now use
`gb_irq_write_barrier()` from `gb_write8`. Previously, normal direct chaining
could execute additional source instructions before the batch reached its
200-T-cycle limit, even when the write made an interrupt immediately eligible.
This could save a later interrupt return PC or expose pre-interrupt register
values to the following instruction. Missing native error-report code could
then obscure the underlying execution difference.

The barrier commits pending cycles before changing the register while IRQ
service is deferred, restores the prior deferral state, clears the charged
instruction cost and sets `gb_force_tick`. At the opcode's normal completion
boundary, arbitration therefore uses the new IF/IE state before entering the
next instruction. It preserves d0-d6/a0-a1, including temporaries used by
multi-byte stack stores; the existing cycle accumulator is committed normally.
Normal timer/DMA write handling remains in its previous path.

Original fixtures independently reproduce request-write and enable-write
latency: Python stored5 at the first observation while native stored4, then
later5. Both now match, alongside disabled-IME, delayed-EI and a PUSH that
writes IE through stack wraparound. This is a general I/O ordering fix, not
a test-specific target seed. It does not establish every cycle-exact interrupt
entry/cancellation edge or arbitrary self-modifying RAM coverage.

When vasm reports its specific "maximum number of passes reached" layout
convergence error, `build()` retries the same generated assembly once with
`-no-opt`. This disables assembler instruction/size optimizations, not native
recompilation or trace coverage. The flag persists through capacity retries.
`assembler_options`, `assembler_retries` and each layout attempt record the
mode; successful normal builds keep the existing assembler defaults. Other
errors fail directly, and repeated convergence failure leaves any prior ROM
intact. Original mocked-error tests cover retry bounds, one discovery pass,
ordinary errors and preservation; the native chain A/B fixture exercises the
actual non-convergent layout and successful fallback.

## Optional GB clock speed HUD

`build(..., show_fps=True)` / `--show-fps` defines `GB2MD_SHOW_FPS`, installs
`gb_fps_vblank` at Genesis level6 vector `$78`, uploads an original17-glyph
font from `fps_overlay.font_assembly()`, then enables only the needed host
interrupt level after setup (`SR=$2500`). The optional assembly lives in
`fps_overlay_68000.s`; it does not implement or change Game Boy interrupts.
Normal builds keep the original vector table and masked host interrupts.

The handler acknowledges VDP status, counts host VBlanks at `$FF0060`, and
samples source-cycle progress every50 PAL or60 NTSC VBlanks, selected from the
Genesis version register. The modular32-bit cycle difference survives counter
wrap. Dividing by4 and then17,556 converts to nominal GB frames; scaling by10
produces truncated tenths, saturated at9999. `fps_overlay.rate_tenths()` is the
reference for the same arithmetic. The value at `$FF006C` represents GB clock
progress per nominal hardware second, not rendered-image frequency or host
wall time during fast-forward. The sample count is at `$FF0070`.

The ISR saves d0-d4/a0 and returns with RTE, preserving the interrupted native
instruction's state and condition codes. Renderer hooks hold `$FF006E` busy
through its complete VDP transaction. While busy the ISR samples but defers
HUD writes; control commands remain complete32-bit instructions. Unimplemented
status-screen setup also holds the guard. Missing-block loops have no VDP
transaction, allowing the independent sampler to display0.0 after source time
stops. A paused or waiting source program may still advance its clock.

The HUD uses Plane B cells(1,1)..(12,1), above the game viewport, font tiles
644..660 (after source patterns and shell tiles), and shell palette entry15.
It updates the12 tile names only when a new sample is ready; glyphs upload once
at startup. Its RAM fields occupy `$FF0060..$FF0073`, outside GB-visible state
and serial-test buffers. It is off by default and exposed by the GUI checkbox.
Disabled-mode binary parity is checked against a prior verified fixture;
forced PAL/NTSC and trapped-source tests validate enabled-mode timing.

## Native variant fetches across memory windows (2026-11-12)

An instruction can start in WRAM or its echo and fetch an operand from the
next logical region. The previous variant guard compared bytes through one
backing-array pointer, so it rejected such instructions to avoid reading past
that array. `emit_native_blocks` now permits boundary variants sharing the
same opcode and length. Other cross-window patterns still fail explicitly.

For these guards only, `gb_fetch_read8` advances one four-T-cycle bus fetch
and uses `gb_read8` for each logical address. Thus echo wrapping and OAM DMA
accessibility are checked at each fetch, including when DMA finishes between
operand bytes. Three sampled bytes at `gb_fetch_bytes` ($FF0059–$FF005B) select
only previously translated native bodies. An unseen sequence still traps.
No new source opcode is interpreted or compiled at runtime.

The emitter marks these copies with `bus_fetch_cycles`; their native body
charges only the remaining instruction cycles. Taken conditional costs also
subtract the fetched prefix, and these edges are excluded from constant-cost
specialization. `gb_force_tick` ensures end-of-instruction arbitration; fetch
phases defer interrupts and preserve the previous deferral state. Existing
non-boundary guards and the Python CPU are unchanged. This does not implement
all instruction bus phases, mixed-length boundary code or arbitrary unseen RAM
code. Original regressions cover echo wrapping, OAM operands, conditional cost
emission and unseen-byte traps.

## Timed native stack reads (2026-11-12)

`native_body`'s `pop_word(prefix=8)` is shared by POP, RET and RETI; taken
conditional RET uses prefix12. Stack words with SP in $FDFF–$FF7F can touch
OAM or I/O. Their emitted address guard calls `gb_pop16_timed` instead of
sampling both bytes after the complete instruction cost. The lower byte is
read at T8 (T12 for taken RET cc), the higher byte four T-cycles later. POP
has no remaining cycles; returns leave their final4T for normal dispatch.

The helper uses `gb_tick` to advance existing timer, DMA and PPU state,
defers interrupt arbitration across both reads, preserves the low byte across
peripheral work, restores the previous deferral state and requests a boundary
tick. Return code installs the fetched PC before that final arbitration, and
RETI still enables IME at its existing instruction-end point. SP advances by
two; POP AF retains its existing lower-flag-bit mask.

Other stack addresses retain the prior inline reads, with an added address
comparison/branch. Host overhead has not been benchmarked, so this is a timing
correctness change rather than a speed claim. The Python CPU and timer/DMA/PPU
algorithms are unchanged. `tests/test_stack_read_timing.py` generates original
DIV-boundary programs for both bytes and POP/RET/RETI/taken/untaken returns;
reference cases also cover WRAM and SP wraparound. Actual native observations
compare their result memory to Python and require zero diagnostic markers.

This does not correct stack-write bus phases or arbitrary instruction fetch
patterns. The independent timing specification for POP is documented in
[Mooneye's POP timing test](https://github.com/Gekkio/mooneye-test-suite/blob/main/acceptance/pop_timing.s); no suite source or ROM is copied into these fixtures.

## Timed native stack writes (2026-11-12)

`native_body`'s `push_word` serves PUSH, PUSH AF, CALL, conditional CALL and
RST. It computes the low destination `(SP-2)&$FFFF` before selecting a path.
Words touching OAM/I/O (low destination $FDFF–$FF7F) or IE ($FFFE/$FFFF)
use `gb_push16_timed`. Other words retain the original inline stores, with
an added comparison/branch; host-speed overhead has not been measured.

The helper charges the remaining instruction cost minus4T, decrements SP and
writes the upper byte, then advances4T, decrements SP and writes the lower
byte. Already sampled cross-window fetch costs are therefore not charged
twice. The complete payload stays on the native host stack: OAM/I/O handlers
may call `gb_tick` and clobber native d3/d4. The previous inline path kept a
low address in d4 across that call and could lose the second store.

`gb_bus_write_charged` ($FF005C) marks each precharged write. OAM/timer/IF/IE
barriers skip a redundant scheduler call for this marker or the existing
interrupt-entry marker. A zero-cycle retick could clear the TIMA reload-cycle
flag and wrongly accept a write that should be ignored. An original reload-
edge diagnostic reproduces reference$FF versus native$A6 without this gate.
The marker is cleared after each write and checked by native regressions.

IRQ arbitration remains deferred through both bytes; the prior deferral state
is restored and the completed instruction requests a normal boundary tick.
CALL/RST code installs its target PC before arbitration. The helper preserves
native temporaries, clears the charged instruction cost and uses the existing
mapper, timer, DMA and I/O handlers. Their algorithms and the reference CPU
are unchanged. The interrupt-entry push retains its separate existing path.

Original diagnostics in `tests/test_stack_write_timing.py` make a high-byte
DIV reset observable four cycles before the lower write, and check OAM/echo
boundaries, AF data, taken/untaken calls and IE wraparound. ROM code is generated
from original source. These changes do not establish full CPU bus/DMA
restrictions or general PPU accuracy. Independent timing references are
[Mooneye PUSH](https://github.com/Gekkio/mooneye-test-suite/blob/main/acceptance/push_timing.s)
and [CALL](https://github.com/Gekkio/mooneye-test-suite/blob/main/acceptance/call_timing2.s).

## Event-aware native interrupt batches (2026-11-15)

Native chain stubs retain their existing200T cap and constant incoming-cost
checks. `gb_refresh_batch_bias` shortens that cap near an enabled interrupt
event without adding per-instruction memory checks. When IME and IE permit
interrupts, it calculates the next modeled timer reload, VBlank edge or STAT
mode/line edge, clamped to200T. A pending enabled IF bit has distance0.

`gb_batch_bias` at$FF005E stores virtual credit `200-distance`. After a tick,
d7 starts at this credit; chaining adds the costs of completed instructions
as before. The unchanged200T comparisons therefore flush the instruction
that reaches the event. `gb_tick` subtracts the credit before updating any
clock and resets it before nested peripheral/IRQ phases. Its real input is:

```text
gb_step_cycles + d7 - gb_batch_bias + gb_cycle_batch
```

The credit is never Game Boy time. It does not change CPU instruction costs
or multiply the source clock. Explicit HALT paths that replace d7 with real
idle cycles clear the credit first. Renderer register saves preserve d7.
Interrupt-disabled work skips deadline calculation and keeps normal batching.

Timer distance uses an existing pending reload countdown, or the next selected
divider falling edge plus remaining TIMA increments and four reload cycles.
Only LY143 can reach VBlank within200T; STAT conservatively stops at the next
mode/line boundary under the existing fixed-length PPU model. This is not a
new PPU model, serial controller, or full bus-accurate peripheral scheduler.
ROM-backed IME0 HALT fetch suppression is implemented; writable-code fetch
contexts and other hardware edge cases remain incomplete.

Previously a timer/VBlank request could remain unprocessed in a straight-line
batch while a later DI disabled IME. Flushing only on entry to DI would still
save the wrong return PC when the event preceded a final NOP. Original fixtures
in `tests/test_irq_batch_deadline.py` compare IRQ outcome, exact saved PC, IF
and a DIV sample with Python across neighboring alignments. Native default,
compact and unoptimized paths are tested. The DI and second HALT-timing ROMs
also pass with exactly the same discovered source entries/variants as before.
No additional trace steps, test-specific addresses or interpreter were added.

## Guarded pure-register runs (2026-11-15)

`emit_native_blocks()` can duplicate short, frequently traced ROM sequences
into `gb_fused_*` native regions. Each region contains three to eight register
instructions from one cartridge window. It excludes memory accesses, helper
calls, dynamic opcode variants, CPU control, and bank-window crossings. Every
original instruction entry and body remains available for branches, returns,
interrupts and the slow path; this pass discovers no new source code.

One entry guard checks `gb_force_tick`, `gb_ei_delay`, and whether biased `d7`
plus the complete region cost is strictly below the 200T boundary. Equality
falls back to the original per-instruction code. Because `gb_batch_bias`
already incorporates the next enabled interrupt event, a successful guard
cannot skip an interrupt-service boundary. The fast path emits the existing
arithmetic and **all** flag updates, adds the exact summed source cycles once,
and enters the ordinary successor. It caches no guest registers and introduces
no new runtime state, clock multiplier or peripheral behavior.

Candidate selection is deterministic, ranked by trace hits and the number of
chains eliminated. Regions do not overlap. The default ceiling is 128 regions
and a conservative 32 KiB added-code estimate. Reducing the hot-stub quota
during cartridge-size retries also reduces eligible starts; zero hot stubs
disables fusion. Capacity retries preserve the configured region limit,
including an explicit zero. `max_fused_regions=0` disables only this pass for backend A/B
tests. `optimize_pure_chains=False` / `--no-chain-opt` disables both this pass
and constant-cycle chain specialization. GUI builds use the sibling compiler's
default after recompilation; existing binaries do not change.

`native-codegen-report.json` records `fused_register_regions`,
`fused_register_instructions`, `fused_register_estimated_bytes`, the region
limit, and each selected run's PCs, successor and T-cycle sum. Original
regression fixtures in `tests/test_register_fusion.py` check safety exclusions,
retained entries, capacity limits, and native on/off register/flag, clock-sample
and interrupt-return equivalence. Performance results must identify their
workload: an improvement in a register loop does not establish game speed.

## Native read-modify-write bus phases (2026-11-15)

`native_body` routes INC/DEC(HL) and modifying CB(HL) operations through
`gb_rmw_read8` and `gb_rmw_write8`. BIT(HL) stays on the ordinary read-only
12T path. The arithmetic, flags, rotations and bit operations remain statically
emitted68000 statements; these helpers only sequence memory/peripheral time.

OAM/I/O/IE operands read one M-cycle before the final write. The read helper
charges the remaining opcode cost minus4T while deferring IRQ service, reads
through the existing logical map, then leaves4T for the write helper. The
write advances that phase before the store and uses `gb_bus_write_charged`
to avoid redundant synchronization that could erase a TIMA reload window.
Interrupt arbitration occurs after the complete opcode, with final flags/data.

Plain RAM/HRAM/ROM operands retain existing batching through guarded helper
paths. A phased read leaves exactly4T; all unphased modifying opcodes have at
least8T remaining, including CB instructions whose two fetch bytes have been
sampled by a cross-window guard. This is the helper-pair contract; it does not
decode source opcodes at runtime or add another persistent state byte.

An original TIMA-boundary fixture distinguishes reading$FF before overflow
from reading$00 afterward, and checks writes on the subsequent reload cycle.
It reproduces wrong INC/DEC and CB data/flags while a BIT control matches.
`tests/test_rmw_bus_timing.py` covers modifying families, reload windows, plain
WRAM, OAM and IE. The reference CPU and peripheral algorithms are unchanged.
This does not fix every memory/bus interaction, including broader CPU access
restrictions and ordinary-memory writes racing DMA; full PPU timing is open.

## Constant HRAM load/store lowering (2026-11-15)

`native_body(block, optimize_hram=True)` lowers the four constant-address
loads/stores (`LDH (a8),A`, `LDH A,(a8)`, `LD (a16),A`, `LD A,(a16)`) directly
when their address lies in `$FF80..$FFFE`. For example, `F0 80` becomes
`move.b gb_hram+$00,gb_a`. A store also emits the same
`addq.l #1,gb_write_count` as the generic write service. The actual Game Boy
HRAM storage remains shared with indirect accesses and code-variant guards.

This removes host address classification and a service call, without changing
source instruction costs, flags, polling analysis, interrupt handling or DMA.
The generic HRAM handlers do not synchronize peripherals, so there is no lost
timing barrier. These instructions remain classified as memory operations:
removing their helper call does not make them eligible for register fusion.
IE at `$FFFF`, I/O below `$FF80`, other memory windows and all indirect
addresses retain their original handlers. HRAM remains accessible during DMA.
This pass does not fix existing ordinary-memory DMA races or bus restrictions.

`emit_native_blocks()` and `build()` accept the independent `optimize_hram`
keyword. `--no-hram-opt` selects the generic path; `--no-chain-opt` controls
register chains separately. Capacity retries carry both selections. The GUI's
**Faster high RAM access** checkbox forwards the disabled mode through
`compiler_command()`; restart and recompile after updating. Reports record
`optimize_hram` and `direct_hram_sites` (instruction-variant sites, not unique
addresses). Old output images do not update automatically.

`tests/test_hram_lowering.py` uses original programs for byte-range boundaries,
flags, clock samples, stack preservation, write counts, DMA-time HRAM access,
mutable immediates and a mutable HRAM load address. Existing observed-byte
variant checks choose the correct specialized native body; unknown variants
still trap. `benchmark_hram.py` generates original read/write/absolute and I/O
control loops, confirms identical discovered coverage in both modes, and
compares source-cycle throughput over equal Genesis-frame intervals. Its
numbers are synthetic workload measurements, not game-speed guarantees.

## Native scheduler bookkeeping (2026-11-15)

Profiling uses BlastEm's emulated clock at helper entry/return, rather than
its display FPS or host wall time. On one Tetris falling-piece route,
`gb_render_frame` occupied about 2.1% of the sampled interval (no background
refreshes), while `gb_tick` occupied 32.4%, including its callees. Separate
samples of nested `gb_stat_sync` and `gb_refresh_batch_bias` were about 6%
each. These nested measurements must not be added together, and this route
does not represent every game, line clearing, scrolling or video playback.
Compact shared chains were rare in this sample; changing their layout was
not justified by the measurements.

`gb_stat_sync` now needs D0/D1 instead of D0–D3. It still updates mode and
LY/LYC coincidence on every call, even with STAT interrupts disabled. With no
STAT interrupt source enabled, it sets the combined line low directly, while
preserving any pending IF request. Enabled-source paths retain the same
OR-line rising-edge behavior. This changes bookkeeping cost, not PPU timing.

`gb_refresh_batch_bias` avoids its general calculation only when raw IE is
exactly 1, VBlank IF is clear, and LY is not 143. In that configuration there
is no enabled event within the existing 200-T-cycle cap, so the correct
credit is zero. LY143 and pending VBlank still use the general path. Other
interrupt configurations retain the old deadline calculation, with six
registers saved instead of nine; the other three registers are untouched.
No cache, clock multiplier, new runtime state or game-specific rule is used.

`tests/test_scheduler_bookkeeping.py` checks 7,680 STAT state vectors against
`Memory._update_stat` and 2,460 capped deadline vectors, including LY143
boundaries, mixed interrupt masks, timer reloads and upper-D7 preservation.
Its native harness checks state and register contracts against both helpers.
The prior runtime and the optimized runtime both pass these matrices.

`benchmark_scheduler.py` generates original register loops with masked,
VBlank-only and mixed interrupts. Supply an earlier `runtime_68000.s` through
`--reference-runtime`; both builds use identical current lowering and their
coverage must match. External vasm and BlastEm are required. The JSON records
runtime hashes and source-cycle progress over fixed Genesis-frame intervals.
A throughput ratio describes these synthetic loops, not commercial-game FPS.

## Optional coverage imports (2026-11-16)

`compile_trace(..., coverage_profiles=...)` validates imports with
`coverage_profiles.load_coverage_profiles` before executing a new trace.
`merge_coverage_profiles` combines instruction identities and observed byte
variants before ordinary static closure and native lowering. No source CPU,
peripheral, mapper or Genesis runtime behavior is replaced.

A profile must carry `source_sha256`, matching the entire input cartridge.
Every imported ROM instruction/variant must match bytes in the stated physical
bank. Fixed-window identities use bank zero; upper-window bank zero requires
MBC5. Crossing a ROM window, malformed lengths, duplicate identities and invalid
RAM locations are rejected. Parsing limits are 16 profiles, 128 MiB per file,
one million entries and 256 alternate variants per entry. The loader reads JSON data;
it does not deserialize Python objects or restore emulator state.

RAM instruction bytes are trusted local observations, not proven by the ROM
digest. Their existing native guard compares live memory before execution;
an unobserved variant still traps. Unknown fixed-ROM active-bank contexts are
not invented from imported identities. Importing a profile does not reproduce
its complete dynamic execution context or prove future coverage.

`total_steps_executed` counts only current tracing. The report separately
records `fresh_dynamic_unique_block_count` and `coverage_imports` (entries,
observed entries and newly contributed identities). Imported zero-hit static
candidates are not reported as dynamic execution. Existing hit weights guide
layout but do not become hardcoded inputs or runtime decisions. The build API
and CLI expose the optional feature; the GUI continues to run fresh tracing.

## Branch-separated bank calls and inline BC callbacks (2026-11-16)

`_constant_far_setup` follows a bounded path that assigns B (bank) and HL
(target), allowing NOP and unconditional JR/JP between assignments. It stops
at a candidate CALL/JP after both constants are known. Conditional paths,
unknown effects, cycles, ROM-window crossings and limits (16 instructions,
128-byte span) fail closed. `constant_far_call_targets` still verifies the
entire existing bank-save/select/call/restore trampoline before adding roots.
This recognizes shared argument-setup blocks without assuming a bank change
from an arbitrary call or replacing any source instructions.

`inline_bc_call_table` recognizes an explicit zero high index byte, a ROM
word lookup through BC into HL, then a short sequence of HL/bank-preserving
argument loads and an explicit PUSH/JP synthetic call. Its literal return
must point immediately after the jump to a recognized return epilogue. It
adds bounded aligned pointer candidates and the return entry through normal
closure; it does not infer every possible unknown byte offset. Table bounds,
physical bank mapping, a minimum of two pointers, a 128-entry cap and the
forward-code boundary constrain scanning. Actual execution still runs the
original index arithmetic, lookup, stack operations and selected callback.
Trace/build reports expose `inline_bc_call_targets`, `inline_bc_call_returns`
and `inline_bc_call_tables` separately.

## Capacity fallback for dispatch tables (2026-11-16)

Ordinary fitting images retain the existing 32-bit bank/page/leaf tables.
If a paged image exceeds 4 MiB, `build` first omits the unused duplicate block
catalog when permitted, then tries `emit_native_blocks(dispatch_format="packed")`
before reducing inline scheduler quotas. Later retries retain the selected
format and optimization settings. Every executable block and diagnostic hole
is retained; the final 4 MiB cartridge limit is still enforced.

Only leaf pointers shrink from four bytes to three. Bank and page directories
remain aligned 32-bit pointers. Leaf slot `PC & 255` is multiplied by three;
three byte reads assemble a zero-extended 24-bit native address. Word/long
reads at these slots would bus-error on odd addresses on a real 68000. The
lookup uses scratch D0/D1/A0 and leaves the scheduler's D7 untouched. The
builder's image limit ensures native pointers fit in 24 bits.

The format costs extra pointer-unpacking work, so it is a capacity fallback,
not a universal speed optimization. Saving 256 bytes per populated leaf page
plus the empty page can also preserve more fast inline scheduler entries.
Reports identify `bank_page_table_24`, `dispatch_leaf_entry_bytes=3`, exact
metadata bytes and the format of every layout attempt. Explicit `paged` and
`packed` emitter options permit controlled testing. Original native tests
exercise addresses above 0x123456, odd slots, page boundaries, missing entries,
IRQ flow, mapper changes and MBC5 bank zero. A preserved-coverage Tetris rebuild
remains byte-identical to its prior normal-table checkpoint.


## Bounded packed dispatch pages (2026-11-16)

`emit_native_blocks(..., dispatch_format="trimmed")` adds a capacity-only layout
for images that cannot fit with full packed leaves. `build` tries it after the
packed fallback and before reducing fast scheduler quotas, when the estimated
table data would shrink. Fitting images keep their existing output format.
Later quota and assembler-convergence retries retain the chosen layout and
optimization settings in `build`. Assembler retries reuse the generated assembly.

Each page directory still contains an aligned 32-bit native pointer. Its leaf
begins with two bytes: the lowest populated `PC & 255` slot and the inclusive
span to the highest slot. A singleton has span 0; a full 256-slot page has
span 255. Lookup subtracts the first slot, traps on unsigned underflow, and
traps if the resulting index exceeds the span. Remaining internal holes still
contain `gb_missing_block` pointers. It then performs the same three byte reads
as the packed format. The shared empty leaf also traps for every possible PC.

The two-byte header and byte-wise pointer reads permit odd packed entries;
each leaf ends with `even` so following directories/labels remain aligned.
Only scratch D0/D1/A0 are used; scheduler D7 is preserved. All generated bodies,
guarded RAM variants, bank normalization and interrupt/scheduler semantics
remain unchanged. Removing unused table slots is not removing source code or
proving that undiscovered paths are covered.

Reports call this `bank_page_table_24_trimmed`. `dispatch_table_bytes` measures
the selected layout including per-leaf alignment; `dispatch_trimmed_table_bytes`
provides the candidate size before retrying. These are table data sizes, not
the whole image or a throughput benchmark. Extra bounds checks cost work on
indirect dispatch, while smaller metadata can retain more fast chain entries.
The builder still enforces 4 MiB and fails rather than dropping required code.

Original fixtures in `tests/test_trimmed_dispatch.py` cover singleton/full-page
spans and exact aligned byte accounting, plus native low/high out-of-range
PCs, internal holes, high native addresses, odd slots, page boundaries,
missing banks, interrupts and MBC5 bank zero. The existing capacity retry test
also checks format/option retention and the ordering before quota reduction.


## Byte-offset lookup order and bank-window directories (2026-11-17)

`hl_dispatch_table` now recognizes the exact suffix
`LD B,0 / LD C,A / ADD HL,BC / LD A,(HL+) / LD H,(HL) / LD L,A / JP (HL)`
after `LD HL,table`. The caller may have doubled A before loading HL; it may
also supply an already prepared byte offset. The static analyzer therefore
finds this table without requiring multiplication at a particular location.
It does not rewrite the source arithmetic or replace the live lookup.

The `table_only` diagnostic distinguishes this jump from a synthetic-return
callback. `compile_trace` scans at most 128 aligned word candidates, requires
at least two valid pointers, retains the physical bank, and stops before the
first known forward code target. Unknown mappings, ROM-window boundaries and
invalid pointers terminate the scan. Aligned candidates do not establish all
possible odd-offset destinations. New `inline_byte_offset_tables` records
identify these static discoveries separately from current dynamic execution.
No fake call return is inferred from this form.

The extra discovered code can increase cartridge size. An optional automatic
capacity layout, `emit_native_blocks(dispatch_format="windowed")`, preserves
the bounded packed leaves but shrinks page directories for nonzero execution
banks from 256 to 64 pointers. This follows the existing `gb_normalize_bank`
contract: nonzero identities can only have PC in $4000–$7FFF. Lookup subtracts
0x40 from the page index in that case. Bank zero keeps all 256 pointers,
including MBC5 upper bank zero and ordinary fixed-ROM/RAM-code pages. The
shared empty bank retains its full directory, so missing identities still trap.
Malformed noncanonical identities fail with an error rather than losing code.

`build` tries this after bounded leaves and before reducing scheduler quotas.
Later layout retries preserve `bank_page_table_24_windowed` and optimization
options; assembler convergence retries reuse the generated assembly. Fitting
older layouts are unchanged. `dispatch_windowed_table_bytes` reports the
candidate metadata size, and `dispatch_table_bytes` reports the selected one.
The new lookup still uses scratch D0/D1/A0 only; scheduler D7, CPU/peripheral
semantics and every compiled entry remain intact. Extra lookup instructions
and different retained quotas mean this is not a universal speed guarantee.

Original fixtures in `tests/test_prescaled_tables.py` exercise index ordering,
byte offsets, wraparound, physical banks, changed opcodes, scan boundaries and
native execution. `tests/test_windowed_dispatch.py` covers exact directory
savings, capacity retry options, noncanonical identities, highest upper-window
pages, MBC5 bank zero, IRQs, odd/high addresses and missing-entry diagnostics.


## Tagged callback records and compact bank arguments

`tagged_callback_table()` recognizes a bounded DE-based search over three-byte
records: tag, target low byte, target high byte. It requires the actual
comparison and stride-three loop, the matching script-byte conditional branch,
and a callback path that saves HL, reads the ROM pointer, pushes a literal
return address and jumps through HL. The literal return must restore HL and
branch back to a script fetch. All addresses are decoded operands. No title,
ROM hash or game address selects the analysis. Unknown upper-bank context,
changed search/stack operations, duplicate tags and invalid pointers fail
closed. Candidates stop at the compared sentinel, a forward code boundary,
ROM window/file boundary or the configurable analysis entry cap (default128).
At least two records are needed. This narrowly recognized idiom is coverage
analysis; it is not a proof of all indirect control flow or odd record layouts.

`compile_trace()` merges the callback and synthetic return roots into normal
static closure, reporting `tagged_callback_tables`, `tagged_callback_targets`
and `tagged_callback_returns`. Original lookup instructions still execute in
the native ROM. An unrecognized computed target continues to trap.

`emit_native_blocks(compact_bank_immediates=True)` can encode bank arguments
0..127 in compact scheduler stubs using two-byte `MOVEQ` instead of four-byte
`MOVE.W`. D1 is scratch and the shared scheduler consumes the low bank word;
128 and larger retain the original word encoding to avoid sign extension.
The builder enables this only as a capacity retry for images exceeding4MiB,
after available table layouts and before halving hot-stub quotas. Reports
record the option and byte savings; retries retain the setting. Ordinary
fitting builds keep their previous assembly. No shared scheduler, clocks or
peripheral implementation changes are needed.


## GBMicrotest observation and broad collection reports

`run_compat_tests.protocol_for()` selects `gbmicro_hram` for this test suite.
`gbmicro_result()` accepts only the documented FF82 flag:1 for PASS,255 for
FAIL; FF80/FF81 are diagnostics and can agree on a failing test. Both reference
and native observation require `GBMICRO_OBSERVE_CYCLES` (24 times70224 source
T-cycles) before accepting a result, covering the documented delayed IF test.
The reference idle-loop detector waits for that floor. Native observation reads
the mapped HRAM flag and source-clock counter, prioritizing missing-block
traps. Host acceleration never replaces this emulated-clock requirement.
Unsupported visual/audio protocols remain NOT_RUN. Broader collection results
are summarized in TEST_ROM_RESULTS.md; per-ROM raw reports and binaries stay
private. Memory.__init__ now starts BGP atFC, matching the already established
native initialization. This does not complete all DMG boot-state behavior.


## HALT fetch contexts (2026-11-20)

When IME is clear and an enabled interrupt is already pending at HALT entry,
the following opcode fetch suppresses one PC increment. This changes immediate
operands and instruction boundaries as well as single-byte instruction behavior.
`halt_fetch_probe.make_rom()` and `reference()` provide original minimal examples.

`compile_trace()` keeps the ordinary ROM instruction canonical and records
separate `halt_fetch_bytes`/`halt_fetch_hits` metadata. `add_halt_fetch()` closes
the direct successors using the shortened PC advance. `coverage_profiles.py`
validates both cartridge bytes and the exact duplicated-opcode encoding before
merging profiles. The ordinary block identity remains `(bank, PC)`; alternate
fetch semantics use separate native entries, not self-modifying ROM variants.

`native_body()` uses a one-byte-shorter next PC for those entries, including
relative branches and pushed CALL/RST return addresses. `emit_native_blocks()`
emits a sparse `gb_halt_dispatch_tree`. Ordinary native dispatch and chains
have no new fetch-context check. This remains native 68000 code, not an SM83
interpreter.

`gb_halt_enter` first flushes preceding accumulated source cycles with IRQ
service and EI advancement deferred. It then samples IE/IF at HALT entry.
`gb_halt_dispatch` selects ordinary or suppressed-fetch dispatch exactly once.
For EI/HALT with a pending IRQ, reference `CPU._step_base()` and native IRQ
entry correct the pushed return PC back to HALT and clear the latch; the IRQ
handler's first instruction has an ordinary fetch.

Unsupported suppressed fetch in writable code produces an explicit trace error
or native trap. Missing alternate entries set `gb_missing_fetch_context`
($FF0081) before the existing missing-block trap; the compatibility runner
reports `missing_native_fetch_context`. Mixed-window multi-byte suppressed
fetches are also unsupported. These are limitations, not ordinary block misses.

`tests/test_halt_context.py` covers canonical profile round trips, metadata
rejection, exposed successors, relative branches, calls, RST, CB instructions,
mixed normal/bugged execution at one PC, EI/HALT, timer-boundary phases and ROM
bank/window contexts. Native checks compare register/WRAM and DIV/TIMA results.
The existing timer/peripheral models otherwise remain unchanged.

A separate production-reference failure was isolated in SameSuite's EI/HALT ROM:
VBlank can be requested while LCD is disabled. A private diagnostic gate isolates
that PPU issue; the gate itself was not a production or native PASS. The
2026-11-22 correction below subsequently fixes the request and validates the
ROM in both backends. Coordinated LCD timing/startup work remains necessary.

## LCD-off VBlank generation (2026-11-22)

[Pan Docs LCDC](https://github.com/gbdev/pandocs/blob/master/src/LCDC.md) describes
LCDC.7 as the LCD/PPU enable, and its
[interrupt documentation](https://github.com/gbdev/pandocs/blob/master/src/Interrupt_Sources.md)
identifies VBlank entry as the request source. Both backends previously requested
IF.0 at LY 144 before checking that enable. This could preempt a timer handler
while software deliberately kept the LCD disabled.

`Memory.tick()` now requests IF.0 at each enabled VBlank boundary visited by its
existing event loop. This also fixes large tick calls that cross the boundary
but end on another scanline. `gb_tick` tests LCDC.7 before setting IF.0 in its
scanline loop. Existing accelerated VBlank/LY waits already require LCD enable.
The correction does not clear pending IF bits or pause the source CPU clock,
DIV/TIMA or DMA. `gb_stat_sync`/`Memory._update_stat` retain their existing
rising-edge logic and disabled-LCD STAT suppression.

`tests/test_lcd_vblank.py` creates original programs and checks LCD off, retained
requests, enabled VBlank, toggles, and timers while disabled. Reference tests
also compare small/bulk advancement and acknowledge/reassert boundaries. Its
opt-in native method checks actual WRAM result flags and missing-block counters.
SameSuite's EI/HALT completion was additionally observed with an explicit
serial diagnostic peer on Python and Genesis, without editing the fixture or
injecting results.

This is a request-generation correction, not a complete LCD stop/restart model.
Reference LY still derives from the global source-cycle counter and native
scanline phase still advances while disabled. LY reset, LCD restart phase,
startup blanking and other post-boot register values require further coordinated
work. Reference LCDC now starts at $91, matching native startup and the documented
DMG post-boot state. Without that correction, removing false LCD-off VBlank
requests exposed four HALT tests waiting forever on the reference's initially
disabled LCD. This corrects the shared hardware startup state. Full PPU
compatibility is not established; LCD register-write boundary ordering also
needs further validation.

The post-boot LCDC value follows the
[hardware-register table](https://github.com/gbdev/pandocs/blob/master/src/Power_Up_Sequence.md#hardware-registers).
Original diagnostics observe $FF40 before writing it and verify $91 on both
backends. This does not claim complete boot-state accuracy (DIV/STAT and phase
alignment still need separate validation).

## Automatic background scanline renderer (2026-11-22)

`raster_68000.s` adds a native display path; source CPU execution remains
recompiled 68000 blocks. `gb_write8` arms it for changed SCX/SCY/BGP writes
while visible and with LCD on, sprites off and window off. `gb_tick` calls
`gb_raster_scanline` at its existing fixed transfer-end boundary (dot 252).
Capture waits for LY0 and checks contiguous lines, avoiding a partial first
frame. Direct idle shortcuts are guarded so they cannot bypass required raster
history. Existing hardware scheduling and normal block lowering are retained.

Each row fetches the live selected GB map, signed/unsigned pattern row and
fine SCX (including map wrap); BGP maps the source pixels to four final shades.
Two sparse palette caches eliminate repeated per-pixel palette extraction.
`gb_raster_select_palette` computes sixteen valid pixel-pair entries per miss;
all 256 BGP values, including replacements, are checked in a native helper
unit. `gb_raster.py` supplies the independent BG row oracle and diagnostic
fingerprints. It is a rendering oracle, not a replacement CPU interpreter.

VDP patterns $9000-$BCFF are separate from normal patterns, shell/HUD fonts and
maps at $C000 and above. `gb_raster_present` selects the composed viewport and
flat four-shade palette. `gb_raster_end_frame` returns a quiet scene to the
normal renderer; sprite/window scenes also retain that path. Source pattern
and map dirty flags remain set during raster presentation so a later normal
frame restores all changed graphics. The GUI needs no new command-line option.

Diagnostic state occupies native RAM $FF0082-$FF0095; $FFC700-$FFC93F holds
144 ordered output-row fingerprints and $FFC940-$FFCB3F holds two palette
caches. These do not overlap mapped source ERAM, serial-test output or FPS
state. Captured-line and raster-render counters describe work, not unique video
frames; actual changing captures are needed to establish animation.

Limits are explicit: fixed-length scanlines, BG-only composition, first-full-
frame activation latency, current register-write ordering, and visible front-
buffer updates (possible tearing). LCDC-only and VRAM-only raster effects do
not independently arm the path. Native rendering costs reduce throughput on
these workloads; ordinary static or sprite/window scenes retain the existing
renderer. Future work includes profiling, better buffering and wider raster
composition, without ROM-specific decoding or game patches.
