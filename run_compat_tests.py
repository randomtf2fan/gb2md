#!/usr/bin/env python3
"""Run immutable Game Boy compatibility ROMs against GB2MD's Python oracle.

The runner deliberately keeps Python and native-Genesis results separate.  A
ROM that passes the reference core is never reported as a native pass unless a
future native backend has actually observed the target protocol on Genesis.
"""
from __future__ import annotations

import argparse
from collections import Counter, deque
import hashlib
import json
import os
from pathlib import Path
import pty
import re
import select
import shutil
import subprocess
import sys
import time
from typing import Iterable

from gb2md import CARTRIDGES, cartridge_profile
from gb_cpu import CPU, Memory

STATUSES = ("PASS", "FAIL", "TIMEOUT", "UNSUPPORTED", "NOT_RUN")
ROM_SUFFIXES = {".gb", ".gbc"}
MOONEYE_PASS = (3, 5, 8, 13, 21, 34)
MOONEYE_FAIL = (0x42,) * 6


class ProtocolMemory(Memory):
    """Memory with an instantaneous external serial receiver.

    Compatibility ROMs commonly write a byte to SB ($FF01), then write $81 to
    SC ($FF02).  Recording that edge and clearing transfer-start models a link
    peer that completed immediately; no game input is injected.
    """

    def __init__(self, rom: bytes):
        super().__init__(rom)
        self.serial = bytearray()
        self.dma_writes = 0

    def write(self, address, value, bus_phase=0):
        super().write(address, value, bus_phase=bus_phase)
        if (address & 0xFFFF) == 0xFF46:
            self.dma_writes += 1
        if (address & 0xFFFF) == 0xFF02 and (value & 0x81) == 0x81:
            self.serial.append(self.io[0x01])
            self.io[0x02] = value & 0x7F


def discover_roms(root: Path, selections: Iterable[Path], suite: str | None):
    """Return immutable fixture paths in stable order."""
    candidates = []
    selected = list(selections)
    if not selected:
        selected = [root]
    for item in selected:
        path = item if item.is_absolute() else Path.cwd() / item
        if not path.exists() and not item.is_absolute():
            alternate = root / item
            if alternate.exists():
                path = alternate
        if path.is_file() and path.suffix.lower() in ROM_SUFFIXES:
            candidates.append(path)
        elif path.is_dir():
            candidates.extend(
                p for p in path.rglob("*")
                if p.is_file() and p.suffix.lower() in ROM_SUFFIXES
            )
    unique = sorted({p.resolve() for p in candidates}, key=lambda p: str(p).lower())
    if suite:
        needle = suite.lower()
        unique = [p for p in unique if needle in str(p).lower()]
    return unique


def suite_name(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).parts[0]
    except (ValueError, IndexError):
        return "external"


def protocol_for(path: Path) -> str:
    lower = "/".join(part.lower() for part in path.parts)
    if "/blargg/" in f"/{lower}/":
        if any(component in lower for component in ("/cpu_instrs/", "/instr_timing/", "/mem_timing/", "/mem_timing-2/")):
            return "blargg_serial"
        return "manual_visual"
    if "mooneye-test-suite-wilbertpol" in lower:
        return "mooneye_legacy_ed"
    if "mooneye-test-suite" in lower:
        if "/manual-only/" in f"/{lower}/":
            return "manual_visual"
        return "mooneye_fibonacci"
    if any(name in lower for name in ("dmg-acid2", "cgb-acid2", "cgb-acid-hell")):
        return "manual_visual"
    return "unknown"


def header_support(rom: bytes, path: Path):
    if len(rom) < 0x150:
        return False, "file is smaller than the Game Boy header"
    cgb_flag = rom[0x143]
    if cgb_flag == 0xC0:
        return False, "CGB-only execution is not implemented"
    if cgb_flag not in (0x00, 0x80):
        return False, f"unrecognized CGB flag ${cgb_flag:02X}"
    mapper = rom[0x147]
    if mapper not in CARTRIDGES:
        return False, f"unsupported cartridge type ${mapper:02X}"
    return True, ""


