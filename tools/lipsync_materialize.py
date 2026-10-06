#!/usr/bin/env python3
"""把 plan 里"多段拼成的一镜"物化成连续帧目录 out/shotframes/{sh}/，供底稿与引擎直接使用。
单段且源=交付 take 的镜不物化（沿用原 frames 目录）。"""
import json, os, shutil, sys
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
plan=json.load(open(f'{ROOT}/out/lipsync-plan.json'))
out=f'{ROOT}/out/shotframes'
made=[]
for sh,pieces in plan.items():
    multi = len(pieces)>1
    if not multi: continue
    d=os.path.join(out, sh); shutil.rmtree(d, ignore_errors=True); os.makedirs(d, exist_ok=True)
    k=0
    for p in pieces:
        src=os.path.join(ROOT,f'clips/final/{p["src"]}-frames')
        fs=sorted(f for f in os.listdir(src) if f.endswith('.png'))
        for i in range(p['f0'], min(p['f0']+p['n'], len(fs))):
            os.link(os.path.join(src,fs[i]), os.path.join(d,f'f{k:04d}.png')); k+=1
    made.append((sh,k))
    print(f'{sh}: {len(pieces)} 段 → {k} 帧 → out/shotframes/{sh}')
json.dump({sh:k for sh,k in made}, open(f'{ROOT}/out/shotframes.json','w'))
print('物化完成：', len(made), '镜')
