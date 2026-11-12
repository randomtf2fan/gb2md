; Shared state is placed in Genesis work RAM, not in cartridge ROM.
gb_bank equ $FF0000
gb_pc equ $FF0002
gb_operand equ $FF0004
gb_opcode equ $FF0006
gb_a equ $FF0008
gb_f equ $FF0009
gb_b equ $FF000A
gb_c equ $FF000B
gb_d equ $FF000C
gb_e equ $FF000D
gb_h equ $FF000E
gb_l equ $FF000F
gb_sp equ $FF0010
gb_ime equ $FF0012
gb_ie equ $FF0013
gb_write_count equ $FF0014
gb_ei_delay equ $FF001C
gb_halted equ $FF001D
gb_rom_bank equ $FF001E
gb_cycle_counter equ $FF0020
gb_div_accum equ $FF0024
gb_timer_accum equ $FF0026
gb_ly_accum equ $FF0028
gb_mapper_kind equ $FF002A
gb_step_cycles equ $FF002B
gb_video_dirty equ $FF002C
gb_cycle_batch equ $FF002E
gb_vram_dirty equ $FF0030
gb_oam_dirty equ $FF0031
gb_bg_dirty equ $FF0032
gb_timer_reloaded equ $FF0033
gb_defer_irq equ $FF0034
gb_force_tick equ $FF0035
gb_plane_initialized equ $FF0036
gb_missing_count equ $FF0038
gb_render_count equ $FF003C
gb_full_render_count equ $FF0040
gb_halt_fast_forward_count equ $FF0044
gb_dma_source equ $FF0048
gb_dma_index equ $FF004A
gb_dma_active equ $FF004C
gb_dma_request_source equ $FF004D
gb_dma_requested equ $FF004E
gb_dma_start_source equ $FF004F
gb_dma_starting equ $FF0050
gb_ram_bank equ $FF0051
gb_ram_enabled equ $FF0052
gb_mbc1_mode equ $FF0053
gb_mbc1_upper equ $FF0054
gb_stat_line equ $FF0055
gb_window_full equ $FF0056
gb_bank_dirty equ $FF0057
gb_irq_entry equ $FF0058
gb_fetch_bytes equ $FF0059       ; three sampled bytes for native variant guards
gb_io equ $FF0100
gb_hram equ $FF0180
gb_oam equ $FF0200
gb_vram equ $FF0300
gb_wram equ $FF2300
gb_eram equ $FF4300
gb_tile_dirty equ $FFC300

	xdef gb_dispatch,gb_read8,gb_write8,gb_render_frame
gb_dispatch:
	clr.b gb_force_tick
	bsr.w gb_tick
	tst.b gb_halted
	beq.s .dispatch_awake
	bsr.w gb_halt_wait
	bra.s gb_dispatch
.dispatch_awake:
	jmp gb_dispatch_tree
gb_missing_block:
	; BADB10C0 identifies missing trace coverage. gb_bank/gb_pc and all GB
	; registers remain intact for BlastEm or real-hardware RAM inspection.
	cmpi.l #$BADB10C0,$FF0018
	beq.s .missing_halt
	move.l #$BADB10C0,$FF0018
	addq.l #1,gb_missing_count
.missing_halt:
	bra.w gb_missing_block

; Logical PC determines execution identity; bank zero is also legal in an
; MBC5 upper window, so do not infer the window from the old gb_bank value.
gb_normalize_bank:
	cmpi.w #$4000,gb_pc
	blo.s .fixed_window
	cmpi.w #$8000,gb_pc
	bhs.s .fixed_window
	move.w gb_rom_bank,gb_bank
	rts
.fixed_window:
	clr.w gb_bank
	rts

; d1.w = logical GB address, returns value in d0.b.
gb_read8:
	moveq #-1,d0
	; Translated game code reads writable high memory far more often than ROM:
	; split there first so WRAM, I/O, HRAM and IE avoid every cartridge/VRAM
	; comparison. ROM and VRAM still use the same handlers below.
	cmpi.w #$C000,d1
	blo.w .read_low
	cmpi.w #$FF00,d1
	bhs.w .read_high_io
	cmpi.w #$E000,d1
	blo.w .wram_read
	cmpi.w #$FE00,d1
	blo.w .echo_read
	cmpi.w #$FEA0,d1
	blo.w .oam_read
	bra.w .read_done
.read_high_io:
	cmpi.w #$FF80,d1
	blo.w .io_read
	cmpi.w #$FFFF,d1
	blo.w .hram_read
	move.b gb_ie,d0
	bra.w .read_done
.read_low:
	cmpi.w #$4000,d1
	blo.w .rom0_read
	cmpi.w #$8000,d1
	blo.w .romx_read
	cmpi.w #$A000,d1
	blo.w .vram_read
	bra.w .eram_read
.read_done:
	rts
.rom0_read:
	lea gb_cart_rom,a0
	; In MBC1 RAM-banking mode, the upper register remaps the fixed window.
	cmpi.b #$01,gb_mapper_kind
	blo.s .rom0_read_data
	cmpi.b #$03,gb_mapper_kind
	bhi.s .rom0_read_data
	tst.b gb_mbc1_mode
	beq.s .rom0_read_data
	moveq #0,d2
	move.b gb_mbc1_upper,d2
	lsl.l #8,d2
	lsl.l #8,d2
	lsl.l #3,d2
	adda.l d2,a0
.rom0_read_data:
	move.b (a0,d1.w),d0
	rts
.romx_read:
	moveq #0,d2
	move.w gb_rom_bank,d2
	lsl.l #8,d2
	lsl.l #6,d2
	subi.w #$4000,d1
	lea gb_cart_rom,a0
	adda.l d2,a0
	move.b (a0,d1.w),d0
	rts
.vram_read:
	subi.w #$8000,d1
	lea gb_vram,a0
	move.b (a0,d1.w),d0
	rts
.eram_read:
	tst.b gb_ram_enabled
	beq.s .eram_read_done
	cmpi.b #4,gb_ram_bank
	bhs.s .eram_read_done
	subi.w #$A000,d1
	moveq #0,d2
	move.b gb_ram_bank,d2
	lsl.l #8,d2
	lsl.l #5,d2
	lea gb_eram,a0
	adda.l d2,a0
	move.b (a0,d1.w),d0
.eram_read_done:
	rts
.wram_read:
	subi.w #$C000,d1
	lea gb_wram,a0
	move.b (a0,d1.w),d0
	rts
.echo_read:
	subi.w #$E000,d1
	lea gb_wram,a0
	move.b (a0,d1.w),d0
	rts
.oam_read:
	; OAM accessibility changes at individual DMA M-cycles. Commit all batched
	; cycles through this read before sampling the active-transfer gate.
	movem.l d1-d2/a0,-(sp)
	move.b #1,gb_defer_irq
	bsr.w gb_tick
	clr.b gb_defer_irq
	move.b #1,gb_force_tick
	clr.b gb_step_cycles
	movem.l (sp)+,d1-d2/a0
	tst.b gb_dma_active
	beq.s .oam_read_available
	moveq #-1,d0
	rts
.oam_read_available:
	subi.w #$FE00,d1
	lea gb_oam,a0
	move.b (a0,d1.w),d0
	rts
.io_read:
	cmpi.w #$FF41,d1
	bne.s .not_stat_status_read
	bsr.w gb_stat_sync
.not_stat_status_read:
	cmpi.w #$FF00,d1
	bne.s .plain_io_read
	bsr.w gb_read_joypad
	rts
.plain_io_read:
	subi.w #$FF00,d1
	cmpi.w #$0004,d1
	blo.s .plain_io_synced
	cmpi.w #$0007,d1
	bhi.s .plain_io_synced
	; DIV/TIMA/TMA/TAC reads are ordering barriers. Apply straight-line
	; batched cycles, including this read instruction, before sampling.
	movem.l d1-d2/a0,-(sp)
	move.b #1,gb_defer_irq
	bsr.w gb_tick
	clr.b gb_defer_irq
	move.b #1,gb_force_tick
	clr.b gb_step_cycles
	movem.l (sp)+,d1-d2/a0
