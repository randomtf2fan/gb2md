# GB2MD publication audit

Audit date: 2026-10-31.

This is an engineering inventory, not legal advice or a guarantee against a
claim. It documents what the clean public tree is intended to contain.

## Included source

- Python compiler, trace explorer, reference CPU/memory/renderer, CLI, GUI,
  compatibility runner, and focused synthetic tests.
- Original Motorola 68000 runtime source.
- Architecture, compatibility, build, licensing, and dependency documentation.
- No binary ROM is required for the 56 focused unit/smoke tests.

## Excluded private/generated material

- All `.gb` and `.gbc` input ROMs.
- Downloaded `test_roms/` collections and reference images.
- All generated Mega Drive/Genesis ROMs, including files using `.md`.
- `build-*`, `gui-builds`, `compat-results`, and private `checkpoints`.
- Generated assembly, trace profiles, build reports, screenshots, logs,
  listings, PPMs, and binary VDP assets.
- Bundled/local vasm and BlastEm trees and binaries.
- Python caches, editor state, and virtual environments.

Generated native ROMs are excluded because `build_recompiled.py` embeds source
cartridge data for runtime banked reads. Generated assembly and screenshots can
also reflect commercial game content.

## Files reviewed

The review covered all root Python and assembly source, `tests/`, root project
documentation, generated build/checkpoint categories, downloaded test-suite
categories, the local vasm documentation, and the bundled BlastEm notices.
No explicit copied emulator-source notice was found in the GB2MD source, but
the project currently lacks authorship history sufficient to prove provenance
by itself. Contributors must not add code copied from third-party emulators
without compatible licensing and attribution.

## Changes made for publication

- Added path-specific ignore rules that distinguish Markdown from `.md` ROMs.
- Made vasm and BlastEm externally configurable instead of release-bundled.
- Removed Tetris-specific branding from newly generated ROM headers.
- Added GPLv3-or-later licensing scope, dependency notices, and trademark/
  non-affiliation language.
- Corrected compatibility documentation to identify Tetris v4, 56 focused
  tests, and the unresolved Super Mario Land native/Python divergence.

## Remaining risks and release checks

- Confirm every contributor agrees to GPLv3-or-later and has rights to their
  contributions.
- Audit any future Git history, not merely the working tree; `.gitignore` does
  not remove already committed objects.
- Do not attach commercial-ROM builds, checkpoints, screenshots, or trace
  output to releases, issues, or CI artifacts.
- Review each third-party test suite before distributing any fixture.
- Treat game compatibility claims as measured interoperability results, not as
  endorsement or complete compatibility guarantees.

## Clean-tree verification

The source-only release tree was verified without `test_roms/`, commercial
ROMs, checkpoints, bundled vasm, or bundled BlastEm:

- `python3 -m unittest discover -s tests -q`: 56 tests passed, zero skips.
- A newly generated 32 KiB original synthetic ROM compiled through the public
  `build_recompiled.py` using an explicitly supplied external vasm path.
- The resulting 512 KiB ROM contained 5/5 native blocks and no unlowered
  families. Its one-run SHA-256 was
  `8bf334c9fb16fd664310d2f34e11fd47c9652c836a66f841c36150af8aa795a2`.
- A file scan found no `.gb`, `.gbc`, `.gen`, `.smd`, `.rom`, binary `.md`,
  screenshots, logs, traces, listings, or bundled third-party executables in
  the release tree.