def model_support(path: Path):
    """Conservatively select tests applicable to the DMG-ABC target model."""
    name = path.stem.lower()
    if "mooneye" not in "/".join(part.lower() for part in path.parts):
        return True, ""
    # G and GS groups include DMG. Standalone S/C/A and explicit non-DMG
    # models do not. Initial-revision dmg0 behavior is intentionally separate.
    if "dmg0" in name:
        return False, "test targets the initial DMG SoC revision"
    if any(token in name for token in ("-sgb", "-sgb2", "-mgb")):
        return False, "test targets a non-DMG console model"
    if name.endswith(("-s", "-c", "-a")):
        return False, "test's model group does not include DMG"
    return True, ""


def cpu_registers(cpu: CPU):
    return {
        "A": cpu.a, "F": cpu.f, "B": cpu.b, "C": cpu.c,
        "D": cpu.d, "E": cpu.e, "H": cpu.h, "L": cpu.l,
        "SP": cpu.sp, "PC": cpu.pc,
    }


def terminal_mooneye(cpu: CPU, memory: ProtocolMemory, protocol: str):
    regs = (cpu.b, cpu.c, cpu.d, cpu.e, cpu.h, cpu.l)
    op = memory.read(cpu.pc)
    if protocol == "mooneye_legacy_ed" and op == 0xED:
        return "PASS" if regs == MOONEYE_PASS else "FAIL", "legacy undefined-opcode terminator"
    if protocol == "mooneye_fibonacci" and op == 0x40:
        # The terminal breakpoint is LD B,B followed by JR -2.  Requiring the
        # loop bytes prevents ordinary LD B,B instructions from being exits.
        if memory.read((cpu.pc + 1) & 0xFFFF) == 0x18 and memory.read((cpu.pc + 2) & 0xFFFF) == 0xFE:
            if regs == MOONEYE_PASS:
                return "PASS", "Fibonacci register signature"
            if regs == MOONEYE_FAIL:
                return "FAIL", "failure register signature ($42 x6)"
            return "FAIL", "terminal breakpoint with an invalid register signature"
    return None


def blargg_result(memory: ProtocolMemory):
    text = bytes(memory.serial).decode("ascii", "replace")
    if "Passed" in text:
        return "PASS", "serial output contains Passed"
    if "Failed" in text:
        return "FAIL", "serial output contains Failed"
    # Some Blargg harnesses expose DE B0 61 and a zero-terminated message in
    # cartridge RAM instead of (or in addition to) serial output.
    if len(memory.eram) >= 5 and memory.eram[1:4] == b"\xDE\xB0\x61":
        raw = bytes(memory.eram[4:]).split(b"\0", 1)[0]
        ram_text = raw.decode("ascii", "replace")
        if "Passed" in ram_text:
            return "PASS", "Blargg cartridge-RAM signature contains Passed"
        if "Failed" in ram_text:
            return "FAIL", "Blargg cartridge-RAM signature contains Failed"
    return None


def base_result(path: Path, root: Path, rom: bytes):
    profile = cartridge_profile(rom) if len(rom) >= 0x150 else None
    return {
        "path": str(path),
        "relative_path": str(path.resolve().relative_to(root.resolve()))
        if path.resolve().is_relative_to(root.resolve()) else str(path),
        "suite": suite_name(path, root),
        "sha256": hashlib.sha256(rom).hexdigest(),
        "bytes": len(rom),
        "protocol": protocol_for(path),
        "cartridge": profile,
        "python": {"status": "NOT_RUN"},
        "native_genesis": {
            "status": "NOT_RUN",
            "detail": "no native Genesis execution backend was requested or verified",
        },
    }