.plain_io_synced:
	lea gb_io,a0
	move.b (a0,d1.w),d0
	cmpi.w #$0041,d1
	bne.s .not_stat_read
	ori.b #$80,d0
.not_stat_read:
	cmpi.w #$0007,d1
	bne.s .not_tac_read
	ori.b #$F8,d0
.not_tac_read:
	cmpi.w #$000F,d1
	bne.s .plain_io_done
	ori.b #$E0,d0
.plain_io_done:
	rts
.hram_read:
	subi.w #$FF80,d1
	lea gb_hram,a0
	move.b (a0,d1.w),d0
	rts

; d1.w = logical GB address, d0.b = value.
gb_write8:
	addq.l #1,gb_write_count
	; As above, prioritize the writable address space used by normal gameplay.
	; Mapper and VRAM writes take the low path; their semantics are unchanged.
	cmpi.w #$C000,d1
	blo.w .write_low
	cmpi.w #$FF00,d1
	bhs.w .write_high_io
	cmpi.w #$E000,d1
	blo.w .wram
	cmpi.w #$FE00,d1
	blo.w .echo
	cmpi.w #$FEA0,d1
	blo.w .oam
	bra.w .done
.write_high_io:
	cmpi.w #$FF80,d1
	blo.w .io
	cmpi.w #$FFFF,d1
	blo.w .hram
	bsr.w gb_irq_write_barrier
	move.b d0,gb_ie
	bra.w .done
.write_low:
	cmpi.w #$8000,d1
	blo.w .mapper
	cmpi.w #$A000,d1
	blo.w .vram
	bra.w .eram
.done:
	rts
.mapper:
	; The next instruction may be fetched from a newly selected bank, even
	; on straight-line code. Force a charged boundary before direct chaining.
	move.b #1,gb_force_tick
	move.b #1,gb_bank_dirty
	; MBC1/MBC3 low ROM-bank register. Other mapper controls are expanded in
	; the same service without changing generated blocks.
	cmpi.b #$19,gb_mapper_kind
	blo.s .mapper_not_mbc5
	cmpi.b #$1E,gb_mapper_kind
	bls.w .mapper_mbc5
.mapper_not_mbc5:
	cmpi.w #$2000,d1
	bhs.s .mapper_bank_select
	cmpi.b #$01,gb_mapper_kind
	blo.w .done
	cmpi.b #$03,gb_mapper_kind
	bls.s .mapper_ram_enable
	cmpi.b #$0F,gb_mapper_kind
	blo.w .done
	cmpi.b #$13,gb_mapper_kind
	bhi.w .done
.mapper_ram_enable:
	andi.b #$0F,d0
	cmpi.b #$0A,d0
	seq gb_ram_enabled
	andi.b #1,gb_ram_enabled
	rts
.mapper_bank_select:
	cmpi.b #$01,gb_mapper_kind
	beq.w .mapper_mbc1
	cmpi.b #$02,gb_mapper_kind
	beq.w .mapper_mbc1
	cmpi.b #$03,gb_mapper_kind
	beq.w .mapper_mbc1
	cmpi.b #$0F,gb_mapper_kind
	blo.w .done
	cmpi.b #$13,gb_mapper_kind
	bls.w .mapper_mbc3
	bra.w .done
.mapper_mbc1:
	cmpi.w #$2000,d1
	blo.w .done
	cmpi.w #$4000,d1
	bhs.s .mbc1_upper_select
	andi.w #$001F,d0
	bne.s .mbc1_low_ready
	moveq #1,d0
.mbc1_low_ready:
	move.w gb_rom_bank,d2
	andi.w #$0060,d2
	or.w d2,d0
	move.w d0,gb_rom_bank
	rts
.mbc1_upper_select:
	cmpi.w #$6000,d1
	bhs.s .mbc1_mode_select
	andi.b #3,d0
	move.b d0,gb_mbc1_upper
	moveq #0,d2
	move.b d0,d2
	lsl.w #5,d2
	andi.w #$001F,gb_rom_bank
	or.w d2,gb_rom_bank
	tst.b gb_mbc1_mode
	beq.s .mbc1_upper_rom_mode
	move.b d0,gb_ram_bank
	rts
.mbc1_upper_rom_mode:
	clr.b gb_ram_bank
	rts
.mbc1_mode_select:
	andi.b #1,d0
	move.b d0,gb_mbc1_mode
	beq.s .mbc1_mode_rom
	move.b gb_mbc1_upper,gb_ram_bank
	rts
.mbc1_mode_rom:
	clr.b gb_ram_bank
	rts
.mapper_mbc3:
	cmpi.w #$2000,d1
	blo.w .done
	cmpi.w #$4000,d1
	bhs.s .mbc3_ram_rtc_select
	andi.w #$007F,d0
	bne.s .store_mapper_bank
	moveq #1,d0
.store_mapper_bank:
	move.w d0,gb_rom_bank
	rts
.mbc3_ram_rtc_select:
	cmpi.w #$6000,d1
	bhs.w .done
	; Values 0-3 select RAM. RTC values 8-C are retained as inaccessible
	; selectors until the RTC register layer is implemented.
	move.b d0,gb_ram_bank
	rts
.mapper_mbc5:
	cmpi.w #$2000,d1
	bhs.s .mbc5_rom_low
	andi.b #$0F,d0
	cmpi.b #$0A,d0
	seq gb_ram_enabled
	andi.b #1,gb_ram_enabled
	rts
.mbc5_rom_low:
	cmpi.w #$3000,d1
	bhs.s .mbc5_rom_high
	andi.w #$00FF,d0
	andi.w #$0100,gb_rom_bank
	or.w d0,gb_rom_bank
	rts
.mbc5_rom_high:
	cmpi.w #$4000,d1
	bhs.s .mbc5_ram_bank
	andi.w #1,d0
	lsl.w #8,d0
	andi.w #$00FF,gb_rom_bank
	or.w d0,gb_rom_bank
	rts
.mbc5_ram_bank:
	cmpi.w #$6000,d1
	bhs.w .done
	andi.b #3,d0
	move.b d0,gb_ram_bank
	rts
.vram:
	subi.w #$8000,d1
	lea gb_vram,a0
	cmp.b (a0,d1.w),d0
	beq.s .vram_unchanged
	move.b d0,(a0,d1.w)
	move.b #1,gb_video_dirty
	cmpi.w #$1800,d1
	bhs.s .vram_map_dirty
	move.w d1,d2
	lsr.w #4,d2
	lea gb_tile_dirty,a0
	move.b #1,(a0,d2.w)
	move.b #1,gb_vram_dirty
	bra.s .vram_unchanged
.vram_map_dirty:
	move.b #1,gb_bg_dirty
.vram_unchanged:
	rts
.eram:
	tst.b gb_ram_enabled
	beq.s .eram_done
	cmpi.b #4,gb_ram_bank
	bhs.s .eram_done
	subi.w #$A000,d1
	moveq #0,d2
	move.b gb_ram_bank,d2
	lsl.l #8,d2
	lsl.l #5,d2
	lea gb_eram,a0
	adda.l d2,a0
	move.b d0,(a0,d1.w)
.eram_done:
	rts
.wram:
	subi.w #$C000,d1
	lea gb_wram,a0
	move.b d0,(a0,d1.w)
	rts
.echo:
	subi.w #$E000,d1
	lea gb_wram,a0
	move.b d0,(a0,d1.w)
	rts
.oam:
	; As with reads, an OAM write is ordered at its actual instruction boundary
	; so a DMA that starts during the instruction can suppress the store.
	movem.l d0-d2/a0,-(sp)
	move.b #1,gb_defer_irq
	bsr.w gb_tick
	clr.b gb_defer_irq
	move.b #1,gb_force_tick
	clr.b gb_step_cycles
	movem.l (sp)+,d0-d2/a0
	tst.b gb_dma_active
	bne.s .oam_unchanged
	subi.w #$FE00,d1
	lea gb_oam,a0
	cmp.b (a0,d1.w),d0
	beq.s .oam_unchanged
	move.b d0,(a0,d1.w)
	move.b #1,gb_video_dirty
	move.b #1,gb_oam_dirty
