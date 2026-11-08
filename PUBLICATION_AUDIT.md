# Publication check — 2026-11-08

Publication uses the separate cleaned checkout, not the development directory
or its history. This is a bounded release check, not a legal guarantee.

Reviewed changes: `.gitignore`, README, architecture/compatibility documentation,
`gb_cpu.py`, `gb_render.py`, `runtime_68000.s`, `trace_recompiler.py`,
`run_compat_tests.py`, `gb2md_gui.py`, and the three source test modules.
Existing LICENSE, NOTICE and THIRD_PARTY terms are retained. vasm, BlastEm,
PyQt5 and downloaded compatibility fixtures remain external dependencies.

Only source, documentation and tests are staged. Synthetic diagnostic ROMs
are generated from original test code; their binary outputs are not included.
No commercial ROMs, converted games, extracted assets, game-derived assembly,
private handoffs, checkpoints, screenshots, traces, credentials or tool binaries
are part of this update. The tracked-file scan checked binary/NUL content,
ROM signatures/extensions and common token/private-key patterns; history
filenames were checked for ROM/build artifacts. These checks are not a claim
of exhaustive credential detection or third-party provenance verification.

Validation: the initial update passed 84 focused tests; the controller
follow-up passes 86 unit tests and an opt-in native integration test. No
diagnostic binaries or emulator logs are published. The actual PyQt5
QProcess build compiled the original MBC3 RAM diagnostic using the sibling
compiler/runtime; temporary outputs stayed outside the checkout. Native
original diagnostics cover STAT polling, memory scanning, windows, RST
dispatch and bank switching. Current game limits and revision-specific timer
results are recorded in COMPATIBILITY.md. Broad final-revision gameplay/DMA/
timing regressions and Windows integration remain outstanding.

The GUI must be restarted after updating, and generated ROMs must be rebuilt.
Existing builds are preserved and are not silently upgraded by a source push.
