; Background-only fixed-scanline composition. No CPU interpretation or title rules.
; Dedicated VDP patterns $9000-$BCFF do not overlap normal patterns, HUD or maps.
; Work RAM C700-C93F stores per-line output fingerprints for diagnostics only.
gb_raster_scanline:
	tst.b gb_raster_armed
	beq.w .done
	movem.l d0-d7/a0-a3,-(sp)
	move.b gb_io+$40,d0
	andi.b #$A2,d0
	cmpi.b #$80,d0
	bne.w .unsupported
	moveq #0,d0
	move.b gb_io+$44,d0
	cmpi.w #144,d0
	bhs.w .restore
	tst.w d0
	bne.s .check_line
	clr.w gb_raster_lines
.check_line:
	cmp.w gb_raster_lines,d0
	bne.w .restore                 ; wait for a complete frame beginning at LY0
	move.w d0,d5
	andi.w #7,d5
	lsl.w #2,d5
	lsr.w #3,d0
	mulu #640,d0
	add.w d0,d5
	addi.w #$9000,d5
	moveq #0,d0
	move.b gb_io+$44,d0
	add.b gb_io+$42,d0
	move.w d0,d4
	andi.w #7,d4
	add.w d4,d4
	lsr.w #3,d0
	lsl.w #5,d0
	lea gb_vram+$1800,a2
	btst #3,gb_io+$40
	beq.s .map_ready
	lea gb_vram+$1C00,a2
.map_ready:
	adda.w d0,a2
	moveq #0,d0
	move.b gb_io+$47,d0
	bsr.w gb_raster_select_palette
	lea gb_2bpp_nibble_table,a1
	moveq #0,d6
	move.b gb_io+$43,d6
	move.w d6,d7
	lsr.w #3,d7
	andi.w #7,d6
	ifd GB2MD_SHOW_FPS
	move.b #1,gb_fps_vdp_busy
	endif
	clr.l -(sp)                    ; ordered rotate/XOR output fingerprint
	move.w #19,-(sp)
.tile:
	moveq #0,d0
	move.b (a2,d7.w),d0
	bsr.w .fetch_row
	move.w d0,d2
	move.w d1,d3
	lsl.w #8,d2
	lsl.w #8,d3
	tst.w d6
	beq.s .aligned
	move.w d7,d0
	addq.w #1,d0
	andi.w #31,d0
	move.b (a2,d0.w),d0
	andi.w #$FF,d0
	bsr.w .fetch_row
	or.w d0,d2
	or.w d1,d3
	lsl.w d6,d2
	lsl.w d6,d3
.aligned:
	lsr.w #8,d2
	lsr.w #8,d3
	btst #0,gb_io+$40
	bne.s .background_enabled
	clr.w d2
	clr.w d3
.background_enabled:
	moveq #0,d0
	move.w d5,d0
	move.l d0,d1
	andi.l #$3FFF,d0
	swap d0
	andi.l #$C000,d1
	lsr.l #8,d1
	lsr.l #6,d1
	or.l d1,d0
	ori.l #$40000000,d0
	move.l d0,$C00004
	moveq #0,d0
	move.w d2,d0
	lsr.w #4,d0
	move.w d3,d1
	andi.w #$F0,d1
	or.w d1,d0
	add.w d0,d0
	move.w (a1,d0.w),d0
	bsr.w .convert_four
	move.w d0,$C00000
	bsr.w .fingerprint
	moveq #0,d0
	move.w d3,d0
	andi.w #15,d0
	lsl.w #4,d0
	move.w d2,d1
	andi.w #15,d1
	or.w d1,d0
	add.w d0,d0
	move.w (a1,d0.w),d0
	bsr.w .convert_four
	move.w d0,$C00000
	bsr.w .fingerprint
	addi.w #32,d5
	addq.w #1,d7
	andi.w #31,d7
	subq.w #1,(sp)
	bpl.w .tile
	addq.l #2,sp
	move.l (sp)+,d0
	moveq #0,d1
	move.b gb_io+$44,d1
	lsl.w #2,d1
	lea gb_raster_row_hashes,a0
	move.l d0,(a0,d1.w)
	addq.w #1,gb_raster_lines
	addq.l #1,gb_raster_capture_count
	cmpi.w #144,gb_raster_lines
	bne.s .capture_done
	move.b #1,gb_raster_ready
	move.b #1,gb_video_dirty
.capture_done:
	ifd GB2MD_SHOW_FPS
	clr.b gb_fps_vdp_busy
	endif
	bra.s .restore
.unsupported:
	clr.b gb_raster_armed
	clr.b gb_raster_seen
	clr.b gb_raster_ready
	clr.w gb_raster_lines
	move.b #1,gb_bg_dirty
	move.b #1,gb_video_dirty
.restore:
	movem.l (sp)+,d0-d7/a0-a3
.done:
	rts
.fingerprint:
	; BSR return, loop word, then the long accumulator.
	move.l 6(sp),d1
	rol.l #1,d1
	eor.l d0,d1
	move.l d1,6(sp)
	rts