.oam_unchanged:
	rts
.io:
	subi.w #$FF00,d1
	cmpi.w #$000F,d1
	beq.s .io_flush_irq_timing
	cmpi.w #$0046,d1
	beq.s .io_flush_timing
	cmpi.w #$0004,d1
	blo.s .io_timing_synced
	cmpi.w #$0007,d1
	bhi.s .io_timing_synced
.io_flush_timing:
	; Preserve the write value/address while committing all cycles that
	; precede this timing-sensitive access. Clearing gb_step_cycles prevents
	; the chain stub from charging this instruction a second time.
	movem.l d0-d2/a0,-(sp)
	move.b #1,gb_defer_irq
	bsr.w gb_tick
	clr.b gb_defer_irq
	move.b #1,gb_force_tick
	clr.b gb_step_cycles
	movem.l (sp)+,d0-d2/a0
	bra.s .io_timing_synced
.io_flush_irq_timing:
	bsr.w gb_irq_write_barrier
.io_timing_synced:
	lea gb_io,a0
	moveq #0,d2
	move.b (a0,d1.w),d2
	cmpi.w #$0004,d1
	bne.s .not_div_write
	; Resetting DIV while the selected timer input is high creates a falling
	; edge and clocks TIMA once.
	movem.l d0-d4/a1,-(sp)
	moveq #0,d3
	move.b gb_io+$04,d3
	lsl.w #8,d3
	or.w gb_div_accum,d3
	moveq #0,d2
	move.b gb_io+$07,d2
	bsr.w gb_timer_input_high
	tst.w d4
	beq.s .div_no_timer_glitch
	bsr.w gb_timer_glitch_increment
.div_no_timer_glitch:
	movem.l (sp)+,d0-d4/a1
	clr.b d0
	clr.w gb_div_accum
.not_div_write:
	cmpi.w #$0007,d1
	bne.s .not_tac_write
	; TAC mux changes can likewise create a falling edge. The write drives the
	; bus four T-cycles before this instruction-level service is entered.
	movem.l d0-d4/a1,-(sp)
	moveq #0,d3
	move.b gb_io+$04,d3
	lsl.w #8,d3
	or.w gb_div_accum,d3
	subq.w #4,d3
	bsr.w gb_timer_input_high        ; d2 already contains old TAC
	tst.w d4
	beq.s .tac_no_timer_glitch
	moveq #0,d2
	move.b d0,d2
	bsr.w gb_timer_input_high
	tst.w d4
	bne.s .tac_no_timer_glitch
	bsr.w gb_timer_glitch_increment
	cmpi.w #4,gb_timer_accum
	bne.s .tac_no_timer_glitch
	; The edge was four T-cycles ago, so an overflow reloads now.
	clr.w gb_timer_accum
	move.b gb_io+$06,d4
	move.b d4,gb_io+$05
	bset #2,gb_io+$0F
	move.b #1,gb_timer_reloaded
.tac_no_timer_glitch:
	movem.l (sp)+,d0-d4/a1
.not_tac_write:
	cmpi.w #$0044,d1
	bne.s .not_ly_write
	clr.b d0
	clr.w gb_ly_accum
.not_ly_write:
	cmpi.w #$0005,d1
	bne.s .not_tima_write
	tst.b gb_timer_reloaded
	bne.w .io_done                    ; TIMA write on reload cycle is ignored
	clr.w gb_timer_accum              ; earlier overflow-window write cancels reload
.not_tima_write:
	cmpi.w #$0006,d1
	bne.s .not_tma_write
	tst.b gb_timer_reloaded
	beq.s .not_tma_write
	move.b d0,gb_io+$05               ; reload-cycle TMA write also changes TIMA
.not_tma_write:
	cmpi.w #$0044,d1
	beq.w .io_done
	cmpi.w #$0041,d1
	bne.s .not_stat_write
	andi.b #$78,d0
	move.b d2,-(sp)
	andi.b #7,d2
	or.b d2,d0
	move.b (sp)+,d2
.not_stat_write:
	move.b d0,(a0,d1.w)
	; Optional test-only instantaneous serial peer. No instructions or RAM
	; accesses from this observer are assembled into normal game builds.
	ifd GB2MD_TEST_SERIAL
	cmpi.w #2,d1
	bne.s .serial_probe_done
	move.b d0,d2
	andi.b #$81,d2
	cmpi.b #$81,d2
	bne.s .serial_probe_done
	movem.l d0-d2/a0,-(sp)
	moveq #0,d2
	move.w $FFC600,d2
	cmpi.w #512,d2
	bhs.s .serial_probe_overflow
	lea $FFD000,a0
	move.b gb_io+1,(a0,d2.w)
	addq.w #1,$FFC600
	bra.s .serial_probe_recorded
.serial_probe_overflow:
	move.b #1,$FFC602
.serial_probe_recorded:
	movem.l (sp)+,d0-d2/a0
	andi.b #$7F,d0
	move.b d0,gb_io+2
.serial_probe_done:
	endif
	cmpi.w #$0040,d1
	beq.s .sync_stat_write
	cmpi.w #$0041,d1
	beq.s .sync_stat_write
	cmpi.w #$0045,d1
	bne.s .stat_write_done
.sync_stat_write:
	bsr.w gb_stat_sync
.stat_write_done:
	cmpi.w #$000F,d1
	bne.s .not_if_write
	andi.b #$1F,(a0,d1.w)
.not_if_write:
	cmpi.w #$0046,d1
	bne.w .not_oam_dma
	; Queue a two-M-cycle startup/restart. The old transfer remains active
	; until gb_dma_advance starts the replacement, one byte per M-cycle.
	move.b d0,gb_dma_request_source
	move.b #1,gb_dma_requested
	bra.w .io_done
.not_oam_dma:
	cmp.b d2,d0
	beq.s .io_done
	cmpi.w #$0040,d1
	beq.s .mark_video_dirty
	cmpi.w #$0042,d1
	beq.s .mark_video_dirty
	cmpi.w #$0043,d1
	beq.s .mark_video_dirty
	cmpi.w #$0047,d1
	blo.s .check_lcdc_enable
	cmpi.w #$004B,d1
	bls.s .mark_video_dirty
	bra.s .check_lcdc_enable
.mark_video_dirty:
	move.b #1,gb_video_dirty
	move.b #1,gb_bg_dirty
.check_lcdc_enable:
	cmpi.w #$0040,d1
	bne.s .io_done
	btst #7,d0
	beq.s .io_done
	btst #7,d2
	bne.s .io_done
	; LCD enable is a frame boundary for software that builds a complete
	; screen while the DMG LCD is disabled.
	bsr.w gb_render_frame
	clr.b gb_video_dirty
.io_done:
	rts
.hram:
	subi.w #$FF80,d1
	lea gb_hram,a0
	move.b d0,(a0,d1.w)
	rts

; IF/IE writes must arbitrate at the following instruction, not at a later
; scheduler batch. Commit prior cycles before the write, defer service until
; the opcode completes, and preserve temporaries used by word/stack stores.
gb_irq_write_barrier:
	tst.b gb_irq_entry
	beq.s .normal_write
	; The interrupt-entry sequencer already charged this bus phase.
	move.b #1,gb_force_tick
	rts
.normal_write:
	movem.l d0-d6/a0-a1,-(sp)
	moveq #0,d0
	move.b gb_defer_irq,d0
	move.w d0,-(sp)
	move.b #1,gb_defer_irq
	bsr.w gb_tick
	move.w (sp)+,d0
	move.b d0,gb_defer_irq
	move.b #1,gb_force_tick
	clr.b gb_step_cycles
	movem.l (sp)+,d0-d6/a0-a1
	rts

; d3.w = divider, d2.b = TAC; returns d4.w nonzero when timer input is high.
gb_timer_input_high:
	moveq #0,d4
	btst #2,d2
	beq.s .timer_input_done
	andi.w #3,d2
	add.w d2,d2
	lea .timer_input_bits(pc),a1
	move.w (a1,d2.w),d4
	and.w d3,d4
.timer_input_done:
	rts
.timer_input_bits:
	dc.w 512,8,32,128

