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
gb_io equ $FF0100
gb_hram equ $FF0180
gb_oam equ $FF0200
gb_vram equ $FF0300
gb_wram equ $FF2300

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
.read_done:
	rts
.rom0_read:
	lea gb_cart_rom,a0
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
	subi.w #$FE00,d1
	lea gb_oam,a0
	move.b (a0,d1.w),d0
	rts
.io_read:
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
	move.b d0,gb_ie
	bra.w .done
.write_low:
	cmpi.w #$8000,d1
	blo.w .mapper
	cmpi.w #$A000,d1
	blo.w .vram
.done:
	rts
.mapper:
	; MBC1/MBC3 low ROM-bank register. Other mapper controls are expanded in
	; the same service without changing generated blocks.
	cmpi.b #$01,gb_mapper_kind
	beq.s .mapper_low5
	cmpi.b #$02,gb_mapper_kind
	beq.s .mapper_low5
	cmpi.b #$03,gb_mapper_kind
	beq.s .mapper_low5
	cmpi.b #$0F,gb_mapper_kind
	blo.s .done
	cmpi.b #$13,gb_mapper_kind
	bls.s .mapper_low7
	bra.s .done
.mapper_low5:
	cmpi.w #$2000,d1
	blo.s .done
	cmpi.w #$4000,d1
	bhs.s .done
	andi.w #$001F,d0
	bne.s .store_mapper_bank
	moveq #1,d0
	bra.s .store_mapper_bank
.mapper_low7:
	cmpi.w #$2000,d1
	blo.s .done
	cmpi.w #$4000,d1
	bhs.s .done
	andi.w #$007F,d0
	bne.s .store_mapper_bank
	moveq #1,d0
.store_mapper_bank:
	move.w d0,gb_rom_bank
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
	move.b #1,gb_vram_dirty
	bra.s .vram_unchanged
.vram_map_dirty:
	move.b #1,gb_bg_dirty
.vram_unchanged:
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
	cmpi.w #$0004,d1
	blo.s .io_timing_synced
	cmpi.w #$0007,d1
	bhi.s .io_timing_synced
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
	move.b d0,(a0,d1.w)
	cmpi.w #$000F,d1
	bne.s .not_if_write
	andi.b #$1F,(a0,d1.w)
.not_if_write:
	cmpi.w #$0046,d1
	bne.w .not_oam_dma
	; DMG OAM DMA copies $A0 bytes from XX00. WRAM/echo are the hot paths
	; used by Tetris and most games; other legal sources use gb_read8.
	movem.l d3-d5/a1,-(sp)
	moveq #0,d3
	move.b d0,d3
	cmpi.w #$00C0,d3
	blo.s .dma_general
	cmpi.w #$00E0,d3
	blo.s .dma_wram
	cmpi.w #$00FE,d3
	blo.s .dma_echo
	bra.s .dma_general
.dma_wram:
	subi.w #$00C0,d3
	bra.s .dma_direct
.dma_echo:
	subi.w #$00E0,d3
.dma_direct:
	lsl.w #8,d3
	lea gb_wram,a0
	adda.w d3,a0
	lea gb_oam,a1
	moveq #39,d4
.dma_direct_loop:
	move.l (a0)+,d5
	cmp.l (a1),d5
	beq.s .dma_direct_same
	move.l d5,(a1)
	move.b #1,gb_video_dirty
	move.b #1,gb_oam_dirty
.dma_direct_same:
	addq.l #4,a1
	dbf d4,.dma_direct_loop
	bra.s .dma_done
.dma_general:
	lsl.w #8,d3
	lea gb_oam,a1
	move.w #159,d4
.dma_general_loop:
	move.w d3,d1
	jsr gb_read8
	cmp.b (a1),d0
	beq.s .dma_general_same
	move.b d0,(a1)
	move.b #1,gb_video_dirty
	move.b #1,gb_oam_dirty
.dma_general_same:
	addq.l #1,a1
	addq.w #1,d3
	dbf d4,.dma_general_loop