.fetch_row:
	btst #4,gb_io+$40
	bne.s .unsigned
	tst.b d0
	bmi.s .unsigned
	addi.w #256,d0
.unsigned:
	lsl.w #4,d0
	add.w d4,d0
	lea gb_vram,a0
	adda.w d0,a0
	moveq #0,d0
	moveq #0,d1
	move.b (a0)+,d0
	move.b (a0),d1
	rts
.convert_four:
	move.w d0,d1
	lsr.w #8,d1
	move.b (a3,d1.w),d1
	lsl.w #8,d1
	andi.w #$FF,d0
	move.b (a3,d0.w),d0
	or.w d1,d0
	rts
gb_raster_select_palette:
	lea gb_raster_palette_cache,a3
	tst.b gb_raster_palette_valid0
	beq.s .try_second
	cmp.b gb_raster_palette0,d0
	beq.w .palette_ready
.try_second:
	tst.b gb_raster_palette_valid1
	beq.s .palette_miss
	cmp.b gb_raster_palette1,d0
	bne.s .palette_miss
	adda.w #256,a3
	bra.w .palette_ready
.palette_miss:
	eori.b #1,gb_raster_palette_slot
	tst.b gb_raster_palette_slot
	beq.s .replace_first
	move.b d0,gb_raster_palette1
	move.b #1,gb_raster_palette_valid1
	adda.w #256,a3
	bra.s .fill_palette
.replace_first:
	move.b d0,gb_raster_palette0
	move.b #1,gb_raster_palette_valid0
.fill_palette:
	; Generate only sixteen valid entries. This avoids adding a 4 KiB ROM
	; table (important near the cartridge limit) or per-pixel BGP extraction.
	movem.l d2-d4,-(sp)
	move.w d0,d4
	moveq #0,d2
.first_colour:
	move.w d2,d1
	add.w d1,d1
	move.w d4,d0
	lsr.w d1,d0
	andi.w #3,d0
	addq.w #1,d0
	lsl.w #4,d0
	move.w d0,-(sp)
	moveq #0,d3
.second_colour:
	move.w d3,d1
	add.w d1,d1
	move.w d4,d0
	lsr.w d1,d0
	andi.w #3,d0
	addq.w #1,d0
	or.w (sp),d0
	move.w d2,d1
	lsl.w #4,d1
	add.w d3,d1
	move.b d0,(a3,d1.w)
	addq.w #1,d3
	cmpi.w #4,d3
	blo.s .second_colour
	addq.l #2,sp
	addq.w #1,d2
	cmpi.w #4,d2
	blo.s .first_colour
	movem.l (sp)+,d2-d4
.palette_ready:
	rts

; Called from gb_render_frame with its save set already on the host stack.
; d0=1 means a complete BG-only raster replaces the ordinary frame renderer.
gb_raster_present:
	moveq #0,d0
	tst.b gb_raster_ready
	beq.w .done
	move.b gb_io+$40,d0
	andi.b #$A2,d0
	cmpi.b #$80,d0
	bne.w .fallback
	addq.l #1,gb_raster_frame_count
	tst.b gb_raster_presented
	bne.w .success
	; Clear outside viewport and turn off Genesis window/sprites. The next
	; normal frame rebuilds its map/palette after leaving supported BG mode.
	move.w #$9100,$C00004
	move.w #$9200,$C00004
	move.l #$70000003,$C00004
	moveq #0,d0
	move.w #159,d7
.clear_sprites:
	move.w d0,$C00000
	dbf d7,.clear_sprites
	move.l #$40000003,$C00004
	move.w #640,d0
	move.w #2047,d7
.clear_map:
	move.w d0,$C00000
	dbf d7,.clear_map
	move.l #$42940003,$C00004
	move.w #$8480,d0               ; priority + pattern ID $9000/32
	moveq #17,d7
.map_row:
	moveq #19,d6
.map_col:
	move.w d0,$C00000
	addq.w #1,d0
	dbf d6,.map_col
	moveq #43,d6
.pad:
	move.w #640,$C00000
	dbf d6,.pad
	dbf d7,.map_row
	move.l #$C0000000,$C00004
	move.w #0,$C00000
	move.w #gb_shade0,$C00000
	move.w #gb_shade1,$C00000
	move.w #gb_shade2,$C00000
	move.w #gb_shade3,$C00000
	move.l #$7C000003,$C00004
	move.l #0,$C00000
	move.l #$40000010,$C00004
	move.l #0,$C00000
	move.b #1,gb_raster_presented
.success:
	moveq #1,d0
.done:
	rts
.fallback:
	clr.b gb_raster_ready
	moveq #0,d0
	rts

; Static initialization/fades must not permanently select the expensive path.
; Keep it only while visible register changes recur; one quiet full frame
; restores the normal renderer without dropping the already captured picture.
gb_raster_end_frame:
	tst.b gb_raster_armed
	beq.s .done
	tst.b gb_raster_seen
	beq.s .quiet
	clr.b gb_raster_seen
	rts
.quiet:
	clr.b gb_raster_armed
	clr.b gb_raster_ready
	move.b #1,gb_bg_dirty
	move.b #1,gb_video_dirty
.done:
	rts