; Clock TIMA once for a DIV/TAC-induced falling edge.
gb_timer_glitch_increment:
	tst.w gb_timer_accum
	bne.s .timer_glitch_done
	addq.b #1,gb_io+$05
	bne.s .timer_glitch_done
	move.w #4,gb_timer_accum
.timer_glitch_done:
	rts

; One translated instruction has completed. Generated blocks publish their
; LR35902 T-cycle cost in gb_step_cycles, including conditional taken costs.
; Read-only polling loops call this helper after their taken branch. It charges
; the branch normally, then advances in sub-scanline chunks until an enabled
; VBlank interrupt is serviced. If VBlank cannot wake the loop, it returns
; immediately and ordinary translated polling continues.
gb_idle_wait:
	; Legacy traces classified arbitrary hardware polls as VBlank waits.
	; Keep those artifacts executable, but never skip their observed phases.
	jsr gb_tick
	rts

; New traces call this only for known WRAM/HRAM flag polling loops.
gb_idle_flag_wait:
	jsr gb_tick                       ; flush the branch and its basic block
	btst #1,gb_ie
	bne.w .idle_fallback
	tst.b gb_ime
	beq.w .idle_fallback
	btst #0,gb_ie
	beq.w .idle_fallback
	btst #7,gb_io+$40
	beq.w .idle_fallback
	btst #2,gb_io+$07
	bne.w .idle_fallback
	; Jump directly to the next LY=144 boundary.
	moveq #0,d0
	move.b gb_io+$44,d0
	cmpi.w #144,d0
	blo.s .idle_before_vblank
	move.w #298,d1                  ; 154-line wrap plus target 144
	sub.w d0,d1
	bra.s .idle_lines_ready
.idle_before_vblank:
	move.w #144,d1
	sub.w d0,d1
.idle_lines_ready:
	mulu #456,d1
	moveq #0,d0
	move.w gb_ly_accum,d0
	sub.l d0,d1
	move.l d1,d2
	bsr.w gb_add_idle_cycles
	clr.w gb_ly_accum
	move.b #144,gb_io+$44
	bset #0,gb_io+$0F
	tst.b gb_video_dirty
	beq.s .idle_no_render
	bsr.w gb_render_frame
	clr.b gb_video_dirty
.idle_no_render:
	clr.b gb_step_cycles
	jsr gb_tick                       ; service the real VBlank IRQ
.idle_fallback:
.idle_done:
	rts

; A halted SM83 consumes no instructions while peripherals continue. Calling
; gb_tick once per four T-cycles is functionally useful but prohibitively slow
; on the 68000. With TIMA disabled, advance directly to VBlank. With TIMA
; active, advance through gb_tick to the earlier of VBlank or the next enabled
; timer interrupt. No source instruction exists inside either interval.
gb_halt_wait:
	tst.b gb_halted
	beq.w .halt_wait_done
	; STAT may wake the CPU before VBlank. Stop at the next mode edge.
	btst #1,gb_ie
	bne.w .halt_stat_wait
	btst #0,gb_ie
	beq.w .halt_wait_done
	btst #7,gb_io+$40
	beq.w .halt_wait_done
	btst #2,gb_io+$07
	beq.w .halt_direct_vblank
	; A running timer still needs every divider edge and overflow/reload event.
	; Advance through the normal event-driven tick path. If its IRQ is enabled,
	; stop at the reload that raises IF; otherwise VBlank is the next modelled
	; wake event. Word-sized cycle input bounds each chunk to 32760 T-cycles.
	addq.l #1,gb_halt_fast_forward_count
.halt_timer_batch:
	moveq #0,d0
	move.b gb_io+$44,d0
	cmpi.w #144,d0
	blo.s .halt_timer_before_vblank
	move.w #298,d1
	sub.w d0,d1
	bra.s .halt_timer_lines_ready
.halt_timer_before_vblank:
	move.w #144,d1
	sub.w d0,d1
.halt_timer_lines_ready:
	mulu #456,d1
	moveq #0,d0
	move.w gb_ly_accum,d0
	sub.l d0,d1
	; d1.l is cycles to VBlank. When the timer IRQ is enabled, derive cycles
	; to its next overflow reload from the divider phase and TIMA value, then
	; use the earlier event. A pending reload already has an exact countdown.
	btst #2,gb_ie
	beq.s .halt_timer_target_ready
	moveq #0,d2
	move.w gb_timer_accum,d2
	bne.s .halt_timer_compare_target
	move.w #256,d5
	moveq #0,d3
	move.b gb_io+$05,d3
	sub.w d3,d5                    ; falling edges through the overflow edge
	moveq #0,d3
	move.b gb_io+$07,d3
	andi.w #3,d3
	add.w d3,d3
	lea gb_timer_periods(pc),a0
	moveq #0,d4
	move.w (a0,d3.w),d4            ; selected falling-edge period
	moveq #0,d3
	move.b gb_io+$04,d3
	lsl.w #8,d3
	or.w gb_div_accum,d3           ; current 16-bit divider phase
	move.l d4,d2
	move.w d4,d0
	subq.w #1,d0
	and.w d3,d0
	sub.w d0,d2                    ; cycles to the next falling edge
	subq.w #1,d5
	mulu d4,d5
	add.l d5,d2
	addq.l #4,d2                   ; overflow reload raises the timer IF bit
.halt_timer_compare_target:
	cmp.l d1,d2
	bhs.s .halt_timer_target_ready
	move.l d2,d1
.halt_timer_target_ready:
	clr.b gb_step_cycles
	cmpi.l #32760,d1
	bls.s .halt_timer_last_chunk
	move.w #32760,d7
	bra.s .halt_timer_chunk_ready
.halt_timer_last_chunk:
	move.w d1,d7
.halt_timer_chunk_ready:
	bsr.w gb_tick
	tst.b gb_halted
	bne.w .halt_timer_batch
	bra.w .halt_wait_done
.halt_direct_vblank:
	addq.l #1,gb_halt_fast_forward_count
	moveq #0,d0
	move.b gb_io+$44,d0
	cmpi.w #144,d0
	blo.s .halt_before_vblank
	move.w #298,d1                  ; wrap at 154, then advance to line 144
	sub.w d0,d1
	bra.s .halt_lines_ready
.halt_before_vblank:
	move.w #144,d1
	sub.w d0,d1
.halt_lines_ready:
	mulu #456,d1
	moveq #0,d0
	move.w gb_ly_accum,d0
	sub.l d0,d1
	move.l d1,d2
	bsr.w gb_add_idle_cycles
	clr.w gb_ly_accum
	move.b #144,gb_io+$44
	bset #0,gb_io+$0F
	tst.b gb_video_dirty
	beq.s .halt_no_render
	bsr.w gb_render_frame
	clr.b gb_video_dirty
.halt_no_render:
	clr.b gb_step_cycles
	bsr.w gb_tick                    ; wake and, when IME is set, enter VBlank
.halt_wait_done:
	rts
.halt_stat_wait:
	btst #7,gb_io+$40
	beq.s .halt_wait_done
	; A timer may wake earlier; keep its conservative path for now.
	btst #2,gb_io+$07
	bne.s .halt_wait_done
	tst.w gb_timer_accum
	bne.s .halt_wait_done
	move.w #80,d0
	cmp.w gb_ly_accum,d0
	bhi.s .halt_stat_target
	move.w #252,d0
	cmp.w gb_ly_accum,d0
	bhi.s .halt_stat_target
	move.w #456,d0
.halt_stat_target:
	sub.w gb_ly_accum,d0
	move.w d0,d7
	clr.b gb_step_cycles
	bsr.w gb_tick
	rts

; d0.b = LY value polled by a read-only loop. This variant is used while IME
; is disabled during LCD setup/DMA waits, so no program-visible instructions
; exist between the current and requested scanline.
gb_idle_ly:
	move.w d0,-(sp)
	jsr gb_tick                       ; flush the branch and its basic block
	move.w (sp)+,d0
	cmp.b gb_io+$44,d0
	beq.w .idle_ly_done_early
	; STAT-enabled polling cannot skip mode/coincidence transitions.
	move.b gb_io+$41,d1
	andi.b #$78,d1
	bne.w .idle_ly_fallback
	tst.b gb_ime
	bne.w .idle_ly_fallback
	btst #7,gb_io+$40
	beq.w .idle_ly_fallback
	btst #2,gb_io+$07
	bne.w .idle_ly_fallback
	moveq #0,d1
	move.b gb_io+$44,d1
	cmp.b d0,d1
	blo.s .idle_ly_no_wrap
	move.w #154,d2
	sub.w d1,d2
	add.w d0,d2
	bra.s .idle_ly_lines_ready