def run_python(path: Path, root: Path, max_steps: int, max_frames: int | None,
               loop_threshold: int):
    rom = path.read_bytes()
    result = base_result(path, root, rom)
    supported, reason = header_support(rom, path)
    if supported:
        supported, reason = model_support(path)
    protocol = result["protocol"]
    if not supported:
        result["python"] = {"status": "UNSUPPORTED", "category": "cartridge", "detail": reason}
        return result
    if protocol in ("manual_visual", "unknown"):
        result["python"] = {
            "status": "NOT_RUN", "category": "protocol",
            "detail": "no automated success protocol is defined for this ROM",
        }
        return result

    started = time.monotonic()
    memory = ProtocolMemory(rom)
    cpu = CPU(memory)
    recent = deque(maxlen=32)
    unique_pcs = set()
    max_cycles = max_frames * 70224 if max_frames is not None else None
    same_pc = 0
    prior_key = None
    status = None
    category = None
    detail = None
    steps = 0
    try:
        for steps in range(1, max_steps + 1):
            key = (memory.rom_bank, cpu.pc)
            unique_pcs.add(key)
            recent.append({"bank": key[0], "pc": key[1]})
            same_pc = same_pc + 1 if key == prior_key else 0
            prior_key = key

            if protocol.startswith("mooneye"):
                terminal = terminal_mooneye(cpu, memory, protocol)
                if terminal:
                    status, detail = terminal
                    category = "protocol"
                    break
            cpu.step()
            if protocol == "blargg_serial":
                terminal = blargg_result(memory)
                if terminal:
                    status, detail = terminal
                    category = "protocol"
                    break
            if max_cycles is not None and memory.cycles >= max_cycles:
                status, category, detail = "TIMEOUT", "frame_limit", f"reached {max_frames} emulated frames"
                break
            if same_pc >= loop_threshold:
                status, category, detail = "TIMEOUT", "infinite_loop", "PC and ROM bank did not advance"
                break
    except NotImplementedError as exc:
        status, category, detail = "FAIL", "unsupported_instruction", str(exc)
    except Exception as exc:  # Report diagnostics without aborting the suite.
        status, category, detail = "FAIL", "crash", f"{type(exc).__name__}: {exc}"
    if status is None:
        status, category, detail = "TIMEOUT", "instruction_limit", f"reached {max_steps} instructions"

    serial = bytes(memory.serial).decode("ascii", "replace")
    if status == "FAIL" and memory.dma_writes:
        category = "oam_dma_timing"
        detail += f"; test started progressive OAM DMA {memory.dma_writes} time(s)"
    result["python"] = {
        "status": status,
        "category": category,
        "detail": detail,
        "steps": steps,
        "cycles": memory.cycles,
        "frames": memory.cycles / 70224,
        "elapsed_seconds": round(time.monotonic() - started, 6),
        "rom_bank": memory.rom_bank,
        "registers": cpu_registers(cpu),
        "ime": cpu.ime,
        "halted": cpu.halted,
        "interrupt_flags": memory.io[0x0F],
        "interrupt_enable": memory.ie,
        "unique_bank_pcs": len(unique_pcs),
        "recent_bank_pcs": list(recent),
        "serial_output": serial[-4096:],
        "oam_dma_writes": memory.dma_writes,
    }
    return result


def compile_native(result, path: Path, output_root: Path, steps: int):
    """Build a Genesis ROM, but do not infer an execution result from that."""
    if result["python"]["status"] != "PASS":
        result["native_genesis"]["detail"] = "not built because the Python reference did not pass"
        return
    output = output_root / result["sha256"][:16]
    try:
        from build_recompiled import build
        artifact = build(path, output, steps=steps)
        report_path = output / "build-report.json"
        build_report = json.loads(report_path.read_text()) if report_path.exists() else None
        result["native_genesis"] = {
            "status": "NOT_RUN",
            "detail": "native ROM assembled; no Genesis success protocol has been observed",
            "build_status": "BUILT",
            "artifact": str(artifact),
            "build_report": build_report,
        }
    except Exception as exc:
        result["native_genesis"] = {
            "status": "FAIL", "category": "compile",
            "detail": f"{type(exc).__name__}: {exc}", "build_status": "FAILED",
        }


