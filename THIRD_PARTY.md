# Third-party dependencies

The intended public GB2MD repository does not vendor these dependencies.

## vasm

GB2MD uses the external `vasmm68k_mot` assembler. The locally reviewed vasm
documentation states that its archive may be redistributed unmodified for
non-commercial purposes, includes a commercial-output exception, and warns
that individual modules can have additional copyrights. Obtain vasm from its
upstream and review its current terms yourself. GB2MD locates it through
`--assembler`, `GB2MD_VASM`, or `PATH`.

## PyQt5

The optional GUI imports PyQt5. Riverbank documents PyQt as dual-licensed
under GPLv3 and a commercial license:
https://en.riverbankcomputing.com/software/pyqt

PyQt5 is installed separately and is not included in this repository.

## BlastEm

BlastEm is an optional external test emulator distributed under GPLv3 or
later. Binary releases also contain components with their own licenses. Obtain
it separately from its upstream:
https://www.retrodev.com/blastem/

## Compatibility test suites

Blargg, Mooneye, dmg-acid2, and other test ROM suites have separate authors
and terms. No downloaded test ROM collection is included in the intended
public repository. Users who install test fixtures must review each suite's
license and attribution requirements.

## Platform documentation

GB2MD behavior was implemented using public hardware documentation, including
Pan Docs and Sega platform documentation. Hardware behavior, instruction-set
facts, register addresses, and interoperability interfaces are documented
facts; no third-party emulator source is intentionally included.