.idle_ly_no_wrap:
	move.w d0,d2
	sub.w d1,d2
.idle_ly_lines_ready:
	mulu #456,d2
	moveq #0,d1
	move.w gb_ly_accum,d1
	sub.l d1,d2
	bsr.w gb_add_idle_cycles
	clr.w gb_ly_accum
	move.b d0,gb_io+$44
	cmpi.b #144,d0
	blo.s .idle_ly_done
	bset #0,gb_io+$0F
	tst.b gb_video_dirty
	beq.s .idle_ly_done
	bsr.w gb_render_frame
	clr.b gb_video_dirty
.idle_ly_done:
	clr.b gb_step_cycles
	jsr gb_tick
	rts
.idle_ly_fallback:
	rts
.idle_ly_done_early:
	rts

; Add d2.l idle T-cycles to the cycle counter and DIV state. TIMA-enabled
; waits take the conservative fallback paths above.
gb_add_idle_cycles:
	add.l d2,gb_cycle_counter
	moveq #0,d3
	move.w gb_div_accum,d3
	add.l d2,d3
	move.l d3,d1
	andi.l #$000000FF,d3
	move.w d3,gb_div_accum
	lsr.l #8,d1
	add.b d1,gb_io+$04
	rts

; Baseline fixed mode timing: OAM 80 dots, transfer 172, HBlank 204.
; Variable mode-3 stalls, LCD startup and DMG STAT-write glitch remain open.
; Preserve scheduler/write operands; STAT requests on the OR-line rising edge.
gb_stat_sync:
	movem.l d0-d3,-(sp)
	moveq #0,d0
	btst #7,gb_io+$40
	beq.s .stat_mode_ready
	moveq #1,d0
	cmpi.b #144,gb_io+$44
	bhs.s .stat_mode_ready
	moveq #2,d0
	cmpi.w #80,gb_ly_accum
	blo.s .stat_mode_ready
	moveq #3,d0
	cmpi.w #252,gb_ly_accum
	blo.s .stat_mode_ready
	moveq #0,d0
.stat_mode_ready:
	moveq #0,d1
	move.b gb_io+$41,d1
	andi.b #$78,d1
	or.b d0,d1
	move.b gb_io+$44,d2
	cmp.b gb_io+$45,d2
	bne.s .stat_no_coincidence
	ori.b #4,d1
.stat_no_coincidence:
	move.b d1,gb_io+$41
	moveq #0,d3
	btst #7,gb_io+$40
	beq.s .stat_line_ready
	btst #2,d1
	beq.s .stat_mode_source
	btst #6,d1
	bne.s .stat_line_high
.stat_mode_source:
	cmpi.b #3,d0
	beq.s .stat_line_ready
	addq.w #3,d0
	btst d0,d1
	beq.s .stat_line_ready
.stat_line_high:
	moveq #1,d3
	tst.b gb_stat_line
	bne.s .stat_line_ready
	bset #1,gb_io+$0F
.stat_line_ready:
	move.b d3,gb_stat_line
	movem.l (sp)+,d0-d3
	rts

; Fetch one byte for an already compiled, uniform-opcode variant guard.
; d1.w is the logical address. Preserve temporaries, charge one M-cycle,
; defer arbitration through the instruction, and return the bus byte in d0.
gb_fetch_read8:
	movem.l d1-d6/a0-a1,-(sp)
	moveq #0,d0
	move.b gb_defer_irq,d0
	move.w d0,-(sp)
	move.b #1,gb_defer_irq
	move.b #4,gb_step_cycles
	bsr.w gb_tick
	clr.b gb_step_cycles
	move.l 2(sp),d1
	bsr.w gb_read8
	move.w (sp)+,d1
	move.b d1,gb_defer_irq
	movem.l (sp)+,d1-d6/a0-a1
	move.b #1,gb_force_tick
	rts

gb_tick:
	moveq #0,d6
	move.b gb_step_cycles,d6
	add.w d7,d6
	clr.w d7
	add.w gb_cycle_batch,d6
	clr.w gb_cycle_batch
	add.l d6,gb_cycle_counter
	bsr.w gb_dma_advance
	; Preserve the pre-step divider phase. TIMA is driven by falling edges of
	; selected divider bits, not an independent period accumulator.
	moveq #0,d4
	move.b gb_io+$04,d4
	lsl.w #8,d4
	or.w gb_div_accum,d4
	moveq #0,d0
	move.w gb_div_accum,d0
	add.w d6,d0
	move.w d0,d1
	andi.w #$00FF,d0
	move.w d0,gb_div_accum
	lsr.w #8,d1
	add.b d1,gb_io+$04
	; Large event-batched waits can span many scanlines. Consume each crossed
	; boundary so LY wrapping, VBlank, and dirty-frame rendering still happen
	; at the same emulated boundary rather than once per host-side tick call.
	moveq #0,d0
	move.w gb_ly_accum,d0
	add.w d6,d0
.scanline_loop:
	; A batch may cross mode edges within a line without crossing its end.
	cmpi.w #80,gb_ly_accum
	bhs.s .stat_after_mode2
	cmpi.w #80,d0
	blo.s .stat_after_mode2
	move.w #80,gb_ly_accum
	bsr.w gb_stat_sync
.stat_after_mode2:
	cmpi.w #252,gb_ly_accum
	bhs.s .stat_after_mode3
	cmpi.w #252,d0
	blo.s .stat_after_mode3
	move.w #252,gb_ly_accum
	bsr.w gb_stat_sync
.stat_after_mode3:
	cmpi.w #456,d0
	blo.s .scanlines_done
	subi.w #456,d0
	addq.b #1,gb_io+$44
	cmpi.b #154,gb_io+$44
	blo.s .ly_in_range
	clr.b gb_io+$44
.ly_in_range:
	clr.w gb_ly_accum
	bsr.w gb_stat_sync
	cmpi.b #144,gb_io+$44
	bne.s .no_scanline
	bset #0,gb_io+$0F
	btst #7,gb_io+$40
	beq.s .no_scanline
	tst.b gb_video_dirty
	beq.s .no_scanline
	bsr.w gb_render_frame
	clr.b gb_video_dirty
.no_scanline:
	bra.w .scanline_loop
.scanlines_done:
	move.w d0,gb_ly_accum
	; Event-driven timer: advance directly to the next four-cycle reload or
	; selected-divider falling edge. This is cycle-exact without iterating over
	; every T-cycle in timer-enabled games.
	clr.b gb_timer_reloaded
	move.w d6,d5                    ; remaining T-cycles
	beq.w .timer_done
.timer_event:
	tst.w gb_timer_accum
	beq.s .timer_select_edge
	moveq #0,d0
	move.w gb_timer_accum,d0
	cmp.w d5,d0
	bhi.w .timer_pending_later
	sub.w d0,d5
	add.w d0,d4
	clr.w gb_timer_accum
	move.b gb_io+$06,d0
	move.b d0,gb_io+$05
	bset #2,gb_io+$0F
	move.b #1,gb_timer_reloaded
	tst.w d5
	beq.s .timer_done
	clr.b gb_timer_reloaded         ; later cycles leave the reload cycle
.timer_select_edge:
	btst #2,gb_io+$07
	beq.s .timer_no_more_events
	moveq #0,d0
	move.b gb_io+$07,d0
	andi.w #3,d0
	add.w d0,d0
	lea gb_timer_periods(pc),a0
	move.w (a0,d0.w),d1            ; selected falling-edge period
	move.w d1,d2
	subq.w #1,d2
	and.w d4,d2                    ; phase within the period
	move.w d1,d0
	sub.w d2,d0                    ; cycles until next falling edge
	cmp.w d5,d0
	bhi.s .timer_no_more_events
	sub.w d0,d5
	add.w d0,d4
	clr.b gb_timer_reloaded
	addq.b #1,gb_io+$05
	bne.s .timer_edge_complete
	move.w #4,gb_timer_accum
