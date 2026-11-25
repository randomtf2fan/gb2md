"""Native helper state matrices verify optimized bookkeeping and its ABI."""
import itertools,os,random,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from gb_cpu import Memory


def stat_vectors():
    rows=[]
    for lcd,ly,dot,mask,equal,old_line,flags in itertools.product(
            (0,0x91),(0,1,143,144,153),(0,79,80,251,252,455),range(0,128,8),(False,True),(0,1),(0,0xE2)):
        lyc=ly if equal else (ly+1)%154
        mode=0 if not lcd&128 else (1 if ly>=144 else 2 if dot<80 else 3 if dot<252 else 0)
        stat=mask|mode|(4 if equal else 0)
        line=int(bool(lcd&128 and ((equal and mask&64) or (mode==0 and mask&8) or
                                 (mode==1 and mask&16) or (mode==2 and mask&32))))
        # LCD-off freezes the old comparison bit and edge latch, regardless
        # of the current LY/LYC inputs; it never requests a new interrupt.
        if not lcd&128:stat=mask|4;line=old_line
        result_flags=flags if not lcd&128 else flags|(2 if line and not old_line else 0)
        rows.append(((lcd,ly,lyc,mask|0x87,dot,old_line,flags),(stat,line,result_flags)))
    return rows


def deadline(ie,flags,lcd,ly,dot,stat,tac,tima,divider,reload):
    if ie&flags&31:return 200
    distance=200
    if ie&1 and ly==143:distance=min(distance,456-dot)
    if ie&2 and lcd&128 and stat&0x78:
        edge=456 if ly>=144 else (80 if dot<80 else 252 if dot<252 else 456)
        distance=min(distance,edge-dot)
    if ie&4:
        if reload:distance=min(distance,reload)
        elif tac&4:
            period=(1024,16,64,256)[tac&3]
            distance=min(distance,period-(divider&(period-1))+(255-tima)*period+4)
    return 200-distance


def deadline_vectors():
    states=[]
    for ie,flags,ly,dot,tac,reload in itertools.product((1,0x81,0xE1,31),(0,1,2,4),(142,143,144),
                                                       (0,255,256,257,455),(0,5),(0,4)):
        states.append((ie,flags,0x91,ly,dot,0x78,tac,255,15,reload))
    rng=random.Random(0x68000)
    for _ in range(1500):
        states.append((rng.randrange(256),rng.randrange(256),rng.choice((0,0x91)),rng.randrange(154),
                       rng.randrange(456),rng.randrange(256),rng.randrange(8),rng.randrange(256),
                       rng.randrange(65536),rng.randrange(5)))
    rows=[]
    for state in states:
        ie,flags,lcd,ly,dot,stat,tac,tima,div,reload=state
        bias=deadline(*state)
        rows.append(((ie,flags,lcd,ly,dot,stat,tac,tima,div&255,div>>8,reload,0xA55A),
                     (0x17270000|bias,bias)))
    return rows


def probe_program(routine,inputs,outputs,rows,changes_d7=False):
    # This is original native test instrumentation, not an SM83 replacement.
    # Data vectors exercise the same runtime used by compiled Game Boy ROMs.
    sentinels={f'd{i}':0x10203040+0x01010101*i for i in range(8)}
    sentinels.update(a0=0x112233,a1=0x334455)
    lines=['native_probe:', '\tlea native_vectors,a2','\tlea native_vectors_end,a3',
           '\tclr.w $FF2302','.native_vector:']
    for address,size in inputs:lines+=['\tmove.l (a2)+,d0',f'\tmove.{size} d0,{address}']
    lines += [f'\tmove.l #${value:08X},{reg}' for reg,value in sentinels.items()]
    lines += [f'\tjsr {routine}']
    for reg,value in sentinels.items():
        if reg=='d7' and changes_d7:continue
        lines += [f'\t{"cmpa" if reg.startswith("a") else "cmpi"}.l #${value:08X},{reg}',
                  '\tbne.w .native_fail']
    for address,size in outputs:
        lines += ['\tmoveq #0,d0',f'\tmove.{size} {address},d0','\tcmp.l (a2)+,d0','\tbne.w .native_fail']
    lines += ['\taddq.w #1,$FF2302','\tcmpa.l a3,a2','\tbne.w .native_vector',
              '\tmove.b #$42,$FF2300','\tbra.s .native_done','.native_fail:',
              '\tmove.b #$FF,$FF2300','.native_done:','\tbra.s .native_done','\teven','native_vectors:']
    for values,expected in rows:lines.append('\tdc.l '+','.join(f'${x:08X}' for x in (*values,*expected)))
    lines.append('native_vectors_end:')
    return '\n'.join(lines)+'\n'


