; Optional hardware-clock HUD. All source state and native temporaries are
; preserved. VRAM writes occur only while the main renderer is not using VDP.
gb_fps_host_frames equ $FF0060
gb_fps_last_cycles equ $FF0064
gb_fps_ticks equ $FF0068
gb_fps_hz equ $FF006A
gb_fps_value equ $FF006C
gb_fps_vdp_busy equ $FF006E
gb_fps_dirty equ $FF006F
gb_fps_samples equ $FF0070

gb_fps_init:
	move.w #60,gb_fps_hz
	btst #6,$A10001
	beq.s .region_ready
	move.w #50,gb_fps_hz
.region_ready:
	move.l gb_cycle_counter,gb_fps_last_cycles
	move.l #$50800001,$C00004
	lea gb_fps_font,a0
	move.w #271,d0
.copy_font:
	move.w (a0)+,$C00000
	dbf d0,.copy_font
	move.l #$C03E0000,$C00004
	move.w #$0EEE,$C00000
	bsr.w gb_fps_draw
	move.w $C00004,d0             ; acknowledge any setup-time VBlank
	rts

gb_fps_vblank:
	movem.l d0-d4/a0,-(sp)
	move.w $C00004,d4             ; acknowledge real Genesis VBlank
	addq.l #1,gb_fps_host_frames
	addq.w #1,gb_fps_ticks
	move.w gb_fps_ticks,d0
	cmp.w gb_fps_hz,d0
	blo.s .sample_done
	clr.w gb_fps_ticks
	move.l gb_cycle_counter,d0
	move.l d0,d1
	sub.l gb_fps_last_cycles,d0   ; modular32-bit difference survives wrap
	move.l d1,gb_fps_last_cycles
	cmpi.l #70224000,d0
	bhs.s .saturated
	lsr.l #2,d0                  ; machine cycles; divisor17556 fits DIVU
	move.l d0,d1
	lsl.l #2,d0
	add.l d1,d0
	add.l d0,d0                  ; ten times source machine cycles
	divu.w #17556,d0
	bra.s .store_rate
.saturated:
	move.w #9999,d0
.store_rate:
	move.w d0,gb_fps_value
	move.b #1,gb_fps_dirty
	addq.l #1,gb_fps_samples
.sample_done:
	tst.b gb_fps_dirty
	beq.s .done
	tst.b gb_fps_vdp_busy
	bne.s .done
	bsr.w gb_fps_draw
	clr.b gb_fps_dirty
.done:
	movem.l (sp)+,d0-d4/a0
	rte

gb_fps_draw:
	move.l #$60820003,$C00004     ; Plane B(1,1), outside160x144 game area
	lea gb_fps_header,a0
	moveq #6,d3
.header:
	move.w (a0)+,$C00000
	dbf d3,.header
	moveq #0,d0
	move.w gb_fps_value,d0
	divu.w #1000,d0
	bsr.s .digit
	swap d0
	andi.l #$FFFF,d0
	divu.w #100,d0
	bsr.s .digit
	swap d0
	andi.l #$FFFF,d0
	divu.w #10,d0
	bsr.s .digit
	move.w #$A293,$C00000        ; decimal point glyph
	swap d0
	bsr.s .digit
	rts
.digit:
	move.w d0,d1
	addi.w #644,d1
	ori.w #$A000,d1              ; high-priority Plane B, shell palette
	move.w d1,$C00000
	rts
