#!/usr/bin/env python3
"""Run original GB code through the semantic oracle and save its rendered frame."""
from __future__ import annotations
import argparse, pathlib
from gb_cpu import CPU, Memory
from gb_render import frame_ppm

def main():
    p=argparse.ArgumentParser(); p.add_argument("rom",type=pathlib.Path); p.add_argument("--steps",type=int,default=100000); p.add_argument("--frame",type=pathlib.Path,default=pathlib.Path("frame.ppm")); ns=p.parse_args()
    memory=Memory(ns.rom.read_bytes()); cpu=CPU(memory)
    for _ in range(ns.steps): cpu.step()
    ns.frame.write_bytes(frame_ppm(memory))
    print(f"executed {ns.steps} LR35902 instructions; PC=${cpu.pc:04X}; wrote {ns.frame}; VRAM nonzero={sum(v != 0 for v in memory.vram)}")
if __name__ == "__main__": main()
