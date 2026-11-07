import json, pathlib, subprocess, sys, tempfile, unittest

ROOT = pathlib.Path(__file__).parents[1]
class SmokeTest(unittest.TestCase):
    def test_external_assembler_resolution(self):
        import build_recompiled
        with tempfile.TemporaryDirectory() as d:
            assembler=pathlib.Path(d)/"vasmm68k_mot"
            assembler.write_bytes(b"")
            self.assertEqual(build_recompiled.find_assembler(assembler),assembler.resolve())

    def test_minimal_rom_translation(self):
        rom = bytearray(0x150); rom[0x134:0x138] = b"TEST"
        rom[0x100:0x106] = bytes([0x3E, 0x12, 0xEA, 0x00, 0xC0, 0xC9])
        with tempfile.TemporaryDirectory() as d:
            src, out = pathlib.Path(d)/"test.gb", pathlib.Path(d)/"out"; src.write_bytes(rom)
            subprocess.run([sys.executable, ROOT/"gb2md.py", src, "--out", out, "--emit-title-rom"], check=True)
            self.assertIn("L_gb_0100", (out/"translated_bank0.s").read_text())
            self.assertEqual(json.loads((out/"memory-plan.json").read_text())["title"], "TEST")
            self.assertEqual((out/"title_screen.md").read_bytes()[0x100:0x104], b"SEGA")

    def test_mbc3_profile(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("gb2md", ROOT / "gb2md.py")
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        rom = bytearray(64 * 0x4000); rom[0x147:0x14A] = bytes([0x13, 0x05, 0x03])
        profile = module.cartridge_profile(rom)
        self.assertEqual(profile["mapper"], "mbc3")
        self.assertEqual(profile["external_ram_bytes"], 32 * 1024)

    def test_full_instruction_length_table(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("gb2md", ROOT / "gb2md.py")
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        self.assertEqual(module.instruction_length(0xCB), 2)
        self.assertEqual(module.instruction_length(0xEA), 3)
        self.assertEqual(module.instruction_length(0x36), 2)
        self.assertEqual(module.instruction_length(0xAF), 1)

    def test_genesis_title_rom_header(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("title", ROOT / "build_title_demo.py")
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as d:
            out = pathlib.Path(d) / "title.md"; result = module.emit_title_rom(out); image = out.read_bytes()
            self.assertEqual(image[0x100:0x104], b"SEGA")
            self.assertEqual(int.from_bytes(image[4:8], "big"), 0x200)
            self.assertEqual(len(image), result["size"])
            self.assertNotEqual(int.from_bytes(image[0x18E:0x190], "big"), 0)
            # The first DBF is at $27C. Its -6 displacement returns to $278,
            # the start of the VRAM-clear store; -8 would jump into an operand.
            self.assertEqual(int.from_bytes(image[0x27E:0x280], "big", signed=True), -6)

    def test_mbc3_bank_ram_and_rtc_latch(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("memory", ROOT / "gb_memory.py")
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        rom = bytearray(64 * 0x4000)
        for bank in range(64): rom[bank * 0x4000] = bank
        m = module.MBC3(bytes(rom))
        self.assertEqual(m.read(0x4000), 1)
        m.write(0x2000, 0); self.assertEqual(m.read(0x4000), 1)
        m.write(0x2000, 42); self.assertEqual(m.read(0x4000), 42)
        m.write(0xA000, 7); self.assertEqual(m.read(0xA000), 0xFF)
        m.write(0x0000, 0x0A); m.write(0x4000, 3); m.write(0xA000, 7)
        self.assertEqual(m.read(0xA000), 7)
        m.write(0x4000, 0x08); m.write(0xA000, 9); m.write(0x6000, 0); m.write(0x6000, 1)
        m.write(0xA000, 10); self.assertEqual(m.read(0xA000), 9)

    def test_synthetic_reference_program_updates_vram(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("cpu", ROOT / "gb_cpu.py")
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        rom=bytearray(0x8000)
        rom[0x100:0x108]=bytes([0x3E,0x12,0xEA,0x00,0x80,0xC3,0x00,0x01])
        memory = module.Memory(rom); cpu = module.CPU(memory)
        for _ in range(4): cpu.step()
        self.assertNotEqual(sum(memory.vram), 0)
        self.assertNotEqual(cpu.pc, 0x100)

    def test_dmg_tile_to_genesis_4bpp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("vdp", ROOT / "gb_vdp.py")
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        # Pixel colours 0,1,2,3 repeated twice in the first source row.
        source = bytes([0x55,0x33]) + bytes(14)
        self.assertEqual(module.md_tile(source)[:4], bytes([0x01,0x23,0x01,0x23]))

    def test_ei_is_delayed_by_one_instruction(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("cpu", ROOT / "gb_cpu.py")
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        rom=bytearray(0x8000); rom[0x100:0x104]=bytes([0xFB,0x00,0x00,0x76]); rom[0x40]=0xD9
        m=module.Memory(rom); c=module.CPU(m); m.io[0x0F]=m.ie=1
        c.step(); self.assertFalse(c.ime)
        c.step(); self.assertFalse(c.ime)
        c.step(); self.assertEqual(c.pc,0x40)

    def test_lr35902_cycle_costs_include_taken_branches_and_cb_memory(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location("cpu_cycles",ROOT/"gb_cpu.py");module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        self.assertEqual(module.instruction_cycles(0x00),4)
        self.assertEqual(module.instruction_cycles(0x20,taken=False),8)
        self.assertEqual(module.instruction_cycles(0x20,taken=True),12)
        self.assertEqual(module.instruction_cycles(0xCB,0x46),12) # BIT 0,(HL)
        self.assertEqual(module.instruction_cycles(0xCB,0x06),16) # RLC (HL)

    def test_input_scripts_are_frame_based_and_composable(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location("trace_inputs",ROOT/"trace_recompiler.py");module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        scenario=module.parse_input_script("start@512:8,a|right@700:4")
        self.assertEqual(scenario["events"],[(512,520,0x7F),(700,704,0xEE)])
        scenario=module.parse_input_script("start@512:8,poke:0xCA22-0xCA2B=0x8C@850")
        self.assertEqual(scenario["memory_events"],[(850,0xCA22,0xCA2B,0x8C)])
        with self.assertRaises(ValueError):module.parse_input_script("fire@1:2")

    def test_wram_echo_addresses_share_backing_storage(self):
        from gb_cpu import Memory
        memory=Memory(bytes(0x8000))
        memory.write(0xC802,0x8C)
        self.assertEqual(memory.read(0xE802),0x8C)
        memory.write(0xE123,0x42)
        self.assertEqual(memory.read(0xC123),0x42)

    def test_oam_dma_has_two_cycle_startup_and_progressive_copy(self):
        from gb_cpu import Memory
        memory=Memory(bytes(0x8000));memory.wram[:0xA0]=bytes(range(0xA0))
        memory.oam[:]=b"\xCC"*0xA0;memory.write(0xFF46,0xC0)
        self.assertEqual(memory.oam[0],0xCC)
        memory.tick(4)  # Request is armed; OAM remains accessible this cycle.
        self.assertFalse(memory.dma_active);self.assertEqual(memory.read(0xFE00),0xCC)
        memory.tick(4)  # DMA becomes active, but has not copied byte zero yet.
        self.assertTrue(memory.dma_active);self.assertEqual(memory.read(0xFE00),0xFF)
        self.assertEqual(memory.oam[0],0xCC)
        memory.tick(4);self.assertEqual(memory.oam[0],0)
        self.assertEqual(memory.oam[1],0xCC)
        memory.tick(4*159)
        self.assertFalse(memory.dma_active);self.assertEqual(memory.read(0xFE9F),0x9F)

    def test_oam_dma_restart_keeps_old_transfer_running_until_new_start(self):
        from gb_cpu import Memory
        memory=Memory(bytes(0x8000))
        memory.wram[:0xA0]=b"\x11"*0xA0
        memory.wram[0x1000:0x10A0]=b"\x22"*0xA0
        memory.write(0xFF46,0xC0);memory.tick(12)
        self.assertEqual(memory.oam[0],0x11)
        memory.write(0xFF46,0xD0)
        memory.tick(4);self.assertEqual(memory.oam[1],0x11)
        memory.tick(4);self.assertEqual(memory.oam[2],0x11);self.assertEqual(memory.dma_index,0)
        memory.tick(4);self.assertEqual(memory.oam[0],0x22);self.assertEqual(memory.dma_index,1)

    def test_oam_dma_high_source_pages_mirror_wram_not_io(self):
        from gb_cpu import Memory
        memory=Memory(bytes(0x8000));memory.wram[0x1F00:0x1FA0]=bytes(range(0xA0))
        memory.io[:]=b"\xEE"*0x80
        memory.write(0xFF46,0xFF);memory.tick(4*(2+160))
        self.assertEqual(memory.oam,bytes(range(0xA0)))

    def test_cpu_records_bytes_fetched_after_dma_bus_transition(self):
        from gb_cpu import CPU, Memory
        memory=Memory(bytes(0x8000));memory.oam[1]=0x04
        cpu=CPU(memory);cpu.pc=0xFE01
        memory.write(0xFF46,0xC0);memory.tick(4)  # DMA is in startup.
        cpu.step()
        self.assertEqual(cpu.last_pc,0xFE01)
        self.assertEqual(cpu.last_instruction,b"\xFF")
        self.assertEqual(cpu.pc,0x0038)

    def test_native_oam_dma_is_progressive_and_blocks_cpu_oam_access(self):
        runtime=(ROOT/"runtime_68000.s").read_text()
        self.assertIn("gb_dma_advance:",runtime)
        self.assertIn("move.b #1,gb_dma_requested",runtime)
        self.assertIn("tst.b gb_dma_active\n\tbne.s .oam_unchanged",runtime)
        self.assertNotIn(".dma_direct_loop:",runtime)

    def test_joypad_matrix_selects_active_low_rows(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("cpu", ROOT / "gb_cpu.py")
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        m=module.Memory(bytearray(0x8000)); m.joypad_state=0x7E
        m.write(0xFF00,0x20)  # Direction row: Right is pressed.
        self.assertEqual(m.read(0xFF00)&0x0F,0x0E)
        m.write(0xFF00,0x10)  # Button row: Start is pressed.
        self.assertEqual(m.read(0xFF00)&0x0F,0x07)

    def test_ie_does_not_alias_ff7f(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location("cpu_ie",ROOT/"gb_cpu.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        m=module.Memory(bytearray(0x8000));m.write(0xFFFF,0x1F);m.write(0xFF7F,0)
        self.assertEqual(m.read(0xFFFF),0x1F)
        self.assertEqual(m.read(0xFF7F),0)

    def test_timer_falling_edge_reload_and_interrupt(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location("cpu_timer",ROOT/"gb_cpu.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        m=module.Memory(bytearray(0x8000));m.write(0xFF06,0xA5);m.write(0xFF05,0xFF);m.write(0xFF07,0x05)
        m.tick(16);self.assertEqual(m.read(0xFF05),0);self.assertEqual(m.read(0xFF0F)&4,0)
        m.tick(4);self.assertEqual(m.read(0xFF05),0xA5);self.assertEqual(m.read(0xFF0F)&4,4)

    def test_div_write_can_clock_tima(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location("cpu_div",ROOT/"gb_cpu.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        m=module.Memory(bytearray(0x8000));m.write(0xFF07,0x05);m.tick(8)
        self.assertEqual(m.read(0xFF05),0);m.write(0xFF04,0);self.assertEqual(m.read(0xFF05),1)

    def test_if_unused_bits_read_high_and_ei_sequence_is_not_postponed(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location("cpu_if_ei",ROOT/"gb_cpu.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        rom=bytearray(0x8000);rom[0x100:0x103]=bytes((0xFB,0xFB,0x00))
        m=module.Memory(rom);m.write(0xFF0F,0xFF);self.assertEqual(m.read(0xFF0F),0xFF)
        self.assertEqual(m.io[0x0F],0x1F);m.io[0x0F]=0
        c=module.CPU(m);c.step();self.assertFalse(c.ime);c.step();self.assertFalse(c.ime)
        c.step();self.assertTrue(c.ime)

    def test_io_write_occurs_at_final_instruction_boundary(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location("cpu_io_timing",ROOT/"gb_cpu.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        rom=bytearray(0x8000);rom[0x100:0x102]=bytes((0xE0,0x04))
        m=module.Memory(rom);c=module.CPU(m);c.step()
        self.assertEqual(m.cycles,12);self.assertEqual(m.div_counter,0)

    def test_timer_reload_cycle_write_rules_and_tac_mask(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location("cpu_reload",ROOT/"gb_cpu.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        m=module.Memory(bytearray(0x8000));m.write(0xFF07,0xFF);self.assertEqual(m.read(0xFF07),0xFF);m.write(0xFF07,0x05)
        m.write(0xFF06,0xA5);m.write(0xFF05,0xFF);m.div_counter=15;m.tick(1);m.tick(4)
        self.assertTrue(m.timer_reloaded_this_cycle);m.write(0xFF05,0x11);self.assertEqual(m.read(0xFF05),0xA5)
        m.write(0xFF06,0x77);self.assertEqual(m.read(0xFF05),0x77)

    def test_halt_bug_suppresses_one_opcode_fetch_increment(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location("cpu_halt_bug",ROOT/"gb_cpu.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        rom=bytearray(0x8000);rom[0x100:0x103]=bytes((0x76,0x04,0x00))
        m=module.Memory(rom);m.ie=1;m.io[0x0F]=1;c=module.CPU(m)
        c.step();self.assertFalse(c.halted);self.assertTrue(c.halt_bug);self.assertEqual(c.pc,0x101)
        c.step();self.assertEqual(c.b,1);self.assertEqual(c.pc,0x101)
        c.step();self.assertEqual(c.b,2);self.assertEqual(c.pc,0x102)

    def test_native_runtime_contains_timing_video_and_input_services(self):
        runtime=(ROOT/"runtime_68000.s").read_text()
        for label in ("gb_tick:","gb_render_frame:","gb_read_joypad:","gb_ei_delay",".sprite:","gb_video_dirty"):
            self.assertIn(label,runtime)
        # CLR is a read-modify-write instruction on 68000. Reading the VDP
        # data port while it is configured for writes freezes BlastEm/hardware.
        self.assertNotIn("clr.w $C00000",runtime)
        self.assertIn(".io_timing_synced:",runtime)
        self.assertIn(".plain_io_synced:",runtime)
        self.assertIn("gb_force_tick",runtime)

    def test_native_memory_dispatch_prioritizes_writable_high_memory(self):
        runtime=(ROOT/"runtime_68000.s").read_text()
        read=runtime.split("gb_read8:",1)[1].split("gb_write8:",1)[0]
        write=runtime.split("gb_write8:",1)[1].split("gb_idle_wait:",1)[0]
        self.assertLess(read.index("cmpi.w #$C000,d1"),read.index("cmpi.w #$4000,d1"))
        self.assertLess(read.index("cmpi.w #$FF00,d1"),read.index(".read_low:"))
        self.assertLess(write.index("cmpi.w #$C000,d1"),write.index("cmpi.w #$8000,d1"))
        self.assertLess(write.index("cmpi.w #$FF00,d1"),write.index(".write_low:"))
        # Native external RAM must not silently alias every mapper bank to
        # bank zero. MBC1 mode/upper writes and MBC3 RAM/RTC selection have
        # distinct handlers, while unsupported RTC selectors stay inaccessible.
        self.assertIn("gb_mbc1_mode equ",runtime)
        self.assertIn(".mapper_mbc1:",write)
        self.assertIn(".mapper_mbc3:",write)
        self.assertIn("move.b d0,gb_ram_bank",write)
        self.assertIn("cmpi.b #4,gb_ram_bank",read)

    def test_native_scf_and_ccf_preserve_z_and_update_carry(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location("trace_flags",ROOT/"trace_recompiler.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        base={"operand":0,"pc":0x100,"bank":0,"bytes":"37"}
        scf=module.native_body({**base,"opcode":0x37,"family":"SCF"})
        ccf=module.native_body({**base,"opcode":0x3F,"family":"CCF","bytes":"3f"})
        self.assertIn("andi.b #$80,d0",scf);self.assertIn("ori.b #$10,d0",scf)
        self.assertIn("eori.b #$10,d1",ccf);self.assertIn("andi.b #$80,d0",ccf)

    def test_background_transparency_preserves_gb_sprite_priority(self):
        runtime=(ROOT/"runtime_68000.s").read_text()
        build=(ROOT/"build_recompiled.py").read_text()
        self.assertNotIn("addi.w #$1111,d4",runtime)
        self.assertIn("ori.w #$8000,d0",runtime)
        self.assertIn("word=643",build)
        self.assertIn("$44444444",build)

    def test_oam_only_frames_skip_full_background_conversion(self):
        runtime=(ROOT/"runtime_68000.s").read_text()
        for symbol in ("gb_vram_dirty", "gb_oam_dirty", "gb_bg_dirty",
                       "gb_plane_initialized", ".render_tilemap:", ".sprite_section:"):
            self.assertIn(symbol,runtime)
        self.assertIn("beq.w .sprite_section",runtime)
        background=runtime.split(".render_background:",1)[1].split(".sprite_section:",1)[0]
        self.assertIn("tst.b gb_vram_dirty",background)
        self.assertIn("beq.w .render_tilemap",background)
        self.assertIn("tst.b gb_plane_initialized",background)
        vram_write=runtime.split(".vram:",1)[1].split(".wram:",1)[0]
        self.assertIn("cmpi.w #$1800,d1",vram_write)
        self.assertIn(".vram_map_dirty:",vram_write)
        self.assertIn("move.b #1,gb_bg_dirty",vram_write)

    def test_daa_has_a_native_lowering(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location("trace_daa",ROOT/"trace_recompiler.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        block={"bank":0,"pc":0x100,"opcode":0x27,"operand":0,"bytes":"27","family":"DAA"}
        body=module.native_body(block)
        self.assertIsNotNone(body)
        self.assertIn("move.b d0,gb_a",body)
        self.assertIn("move.b d1,gb_f",body)

    def test_signed_sp_offset_families_have_native_lowerings(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location("trace_sp",ROOT/"trace_recompiler.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        for opcode,family,target in ((0xE8,"ADD_SP_R8","gb_sp"),(0xF8,"LD_HL_SP_R8","gb_h")):
            block={"bank":0,"pc":0x100,"opcode":opcode,"operand":0xF8,"bytes":f"{opcode:02x}f8","family":family}
            body=module.native_body(block)
            self.assertIsNotNone(body)
            self.assertIn("ext.w d3",body)
            self.assertIn(f"move.w d0,{target}",body)

    def test_store_sp_absolute_has_native_lowering(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location("trace_store_sp",ROOT/"trace_recompiler.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        block={"bank":0,"pc":0x100,"opcode":0x08,"operand":0xC123,"bytes":"0823c1","family":"LD_A16_SP"}
        body=module.native_body(block)
        self.assertIsNotNone(body)
        self.assertIn("move.l #$C123,d1",body)
        self.assertIn("move.l #$C124,d1",body)

    def test_color_profiles_expose_sgb_ready_palette_boundary(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location("colors",ROOT/"color_profiles.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        self.assertEqual(set(module.COLOR_PROFILES),{"amber","dmg","green","pocket"})
        self.assertTrue(all(len(p["shades"])==4 for p in module.COLOR_PROFILES.values()))

    def test_cpu_memory_mbc3_rom_window(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location("cpu",ROOT/"gb_cpu.py"); module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        rom=bytearray(64*0x4000); rom[0x147:0x14A]=bytes([0x13,0x05,0x03])
        for bank in range(64):rom[bank*0x4000]=bank
        m=module.Memory(rom); self.assertEqual(m.read(0x4000),1);m.write(0x2000,37);self.assertEqual(m.read(0x4000),37)

    def test_synthetic_executed_opcodes_have_lowering_families(self):
        import importlib.util
        def load(name):
            spec=importlib.util.spec_from_file_location(name,ROOT/(name+".py"));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
        cpu,lower=load("gb_cpu"),load("lr35902_lowering")
        rom=bytearray(0x8000);rom[0x100:0x108]=bytes([0x3E,0x12,0x06,0x34,0x80,0xAF,0x00,0x76])
        c=cpu.CPU(cpu.Memory(rom))
        for _ in range(8):c.step()
        self.assertNotIn("UNCLASSIFIED",{lower.family(op) for op in c.opcode_count})
        self.assertNotIn("INVALID",{lower.family(op) for op in c.opcode_count})

    def test_trace_recompiler_emits_synthetic_blocks(self):
        import importlib.util
        sys.path.insert(0,str(ROOT))
        spec=importlib.util.spec_from_file_location("trace",ROOT/"trace_recompiler.py");module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as d:
            temp=pathlib.Path(d);rom=temp/"original-test.gb";data=bytearray(0x8000)
            data[0x100:0x10C]=bytes([0x00])*12;data[0x10C:0x10F]=bytes([0xC3,0x00,0x01]);rom.write_bytes(data)
            blocks=module.compile_trace(rom,temp,5000)
            assembly=(temp/"translated_trace.s").read_text()
            self.assertGreater(len(blocks),10);self.assertIn("gb_dispatch",assembly)
            self.assertIn("bra.w L_gb_B000_0100",assembly)
            self.assertIn("jmp gb_dispatch",assembly)
            self.assertIn(".dispatch_not_equal_",assembly)
            self.assertIn("gb_chain_B000_",assembly)
            self.assertIn("cmpi.w #200,d1",assembly)
            self.assertIn("move.w d7,d1",assembly)
            self.assertNotIn("move.w gb_cycle_batch,d1",assembly)
            self.assertRegex(assembly,r"\.chain_flush_B000_[0-9A-F]{4}:\n\tclr\.b gb_force_tick\n\tmove\.w #\$[0-9A-F]{4},gb_pc\n\tjsr gb_tick")
            self.assertTrue(all("bytes" in block and "operand" in block and "bank" in block for block in blocks))
            self.assertTrue(any(block["native_lowered"] for block in blocks))

    def test_auto_step_stop_policy(self):
        import trace_recompiler as trace
        self.assertIsNone(trace.auto_stop_reason(200,1000,[4,0,0],3,1))
        self.assertIn("plateau",trace.auto_stop_reason(300,1000,[4,0,0,0],3,1))
        self.assertIsNone(trace.auto_stop_reason(300,1000,[0,0,0],3,1,events_pending=True))
        self.assertIn("maximum",trace.auto_stop_reason(1000,1000,[5],3,1))

    def test_auto_steps_reports_execution_and_plateau(self):
        import trace_recompiler as trace
        rom=bytearray(0x8000);rom[0x100:0x102]=bytes([0x18,0xFE])
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);source=root/"loop.gb";source.write_bytes(rom)
            trace.compile_trace(source,root/"out",10,auto_steps=True,auto_max_steps=100,auto_chunk_steps=10,auto_plateau_chunks=2)
            report=json.loads((root/"out"/"trace-profile.json").read_text())
            self.assertEqual(report["total_steps_executed"],30)
            self.assertEqual(report["dynamic_unique_blocks"],1)
            self.assertIn("plateau",report["scenarios"][0]["stop_reason"])

    def test_auto_inputs_discovers_indirect_joypad_path(self):
        import trace_recompiler as trace
        rom=bytearray(0x8000)
        # Select buttons, wait for Start, then reach $0120 through JP (HL),
        # which direct static closure deliberately cannot infer.
        rom[0x100:0x10E]=bytes([0x3E,0x10,0xE0,0x00,0xF0,0x00,0xE6,0x08,
                                0x20,0xFA,0x21,0x20,0x01,0xE9])
        rom[0x120:0x124]=bytes([0x3E,0x42,0x18,0xFE])
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);source=root/"input.gb";source.write_bytes(rom)
            plain=trace.compile_trace(source,root/"plain",30)
            self.assertNotIn((0,0x120),{(b["bank"],b["pc"]) for b in plain})
            explored=trace.compile_trace(source,root/"explored",30,auto_inputs=True,
                input_max_branches=10,input_max_depth=2,input_branch_steps=50,
                input_max_steps=500,input_hold_frames=1,input_snapshot_interval_frames=1,
                input_max_snapshots=8)
            self.assertIn((0,0x120),{(b["bank"],b["pc"]) for b in explored})
            report=json.loads((root/"explored"/"trace-profile.json").read_text())
            self.assertGreater(report["input_exploration"]["new_blocks"],0)
            self.assertEqual(report["input_exploration"]["limits"]["max_branches"],10)
            self.assertEqual(report["input_exploration"]["limits"]["max_depth"],2)
            self.assertTrue(any(branch["action"]=="start" and branch["new_blocks"]
                                for branch in report["input_exploration"]["branches"]))

    def test_missing_block_trap_has_machine_readable_diagnostics(self):
        runtime=(ROOT/"runtime_68000.s").read_text()
        self.assertIn("gb_missing_count equ $FF0038",runtime)
        self.assertIn("gb_render_count equ $FF003C",runtime)
        self.assertIn("gb_full_render_count equ $FF0040",runtime)
        self.assertIn("gb_halt_fast_forward_count equ $FF0044",runtime)
        self.assertIn("gb_halt_wait:",runtime)
        self.assertIn("bsr.w gb_halt_wait",runtime)
        self.assertIn("move.l #$BADB10C0,$FF0018",runtime)
        self.assertIn("addq.l #1,gb_missing_count",runtime)

    def test_halt_wait_batches_to_earliest_timer_or_vblank_wake_event(self):
        runtime=(ROOT/"runtime_68000.s").read_text()
        section=runtime.split("gb_halt_wait:",1)[1].split("gb_idle_ly:",1)[0]
        self.assertIn("btst #2,gb_io+$07",section)
        self.assertIn("btst #2,gb_ie",section)
        self.assertIn(".halt_timer_batch:",section)
        self.assertIn("move.w gb_timer_accum,d2",section)
        self.assertIn("sub.w d3,d5",section)
        self.assertIn("addq.l #4,d2",section)
        self.assertIn("cmp.l d1,d2",section)
        self.assertIn("cmpi.l #32760,d1",section)
        self.assertIn("move.w #32760,d7",section)
        self.assertIn("sub.l d0,d1",section)
        self.assertIn("bsr.w gb_tick",section)
        self.assertIn("tst.b gb_halted",section)

    def test_tick_consumes_all_div_and_scanline_boundaries_in_large_batches(self):
        runtime=(ROOT/"runtime_68000.s").read_text()
        section=runtime.split("gb_tick:",1)[1].split("gb_render_frame:",1)[0]
        self.assertIn("andi.w #$00FF,d0",section)
        self.assertIn("lsr.w #8,d1",section)
        self.assertIn(".scanline_loop:",section)
        self.assertIn("subi.w #456,d0",section)
        self.assertIn(".scanlines_done:",section)
        self.assertIn("move.w d0,gb_ly_accum",section)

    def test_auto_inputs_can_cross_non_novel_bridge_state(self):
        import trace_recompiler as trace
        rom=bytearray(0x8000)
        # Start is latched into C000 without changing control flow. A later A
        # press can reach the indirect target only if that non-novel state is
        # retained for another input branch.
        rom[0x100:0x122]=bytes([
            0x3E,0x10,0xE0,0x00,0xF0,0x00,0x2F,0xE6,0x08,0x47,
            0xFA,0x00,0xC0,0xB0,0xEA,0x00,0xC0,0xF0,0x00,0x2F,
            0xE6,0x01,0x28,0xEC,0xFA,0x00,0xC0,0xA7,0x28,0xE6,
            0x21,0x28,0x01,0xE9])
        rom[0x128:0x12C]=bytes([0x3E,0x77,0x18,0xFE])
        old_actions=trace.AUTO_INPUT_ACTIONS
        trace.AUTO_INPUT_ACTIONS=[("start",trace.BUTTON_STATES["start"]),("a",trace.BUTTON_STATES["a"])]
        try:
            with tempfile.TemporaryDirectory() as d:
                root=pathlib.Path(d);source=root/"bridge.gb";source.write_bytes(rom)
                blocks=trace.compile_trace(source,root/"out",200,auto_inputs=True,
                    input_max_branches=12,input_max_depth=3,input_branch_steps=12000,
                    input_max_steps=144000,input_hold_frames=1,
                    input_snapshot_interval_frames=1,input_max_snapshots=8,
                    input_bridge_states_per_depth=4)
                report=json.loads((root/"out"/"trace-profile.json").read_text())
                self.assertGreater(report["input_exploration"]["bridge_states_expanded"],0)
                self.assertIn((0,0x128),{(b["bank"],b["pc"]) for b in blocks})
        finally:
            trace.AUTO_INPUT_ACTIONS=old_actions

    def test_static_closure_resolves_bounded_rom_pointer_table(self):
        import trace_recompiler as trace
        rom=bytearray([0xFF])*0x8000
        rom[0x100:0x107]=bytes([0x21,0x20,0x01,0xCD,0x30,0x01,0xE9])
        rom[0x120:0x126]=bytes([0x40,0x01,0x50,0x01,0xFF,0xFF])
        rom[0x130]=0xC9;rom[0x140]=0xC9;rom[0x150]=0xC9
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);source=root/"table.gb";source.write_bytes(rom)
            blocks=trace.compile_trace(source,root/"out",1)
            keys={(b["bank"],b["pc"]) for b in blocks}
            self.assertIn((0,0x140),keys);self.assertIn((0,0x150),keys)
            report=json.loads((root/"out"/"trace-profile.json").read_text())
            self.assertEqual(report["indirect_table_targets"],2)

    def test_static_closure_resolves_rst_inline_pointer_table(self):
        import trace_recompiler as trace
        rom=bytearray([0xFF])*0x8000
        # RST $28 handler: use A*2 to index the little-endian pointer table
        # placed at the stacked return address, then jump to that routine.
        rom[0x28:0x34]=bytes.fromhex("87e15f1600195e2356d5e1e9")
        rom[0x100:0x103]=bytes([0x3E,0x01,0xEF])
        rom[0x103:0x109]=bytes([0x40,0x01,0x50,0x01,0xFF,0xFF])
        rom[0x140]=0xC9;rom[0x150]=0xC9
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);source=root/"rst-table.gb";source.write_bytes(rom)
            blocks=trace.compile_trace(source,root/"out",1)
            keys={(b["bank"],b["pc"]) for b in blocks}
            self.assertIn((0,0x140),keys);self.assertIn((0,0x150),keys)
            self.assertNotIn((0,0x103),keys)  # inline data is not code
            report=json.loads((root/"out"/"trace-profile.json").read_text())
            self.assertEqual(report["rst_inline_table_targets"],2)
            self.assertEqual(report["indirect_table_targets"],2)

    def test_rst_without_table_handler_keeps_normal_fallthrough(self):
        import trace_recompiler as trace
        rom=bytearray([0xFF])*0x8000
        rom[0x28]=0xC9
        rom[0x100:0x104]=bytes([0xEF,0x3E,0x42,0xC9])
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);source=root/"ordinary-rst.gb";source.write_bytes(rom)
            blocks=trace.compile_trace(source,root/"out",1)
            self.assertIn((0,0x101),{(b["bank"],b["pc"]) for b in blocks})

    def test_static_closure_compiles_both_conditional_paths(self):
        import importlib.util
        sys.path.insert(0,str(ROOT))
        spec=importlib.util.spec_from_file_location("trace_closure",ROOT/"trace_recompiler.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        rom=bytearray(0x8000);rom[0x40]=0xC9
        rom[0x100:0x102]=bytes([0x20,0x02])  # JR NZ: fall $102, target $104
        rom[0x102]=0xC9
        rom[0x104:0x107]=bytes([0x3E,0x12,0xC9])
        with tempfile.TemporaryDirectory() as d:
            src=pathlib.Path(d)/"paths.gb";src.write_bytes(rom)
            blocks=module.compile_trace(src,pathlib.Path(d)/"out",1)
            keys={(b["bank"],b["pc"]) for b in blocks}
            self.assertIn((0,0x102),keys)
            self.assertIn((0,0x104),keys)
            self.assertIn((0,0x40),keys)

    def test_ldh_a_c_has_direct_native_lowering(self):
        import trace_recompiler as trace
        block={"bank":0,"pc":0x100,"opcode":0xF2,"operand":0,
               "bytes":"f2","family":"LDH_A_C"}
        body=trace.native_body(block)
        self.assertIsNotNone(body)
        self.assertIn("move.b gb_c,d1",body)
        self.assertIn("ori.w #$FF00,d1",body)
        self.assertIn("jsr gb_read8",body)
        self.assertIn("move.b d0,gb_a",body)

    def test_static_closure_recovers_direct_hram_code_target(self):
        import importlib.util
        sys.path.insert(0,str(ROOT))
        spec=importlib.util.spec_from_file_location("trace_hram_closure",ROOT/"trace_recompiler.py")
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        rom=bytearray(0x8000)
        # Copy RET to FFB6, then call it. Two traced steps observe the copy;
        # static closure must recover the not-yet-executed HRAM target.
        rom[0x100:0x108]=bytes([0x3E,0xC9,0xE0,0xB6,0xCD,0xB6,0xFF,0x76])
        with tempfile.TemporaryDirectory() as d:
            src=pathlib.Path(d)/"hram.gb";src.write_bytes(rom)
            blocks=module.compile_trace(src,pathlib.Path(d)/"out",2)
            self.assertIn((0,0xFFB6),{(b["bank"],b["pc"]) for b in blocks})

    def test_read_only_ly_poll_is_marked_as_idle_wait(self):
        import importlib.util
        sys.path.insert(0,str(ROOT))
        spec=importlib.util.spec_from_file_location("trace_idle",ROOT/"trace_recompiler.py");module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        rom=bytearray(0x8000)
        # LDH A,(LY); CP 144; JR NZ back to the read.
        rom[0x100:0x106]=bytes([0xF0,0x44,0xFE,0x90,0x20,0xFA])
        with tempfile.TemporaryDirectory() as d:
            src=pathlib.Path(d)/"idle.gb";src.write_bytes(rom)
            blocks=module.compile_trace(src,pathlib.Path(d)/"out",100)
            branch=next(b for b in blocks if b["pc"]==0x104)
            self.assertTrue(branch["idle_wait"])
            self.assertEqual(branch["idle_ly_target"],0x90)