.timer_edge_complete:
	tst.w d5
	bne.w .timer_event
	bra.s .timer_done
.timer_pending_later:
	sub.w d5,gb_timer_accum
.timer_no_more_events:
	clr.b gb_timer_reloaded
.timer_done:
	; EI takes effect only after the following translated instruction.
	tst.b gb_ei_delay
	beq.s .check_irq
	subq.b #1,gb_ei_delay
	bne.s .check_irq
	move.b #1,gb_ime
.check_irq:
	tst.b gb_bank_dirty
	beq.s .bank_identity_ready
	clr.b gb_bank_dirty
	bsr.w gb_normalize_bank
.bank_identity_ready:
	tst.b gb_defer_irq
	bne.w .tick_done
	move.b gb_io+$0F,d0
	and.b gb_ie,d0
	andi.b #$1F,d0
	beq.w .tick_done
	clr.b gb_halted
	tst.b gb_ime
	beq.w .tick_done
	clr.b gb_ime
	move.b #1,gb_irq_entry
	move.b #1,gb_defer_irq
	move.w gb_pc,d4
	; Two idle M-cycles followed by the high-byte stack-write M-cycle.
	moveq #12,d0
	bsr.w gb_irq_advance
	move.w gb_sp,d1
	subq.w #1,d1
	move.w d1,gb_sp
	move.w d4,d0
	lsr.w #8,d0
	movem.l d3-d4,-(sp)
	bsr.w gb_write8
	movem.l (sp)+,d3-d4
	; IE can change during that push: recompute priority before ack.
	move.b gb_io+$0F,d0
	and.b gb_ie,d0
	andi.b #$1F,d0
	moveq #0,d3                    ; cancellation enters fixed ROM $0000
	tst.b d0
	beq.s .irq_selected
	moveq #1,d2
	move.w #$0040,d3
.find_irq:
	move.b d0,d1
	and.b d2,d1
	bne.s .take_irq
	lsl.b #1,d2
	addq.w #8,d3
	bra.s .find_irq
.take_irq:
	not.b d2
	and.b d2,gb_io+$0F
.irq_selected:
	moveq #4,d0
	bsr.w gb_irq_advance
	move.w gb_sp,d1
	subq.w #1,d1
	move.w d1,gb_sp
	move.w d4,d0
	movem.l d3-d4,-(sp)
	bsr.w gb_write8                 ; low-byte IE write cannot change selection
	movem.l (sp)+,d3-d4
	moveq #4,d0
	bsr.w gb_irq_advance            ; final vector-load M-cycle (20T total)
	clr.b gb_irq_entry
	clr.b gb_defer_irq
	clr.w gb_bank
	move.w d3,gb_pc
.tick_done:
	rts
; Charge one interrupt-entry phase without recursive IRQ arbitration.
; d0.w is T-cycles. Keep stack-pointer/vector temporaries live across gb_tick.
gb_irq_advance:
	movem.l d0-d6/a0-a1,-(sp)
	move.b d0,gb_step_cycles
	move.b #1,gb_defer_irq
	bsr.w gb_tick
	clr.b gb_step_cycles
	movem.l (sp)+,d0-d6/a0-a1
	rts
gb_timer_periods:
	dc.w 1024,16,64,256

; Advance OAM DMA by d6.w T-cycles. Startup/restart edges are processed one
; M-cycle at a time; once no pipeline transition is pending, contiguous bytes
; in the scheduler batch are copied as one bounded run.
gb_dma_advance:
	tst.b gb_dma_active
	bne.s .dma_has_work
	tst.b gb_dma_starting
	bne.s .dma_has_work
	tst.b gb_dma_requested
	beq.w .dma_advance_done
.dma_has_work:
	movem.l d0-d5/a0-a1,-(sp)
	move.w d6,d5
	lsr.w #2,d5
	beq.w .dma_restore

.dma_event_loop:
	tst.w d5
	beq.w .dma_restore
	tst.b gb_dma_starting
	bne.s .dma_single_cycle
	tst.b gb_dma_requested
	bne.s .dma_single_cycle
	tst.b gb_dma_active
	beq.w .dma_restore
	move.w #160,d3
	sub.w gb_dma_index,d3
	cmp.w d5,d3
	bls.s .dma_bulk_count_ready
	move.w d5,d3
.dma_bulk_count_ready:
	bsr.w .dma_copy_run
	sub.w d3,d5
	bra.w .dma_event_loop

.dma_single_cycle:
	tst.b gb_dma_active
	beq.s .dma_single_no_copy
	moveq #1,d3
	bsr.w .dma_copy_run
.dma_single_no_copy:
	tst.b gb_dma_starting
	beq.s .dma_single_no_start
	move.b gb_dma_start_source,gb_dma_source
	clr.w gb_dma_index
	move.b #1,gb_dma_active
	clr.b gb_dma_starting
.dma_single_no_start:
	tst.b gb_dma_requested
	beq.s .dma_single_done
	move.b gb_dma_request_source,gb_dma_start_source
	move.b #1,gb_dma_starting
	clr.b gb_dma_requested
.dma_single_done:
	subq.w #1,d5
	bra.w .dma_event_loop

; Copy d3.w consecutive bytes from the current source/index. d3 is preserved.
.dma_copy_run:
	moveq #0,d1
	move.b gb_dma_source,d1
	lsl.w #8,d1
	add.w gb_dma_index,d1
	move.w d1,d2
	lsr.w #8,d2
	cmpi.w #$00C0,d2
	bhs.w .dma_run_wram
	cmpi.w #$00A0,d2
	bhs.w .dma_run_eram
	cmpi.w #$0080,d2
	bhs.s .dma_run_vram
	cmpi.w #$0040,d2
	bhs.s .dma_run_romx
	lea gb_cart_rom,a0
	cmpi.b #$01,gb_mapper_kind
	blo.s .dma_run_rom0_ready
	cmpi.b #$03,gb_mapper_kind
	bhi.s .dma_run_rom0_ready
	tst.b gb_mbc1_mode
	beq.s .dma_run_rom0_ready
	moveq #0,d2
	move.b gb_mbc1_upper,d2
	lsl.l #8,d2
	lsl.l #8,d2
	lsl.l #3,d2
	adda.l d2,a0
.dma_run_rom0_ready:
	adda.w d1,a0
	bra.w .dma_run_copy
.dma_run_romx:
	moveq #0,d2
	move.w gb_rom_bank,d2
	lsl.l #8,d2
	lsl.l #6,d2
	subi.w #$4000,d1
	lea gb_cart_rom,a0
	adda.l d2,a0
	adda.w d1,a0
	bra.s .dma_run_copy
.dma_run_vram:
	subi.w #$8000,d1
	lea gb_vram,a0
	adda.w d1,a0
	bra.s .dma_run_copy
.dma_run_eram:
	tst.b gb_ram_enabled
	beq.s .dma_run_fill_ff
	cmpi.b #4,gb_ram_bank
	bhs.s .dma_run_fill_ff
	subi.w #$A000,d1
	moveq #0,d2
	move.b gb_ram_bank,d2
	lsl.l #8,d2
	lsl.l #5,d2
	lea gb_eram,a0
	adda.l d2,a0
	adda.w d1,a0
	bra.s .dma_run_copy
.dma_run_wram:
	subi.w #$C000,d1
	andi.w #$1FFF,d1
	lea gb_wram,a0
	adda.w d1,a0
.dma_run_copy:
	lea gb_oam,a1
	adda.w gb_dma_index,a1
	move.w d3,d4
	subq.w #1,d4
.dma_run_copy_loop:
	move.b (a0)+,(a1)+
	dbf d4,.dma_run_copy_loop
	bra.s .dma_run_finish
.dma_run_fill_ff:
	lea gb_oam,a1
	adda.w gb_dma_index,a1
	move.w d3,d4
	subq.w #1,d4
	moveq #-1,d0