def _blastem_values(output: str):
    values = {}
    for address, size, value in re.findall(r"\[\$ff([0-9a-f]{4})\]\.(b|w|l):\s*([0-9a-f]+)", output, re.I):
        values[f"FF{address.upper()}.{size.lower()}"] = int(value, 16)
    return values


def _run_in_pty(command, input_text: str, timeout: int):
    """Run an interactive debugger command stream on a real pseudo-terminal."""
    master, slave = pty.openpty()
    process = subprocess.Popen(command, stdin=slave, stdout=slave, stderr=slave, close_fds=True)
    os.close(slave)
    os.write(master, input_text.encode())
    chunks = []
    deadline = time.monotonic() + timeout
    timed_out = False
    try:
        while process.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True; process.kill(); break
            readable, _, _ = select.select([master], [], [], min(0.25, remaining))
            if readable:
                try:chunks.append(os.read(master, 65536))
                except OSError:break
        process.wait(timeout=5)
        while True:
            readable, _, _ = select.select([master], [], [], 0)
            if not readable:break
            try:chunks.append(os.read(master, 65536))
            except OSError:break
    finally:
        os.close(master)
    return process.returncode, b"".join(chunks).decode("utf-8", "replace"), timed_out


def run_native_blastem(result, source: Path, blastem: Path, frames: int, timeout: int):
    """Observe a Mooneye terminal signature through BlastEm's debugger."""
    native = result["native_genesis"]
    if native.get("build_status") != "BUILT":
        return
    if result["protocol"] != "mooneye_fibonacci":
        native["detail"] = "native ROM assembled; this protocol has no automated BlastEm observer"
        return
    commands = (
        f"frames {frames}\n"
        "p/x [$ff0000].w [$ff0002].w [$ff0008].b [$ff0009].b "
        "[$ff000a].b [$ff000b].b [$ff000c].b [$ff000d].b "
        "[$ff000e].b [$ff000f].b [$ff0010].w "
        "[$ff0018].l [$ff0038].l [$ff0020].l\nquit\n"
    )
    returncode, output, timed_out = _run_in_pty(
        [str(blastem.resolve()), "-d", str(Path(native["artifact"]).resolve())], commands, timeout
    )
    if timed_out:
        native.update(status="TIMEOUT", category="emulator_timeout", detail=f"BlastEm exceeded {timeout} seconds")
        return
    values = _blastem_values(output)
    register_addresses = ("FF000A.b", "FF000B.b", "FF000C.b", "FF000D.b", "FF000E.b", "FF000F.b")
    registers = tuple(values.get(address, -1) for address in register_addresses)
    bank, pc = values.get("FF0000.w"), values.get("FF0002.w")
    terminal_loop = False
    rom = source.read_bytes()
    if bank is not None and pc is not None:
        offset = pc if pc < 0x4000 else bank * 0x4000 + pc - 0x4000
        terminal_loop = offset + 1 < len(rom) and rom[offset:offset + 2] == b"\x18\xFE"
    native["blastem"] = {
        "frames": frames, "exit_code": returncode,
        "observed_memory": values, "terminal_jr_loop": terminal_loop,
    }
    if values.get("FF0018.l")==0xBADB10C0 or values.get("FF0038.l",0)>0:
        location=f"bank ${bank:04X} PC ${pc:04X}" if bank is not None and pc is not None else "unknown bank/PC"
        native.update(status="FAIL",category="missing_native_block",
                      detail=f"Missing native block at {location}; increase trace/discovery coverage")
    elif registers == MOONEYE_PASS and terminal_loop:
        native.update(status="PASS", category="protocol", detail="BlastEm observed Fibonacci registers in the terminal JR loop")
    elif registers == MOONEYE_FAIL and terminal_loop:
        native.update(status="FAIL", category="protocol", detail="BlastEm observed the $42 failure signature")
    else:
        native.update(status="TIMEOUT", category="protocol", detail="BlastEm did not reach a valid terminal signature")