class SchedulerBookkeepingTests(unittest.TestCase):
    def test_state_matrices_match_oracle_and_deadline_edges(self):
        m=Memory(bytes(0x8000))
        for values,expected in stat_vectors():
            lcd,ly,lyc,stat,dot,line,flags=values
            m.io[0x40]=lcd;m.io[0x45]=lyc;m.io[0x41]=stat;m.stat_line=bool(line);m.io[0x0F]=flags
            m._update_stat(ly*456+dot)
            self.assertEqual((m.io[0x41],int(m.stat_line),m.io[0x0F]),expected)
        for dot,bias in ((255,0),(256,0),(257,1),(455,199)):
            self.assertEqual(deadline(1,0,0x91,143,dot,0,0,0,0,0),bias)
        self.assertEqual(deadline(1,1,0x91,0,0,0,0,0,0,0),200)
        self.assertEqual(deadline(4,0,0x91,0,0,0,5,255,15,0),195)
        self.assertEqual(deadline(4,0,0x91,0,0,0,0,255,0,4),196)

    @unittest.skipUnless(os.environ.get('GB2MD_NATIVE_TESTS')=='1','opt-in external BlastEm integration')
    def test_native_helper_matrices_preserve_state_and_registers(self):
        import build_recompiled as compiler
        from run_compat_tests import _run_in_pty,_blastem_values
        models=[('gb_stat_sync', [('gb_io+$40','b'),('gb_io+$44','b'),('gb_io+$45','b'),
                  ('gb_io+$41','b'),('gb_ly_accum','w'),('gb_stat_line','b'),('gb_io+$0F','b')],
                 [('gb_io+$41','b'),('gb_stat_line','b'),('gb_io+$0F','b')],stat_vectors(),False),
                ('gb_refresh_batch_bias',[('gb_ie','b'),('gb_io+$0F','b'),('gb_io+$40','b'),
                  ('gb_io+$44','b'),('gb_ly_accum','w'),('gb_io+$41','b'),('gb_io+$07','b'),
                  ('gb_io+$05','b'),('gb_div_accum','w'),('gb_io+$04','b'),('gb_timer_accum','w'),('gb_batch_bias','w')],
                 [('d7','l'),('gb_batch_bias','w')],deadline_vectors(),True)]
        for routine,inputs,outputs,rows,changes_d7 in models:
            with self.subTest(routine=routine),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);rom=bytearray(0x8000);rom[0x100:0x102]=bytes.fromhex('18fe')
                source=root/'original.gb';source.write_bytes(rom);original=compiler.compile_trace
                def discover(*args,**kwargs):
                    blocks=original(*args,**kwargs);p=args[1]/'translated_trace.s';text=p.read_text()
                    import re
                    text,n=re.subn(r'(gb_compiled_entry:\n)\tbra.w L_gb_[^\n]+',r'\1\tbra.w native_probe',text,count=1)
                    assert n==1
                    p.write_text(text+'\n'+probe_program(routine,inputs,outputs,rows,changes_d7))
                    return blocks
                with patch.object(compiler,'compile_trace',side_effect=discover):image=compiler.build(source,root/'out',2)
                rc,out,timed=_run_in_pty([os.environ['GB2MD_BLASTEM'],'-d',str(image)],
                    'frames 180\np/x [$ff2300].b [$ff2302].w [$ff0018].l\nquit\n',20)
                self.assertFalse(timed,out);self.assertEqual(rc,0,out);v=_blastem_values(out)
                self.assertEqual(v.get('FF2300.b'),0x42,out)
                self.assertEqual(v.get('FF2302.w'),len(rows),out)
                self.assertEqual(v.get('FF0018.l'),0,out)