.dma_run_fill_loop:
	move.b d0,(a1)+
	dbf d4,.dma_run_fill_loop
.dma_run_finish:
	add.w d3,gb_dma_index
	move.b #1,gb_video_dirty
	move.b #1,gb_oam_dirty
	cmpi.w #160,gb_dma_index
	blo.s .dma_run_return
	clr.b gb_dma_active
.dma_run_return:
	rts
.dma_restore:
	movem.l (sp)+,d0-d5/a0-a1
.dma_advance_done:
	rts
; Convert live DMG tile data and the selected 32x32 BG map into Genesis VRAM.
; Plane A is at $C000; tile patterns occupy $0000-$2FFF.  The routine runs at
; emulated VBlank and therefore displays original game state, not baked assets.
gb_render_frame:
	ifd GB2MD_SHOW_FPS
	move.b #1,gb_fps_vdp_busy
	endif
	addq.l #1,gb_render_count
	movem.l d0-d7/a0-a2,-(sp)
	; OAM changes are common during gameplay and do not require reconverting
	; 12 KiB of patterns plus the full background map. Keep that work behind
	; separate VRAM/background-state dirtiness flags.
	tst.b gb_vram_dirty
	bne.w .render_background
	tst.b gb_bg_dirty
	beq.w .sprite_section
.render_background:
	addq.l #1,gb_full_render_count
	; Scroll, palette and LCDC changes require a map/VDP-state refresh, but the
	; expensive 640-pattern conversion is only needed after actual VRAM writes.
	tst.b gb_vram_dirty
	beq.w .render_tilemap
	; Convert only source patterns changed since the previous render. Every
	; dirty BG tile is uploaded to its native index; tiles 0-255 also update
	; their transparent sprite copy at Genesis tile IDs 384-639.
	lea gb_tile_dirty,a2
	moveq #0,d6
	move.w #383,d7
.dirty_tile:
	tst.b (a2)+
	beq.s .dirty_tile_next
	clr.b -1(a2)
	moveq #0,d5
	bsr.w .upload_dirty_tile
	cmpi.w #256,d6
	bhs.s .dirty_tile_next
	move.w #384,d5
	bsr.w .upload_dirty_tile
.dirty_tile_next:
	addq.w #1,d6
	dbf d7,.dirty_tile
	bra.w .render_tilemap

; Upload source tile d6.w to Genesis tile (d6+d5). d6/d7/a2 are preserved.
.upload_dirty_tile:
	move.w d6,d0
	add.w d5,d0
	lsl.w #5,d0
	moveq #0,d1
	move.w d0,d1
	move.l d1,d2
	andi.l #$00003FFF,d2
	swap d2
	andi.l #$0000C000,d1
	lsr.l #8,d1
	lsr.l #6,d1
	or.l d1,d2
	ori.l #$40000000,d2
	move.l d2,$C00004
	move.w d6,d0
	lsl.w #4,d0
	lea gb_vram,a0
	adda.w d0,a0
	lea gb_2bpp_nibble_table,a1
	moveq #7,d4
.dirty_tile_row:
	moveq #0,d0
	moveq #0,d1
	move.b (a0)+,d0                 ; low bitplane
	move.b (a0)+,d1                 ; high bitplane
	move.w d1,d2
	andi.w #$00F0,d2
	move.w d0,d3
	lsr.w #4,d3
	or.w d3,d2
	add.w d2,d2
	move.w (a1,d2.w),$C00000       ; GB color 0 remains transparent
	andi.w #$000F,d0
	andi.w #$000F,d1
	lsl.w #4,d1
	or.w d0,d1
	add.w d1,d1
	move.w (a1,d1.w),$C00000
	dbf d4,.dirty_tile_row
	rts

.render_tilemap:
	; Reset already clears VDP memory. On the first background render, replace
	; Plane A's tile-zero cells with the permanently transparent tile 640 so
	; later conversion of GB tile zero cannot leak outside the viewport.
	; Subsequent refreshes rewrite the complete viewport rows and need no clear.
	tst.b gb_plane_initialized
	bne.s .plane_initialized
	move.l #$40000003,$C00004
	move.w #640,d0
	move.w #2047,d7
.clear_plane_a:
	move.w d0,$C00000
	dbf d7,.clear_plane_a
	; Plane A occupies C000-CFFF; the unscrolled Genesis window uses D000-DFFF.
	move.l #$50000003,$C00004
	move.w #2047,d7
.clear_window_plane:
	move.w d0,$C00000
	dbf d7,.clear_window_plane
	move.b #1,gb_plane_initialized
.plane_initialized:
	; A full-screen DMG window replaces the BG with unscrolled window data.
	; Partial windows still require viewport composition/raster support.
	clr.b gb_window_full
	btst #5,gb_io+$40
	beq.s .window_selection_done
	tst.b gb_io+$4A
	bne.s .window_selection_done
	cmpi.b #7,gb_io+$4B
	bne.s .window_selection_done
	move.b #1,gb_window_full
.window_selection_done:
	; Place the 20x18-tile DMG viewport at (10,5).
	move.l #$42940003,$C00004       ; Plane A cell (10,5)
	lea gb_vram+$1800,a2
	tst.b gb_window_full
	beq.s .select_bg_map
	btst #6,gb_io+$40
	beq.s .map_selected
	lea gb_vram+$1C00,a2
	bra.s .map_selected
.select_bg_map:
	btst #3,gb_io+$40
	beq.s .map_selected
	lea gb_vram+$1C00,a2
.map_selected:
	moveq #0,d2
	moveq #0,d4
	tst.b gb_window_full
	bne.s .map_scroll_selected
	move.b gb_io+$42,d2
	lsr.w #3,d2
	moveq #0,d4
	move.b gb_io+$43,d4
	lsr.w #3,d4
.map_scroll_selected:
	moveq #0,d6
	moveq #17,d7
.map_row:
	move.w d6,d0
	add.w d2,d0
	andi.w #31,d0
	lsl.w #5,d0
	lea (a2,d0.w),a1
	move.w d4,d5
	moveq #19,d3
.map_col:
	moveq #0,d0
	andi.w #31,d5
	move.b (a1,d5.w),d0
	btst #4,gb_io+$40
	bne.s .tile_unsigned
	tst.b d0
	bmi.s .tile_unsigned
	addi.w #256,d0
.tile_unsigned:
	ori.w #$8000,d0               ; BG pixels 1-3 cover low-priority GB sprites
	move.w d0,$C00000
	addq.w #1,d5
	dbf d3,.map_col
	moveq #43,d3                    ; advance to x=10 of the next 64-cell row
.map_pad:
	move.w #640,$C00000
	dbf d3,.map_pad
	addq.w #1,d6
	dbf d7,.map_row
	bsr.w .render_partial_window
	; Palette entry 0 stays transparent. Plane A pixels 1-3 use the BGP
	; mappings for GB colours 1-3; Plane B's solid colour-4 tile supplies the
	; viewport backing for transparent GB colour 0. This lets a low-priority
	; sprite appear over colour 0 while remaining behind colours 1-3.
	move.l #$C0000000,$C00004
	move.w #0,$C00000
	moveq #0,d0
	move.b gb_io+$47,d0
	move.w d0,d5
	lsr.w #2,d0
	lea .dmg_shades(pc),a0
	moveq #2,d7
.palette:
	move.w d0,d1
	andi.w #3,d1
	add.w d1,d1
	move.w (a0,d1.w),$C00000
	lsr.w #2,d0
	dbf d7,.palette
	move.l #$C0080000,$C00004
	andi.w #3,d5
	add.w d5,d5
	move.w (a0,d5.w),$C00000
	; Palette 1 colors the shell. Palettes 2 and 3 hold both object palettes.
	move.l #$C0200000,$C00004
	move.w #gb_shell0,$C00000
	move.w #gb_shell1,$C00000
	move.w #gb_shell2,$C00000
	move.w #gb_shell3,$C00000
	; Full-screen horizontal scroll table lives at $FC00. Plane A uses -SCX.
	move.l #$7C000003,$C00004
	moveq #0,d0
	tst.b gb_window_full
	bne.s .window_hscroll_ready
	move.b gb_io+$43,d0
	andi.w #7,d0
	neg.w d0