def write_report(path: Path, root: Path, args, results):
    path.parent.mkdir(parents=True, exist_ok=True)
    counts = Counter(item["python"]["status"] for item in results)
    report = {
        "format_version": 1,
        "fixture_root": str(root.resolve()),
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "limits": {"instructions": args.max_steps, "frames": args.max_frames},
        "python_summary": {status: counts.get(status, 0) for status in STATUSES},
        "native_summary": dict(Counter(item["native_genesis"]["status"] for item in results)),
        "results": results,
    }
    path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, help="ROMs/directories; relative names may be under --root")
    parser.add_argument("--root", type=Path, default=Path("test_roms"), help="immutable fixture root")
    parser.add_argument("--suite", help="case-insensitive path filter")
    parser.add_argument("--max-steps", type=int, default=2_000_000)
    parser.add_argument("--max-frames", type=int, default=None)
    parser.add_argument("--loop-threshold", type=int, default=65_536)
    parser.add_argument("--json", type=Path, default=Path("compat-results/report.json"))
    parser.add_argument("--compile-native", action="store_true", help="assemble Python-passing ROMs; execution remains NOT_RUN")
    parser.add_argument("--native-steps", type=int, default=None, help="trace steps per native build (defaults to --max-steps)")
    parser.add_argument("--native-output", type=Path, default=Path("compat-results/native-builds"))
    parser.add_argument("--run-native-blastem", action="store_true", help="open BlastEm and verify supported native protocols")
    parser.add_argument("--blastem", type=Path,
                        default=Path(os.environ.get("GB2MD_BLASTEM") or shutil.which("blastem") or "blastem"),
                        help="external BlastEm executable (or set GB2MD_BLASTEM)")
    parser.add_argument("--native-frames", type=int, default=600)
    parser.add_argument("--native-timeout", type=int, default=60)
    parser.add_argument("--list", action="store_true", help="list selected ROMs without running them")
    args = parser.parse_args(argv)
    if args.max_steps <= 0 or (args.max_frames is not None and args.max_frames <= 0):
        parser.error("limits must be positive")
    if args.run_native_blastem and not args.compile_native:
        parser.error("--run-native-blastem requires --compile-native")
    if args.run_native_blastem and not args.blastem.is_file():
        parser.error(f"BlastEm executable does not exist: {args.blastem}")
    root = args.root.resolve()
    if not root.is_dir():
        parser.error(f"fixture root does not exist: {root}")
    roms = discover_roms(root, args.paths, args.suite)
    if not roms:
        parser.error("no .gb or .gbc fixtures matched")
    if args.list:
        for path in roms:
            print(path)
        print(f"{len(roms)} ROM(s)")
        return 0

    results = []
    for index, path in enumerate(roms, 1):
        print(f"[{index}/{len(roms)}] {path}", flush=True)
        item = run_python(path, root, args.max_steps, args.max_frames, args.loop_threshold)
        if args.compile_native:
            compile_native(item, path, args.native_output, args.native_steps or args.max_steps)
            if args.run_native_blastem:
                run_native_blastem(item, path, args.blastem, args.native_frames, args.native_timeout)
        results.append(item)
        py = item["python"]
        suffix = f": {py.get('detail', '')}" if py.get("detail") else ""
        print(f"  Python {py['status']}{suffix}", flush=True)
    report = write_report(args.json, root, args, results)
    summary = report["python_summary"]
    print("Python: " + ", ".join(f"{key}={summary[key]}" for key in STATUSES))
    native = report["native_summary"]
    print("Native Genesis: " + ", ".join(f"{key}={value}" for key, value in sorted(native.items())))
    print(f"JSON: {args.json}")
    return 1 if summary["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