.dma_done:
	movem.l (sp)+,d3-d5/a1
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
	jsr gb_tick                       ; flush the branch and its basic block
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

; d0.b = LY value polled by a read-only loop. This variant is used while IME
; is disabled during LCD setup/DMA waits, so no program-visible instructions
; exist between the current and requested scanline.
gb_idle_ly:
	move.w d0,-(sp)
	jsr gb_tick                       ; flush the branch and its basic block
	move.w (sp)+,d0
	cmp.b gb_io+$44,d0
	beq.w .idle_ly_done_early
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

gb_tick:
	moveq #0,d6
	move.b gb_step_cycles,d6
	add.w d7,d6
	clr.w d7
	add.w gb_cycle_batch,d6
	clr.w gb_cycle_batch
	add.l d6,gb_cycle_counter
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
	cmpi.w #456,d0
	blo.s .scanlines_done
	subi.w #456,d0
	addq.b #1,gb_io+$44
	cmpi.b #154,gb_io+$44
	blo.s .ly_in_range
	clr.b gb_io+$44
.ly_in_range:
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
	bra.s .scanline_loop
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
	; Lowest pending bit has priority. d2 is bit mask, d3 is vector.
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
	move.w gb_sp,d1
	subq.w #2,d1
	move.w d1,gb_sp
	move.w gb_pc,d4
	move.w d1,d5
	addq.w #1,d1
	move.w d4,d0
	lsr.w #8,d0
	bsr.w gb_write8
	move.w d5,d1
	move.w d4,d0
	bsr.w gb_write8
	clr.w gb_bank
	move.w d3,gb_pc
.tick_done:
	rts
gb_timer_periods:
	dc.w 1024,16,64,256
; Convert live DMG tile data and the selected 32x32 BG map into Genesis VRAM.
; Plane A is at $C000; tile patterns occupy $0000-$2FFF.  The routine runs at
; emulated VBlank and therefore displays original game state, not baked assets.
gb_render_frame:
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
	move.l #$40000000,$C00004
	lea gb_vram,a0
	lea gb_2bpp_nibble_table,a1
	move.w #3071,d7                 ; 384 tiles * 8 rows
.tile_row:
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
	dbf d7,.tile_row
	; Sprite patterns need GB color 0 to remain transparent. Duplicate the
	; first 256 tiles unshifted at Genesis tile IDs 384-639.
	lea gb_vram,a0
	move.w #2047,d7                 ; 256 tiles * 8 rows
.sprite_tile_row:
	moveq #0,d0
	moveq #0,d1
	move.b (a0)+,d0
	move.b (a0)+,d1
	move.w d1,d2
	andi.w #$00F0,d2
	move.w d0,d3
	lsr.w #4,d3
	or.w d3,d2
	add.w d2,d2
	move.w (a1,d2.w),$C00000
	andi.w #$000F,d0
	andi.w #$000F,d1
	lsl.w #4,d1
	or.w d0,d1
	add.w d1,d1
	move.w (a1,d1.w),$C00000
	dbf d7,.sprite_tile_row

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
	move.b #1,gb_plane_initialized
.plane_initialized:
	; Place the 20x18-tile DMG viewport at (10,5).
	move.l #$42940003,$C00004       ; Plane A cell (10,5)
	lea gb_vram+$1800,a2
	btst #3,gb_io+$40
	beq.s .map_selected
	lea gb_vram+$1C00,a2
.map_selected:
	moveq #0,d2
	move.b gb_io+$42,d2
	lsr.w #3,d2
	moveq #0,d4
	move.b gb_io+$43,d4
	lsr.w #3,d4
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
	move.b gb_io+$43,d0
	andi.w #7,d0
	neg.w d0
	move.w d0,$C00000
	move.w #0,$C00000
	; Plane A vertical scroll uses SCY.
	move.l #$40000010,$C00004
	moveq #0,d0
	move.b gb_io+$42,d0
	andi.w #7,d0
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
	movem.l (sp)+,d0-d7/a0-a2
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
	; Start with all four GB buttons released, then copy active-low bits.
	ori.b #$0F,d0
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