.window_hscroll_ready:
	move.w d0,$C00000
	move.w #0,$C00000
	; Plane A vertical scroll uses SCY.
	move.l #$40000010,$C00004
	moveq #0,d0
	tst.b gb_window_full
	bne.s .window_vscroll_ready
	move.b gb_io+$42,d0
	andi.w #7,d0
.window_vscroll_ready:
	move.w d0,$C00000
	move.w #0,$C00000
.sprite_section:
	; Convert the 40 DMG OAM entries into the Genesis sprite attribute table
	; at $F000. GB coordinates include an (8,16) origin bias; Genesis sprite
	; coordinates include a 128-pixel hardware bias, and the viewport begins
	; at (80,40).
	move.l #$70000003,$C00004
	lea gb_oam,a0
	moveq #1,d6
	moveq #39,d7
.sprite:
	moveq #0,d0
	move.b (a0)+,d0                 ; GB Y
	moveq #0,d1
	move.b (a0)+,d1                 ; GB X
	moveq #0,d2
	move.b (a0)+,d2                 ; tile
	moveq #0,d3
	move.b (a0)+,d3                 ; attributes
	tst.b d0
	beq.s .sprite_hidden
	cmpi.w #160,d0
	bhs.s .sprite_hidden
	tst.b d1
	beq.s .sprite_hidden
	cmpi.w #168,d1
	bhs.s .sprite_hidden
	addi.w #152,d0
	move.w d0,$C00000
	moveq #0,d4
	btst #2,gb_io+$40
	beq.s .sprite_8x8
	ori.w #$0100,d4               ; one tile wide, two tiles high
	andi.w #$00FE,d2
.sprite_8x8:
	addi.w #384,d2
	move.b d6,d4
	tst.w d7
	bne.s .sprite_link_ready
	clr.b d4
.sprite_link_ready:
	move.w d4,$C00000
	ori.w #$4000,d2               ; OBP0 uses Genesis palette 2
	btst #4,d3
	beq.s .sprite_palette_ready
	ori.w #$2000,d2               ; OBP1 uses Genesis palette 3
.sprite_palette_ready:
	btst #5,d3
	beq.s .sprite_no_xflip
	ori.w #$0800,d2
.sprite_no_xflip:
	btst #6,d3
	beq.s .sprite_no_yflip
	ori.w #$1000,d2
.sprite_no_yflip:
	btst #7,d3
	bne.s .sprite_low_priority
	ori.w #$8000,d2
.sprite_low_priority:
	move.w d2,$C00000
	addi.w #200,d1
	move.w d1,$C00000
	bra.s .sprite_next
.sprite_hidden:
	move.w #0,$C00000
	moveq #0,d4
	move.b d6,d4
	tst.w d7
	bne.s .hidden_link_ready
	clr.b d4
.hidden_link_ready:
	move.w d4,$C00000
	move.w #0,$C00000
	move.w #0,$C00000
.sprite_next:
	addq.b #1,d6
	dbf d7,.sprite
	; Palette 2/3 hold OBP0/OBP1. Color zero remains transparent.
	lea .dmg_shades(pc),a0
	move.l #$C0400000,$C00004
	move.w #0,$C00000
	moveq #0,d0
	move.b gb_io+$48,d0
	lsr.w #2,d0
	moveq #2,d7
.obp0:
	move.w d0,d1
	andi.w #3,d1
	add.w d1,d1
	move.w (a0,d1.w),$C00000
	lsr.w #2,d0
	dbf d7,.obp0
	move.l #$C0600000,$C00004
	move.w #0,$C00000
	moveq #0,d0
	move.b gb_io+$49,d0
	lsr.w #2,d0
	moveq #2,d7
.obp1:
	move.w d0,d1
	andi.w #3,d1
	add.w d1,d1
	move.w (a0,d1.w),$C00000
	lsr.w #2,d0
	dbf d7,.obp1
	clr.b gb_vram_dirty
	clr.b gb_oam_dirty
	clr.b gb_bg_dirty
	move.w #$8174,$C00004
	ifd GB2MD_SHOW_FPS
	clr.b gb_fps_vdp_busy
	endif
	movem.l (sp)+,d0-d7/a0-a2
	rts

; Full-width tile-row-aligned DMG windows use the Genesis window plane.
; It replaces Plane A below the boundary without inheriting SCX/SCY. The
; transparent cells outside the 160x144 viewport reveal the Plane B shell.
; Full-screen WY=0 keeps the existing Plane A path; other X/Y alignments
; still need pixel composition/raster history rather than rounded positions.
.render_partial_window:
	move.w #$8334,$C00004
	move.w #$9100,$C00004
	move.w #$9200,$C00004
	btst #0,gb_io+$40
	beq.w .window_return
	btst #5,gb_io+$40
	beq.w .window_return
	cmpi.b #7,gb_io+$4B
	bne.w .window_return
	moveq #0,d2
	move.b gb_io+$4A,d2
	beq.w .window_return
	cmpi.w #144,d2
	bhs.w .window_return
	move.w d2,d0
	andi.w #7,d0
	bne.w .window_return
	lsr.w #3,d2
	move.w #$9285,d0              ; below viewport origin row 5 plus WY/8
	add.w d2,d0
	move.w d0,$C00004
	moveq #0,d0
	move.w d2,d0
	lsl.w #7,d0
	addi.w #$D294,d0              ; window cell (10,5+WY/8)
	andi.w #$3FFF,d0
	swap d0
	ori.l #$40000003,d0
	move.l d0,$C00004
	lea gb_vram+$1800,a1
	btst #6,gb_io+$40
	beq.s .window_map_ready
	lea gb_vram+$1C00,a1
.window_map_ready:
	move.w #17,d7
	sub.w d2,d7
.window_row:
	moveq #19,d3
.window_col:
	moveq #0,d0
	move.b (a1)+,d0
	btst #4,gb_io+$40
	bne.s .window_tile_ready
	tst.b d0
	bmi.s .window_tile_ready
	addi.w #256,d0
.window_tile_ready:
	ori.w #$8000,d0
	move.w d0,$C00000
	dbf d3,.window_col
	adda.w #12,a1
	moveq #43,d3
.window_pad:
	move.w #640,$C00000
	dbf d3,.window_pad
	dbf d7,.window_row
.window_return:
	rts
.dmg_shades:
	dc.w gb_shade0,gb_shade1,gb_shade2,gb_shade3

; Read a standard Genesis three/six-button pad as a DMG P1/JOYP register.
; Genesis B/C become GB A/B; Genesis A/Start become GB Select/Start.
gb_read_joypad:
	moveq #0,d0
	move.b gb_io,d0
	andi.b #$30,d0
	ori.b #$CF,d0
	move.b #$40,$A10003
	moveq #0,d2
	move.b $A10003,d2
	btst #4,gb_io
	bne.s .no_directions
	ori.b #$0F,d0
	; Genesis bits are U,D,L,R; DMG bits are R,L,U,D.
	btst #3,d2
	bne.s .gen_right_up
	bclr #0,d0
.gen_right_up:
	btst #2,d2
	bne.s .gen_left_up
	bclr #1,d0
.gen_left_up:
	btst #0,d2
	bne.s .gen_up_up
	bclr #2,d0
.gen_up_up:
	btst #1,d2
	bne.s .no_directions
	bclr #3,d0
.no_directions:
	btst #5,gb_io
	bne.s .joy_done
	; Both selected rows share active-low lines: preserve direction clears
	; and AND in the button row instead of replacing those lines.
	btst #4,d2
	bne.s .gb_a_up
	bclr #0,d0
.gb_a_up:
	btst #5,d2
	bne.s .gb_b_up
	bclr #1,d0
.gb_b_up:
	move.b #0,$A10003
	moveq #0,d2
	move.b $A10003,d2
	btst #4,d2
	bne.s .gb_select_up
	bclr #2,d0
.gb_select_up:
	btst #5,d2
	bne.s .joy_done
	bclr #3,d0
.joy_done:
	move.b #$40,$A10003
	rts
