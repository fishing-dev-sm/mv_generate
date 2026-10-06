#!/usr/bin/env python3
"""§7 QC→fix→QC 循环驱动：直到每个演唱镜全程过线（或耗尽修复次数）。"""
import json, os, subprocess, sys, time, datetime
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); LOG=f'{ROOT}/out/lipsync-loop.log'
def log(m):
    line=f"{datetime.datetime.now():%F %T} {m}"
    print(line, flush=True); open(LOG,'a').write(line+'\n')
def qc():
    subprocess.run(['venv/bin/python',os.path.join(os.path.dirname(os.path.abspath(__file__)),'lipsync_qc.py')], cwd=ROOT,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return json.load(open(f'{ROOT}/out/qc7-per-shot.json'))
MAXIT=3
subprocess.run(['venv/bin/python','-c','import sys,os;sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)));import lipsync_qc as q;q.load_plan()'],cwd=ROOT)
log('=== 循环开始（判据：逐 0.6s 窗，±6 帧内最佳正相关 ≥ 0.5）===')
for it in range(1, MAXIT+1):
    res=qc()
    fails={sh:d for sh,d in res.items() if d['first_fail']}
    log(f"--- 第 {it} 轮 QC：过线 {len(res)-len(fails)}/{len(res)}；掉线 {sorted(fails)}")
    for sh,d in sorted(fails.items()):
        f=d['first_fail']; log(f"    {sh} 掉线 @{f['t']}s (r={f['r']}, lag={f['lag']})")
    if not fails:
        log('=== 全部演唱镜过线，循环结束 ==='); break
    for sh,d in sorted(fails.items()):
        T=d['first_fail']['t']
        log(f"[fix] {sh} → 在 {T}s 前最后一个八分音符处切镜 + 生成续镜（第 {it} 次）")
        r=subprocess.run(['venv/bin/python',os.path.join(os.path.dirname(os.path.abspath(__file__)),'lipsync_fix.py'),sh,str(T),str(it)],cwd=ROOT,
                         capture_output=True,text=True)
        for l in (r.stdout or '').strip().splitlines(): log('    '+l)
        if r.returncode!=0:
            log(f"[fix][ERR] {sh}: {(r.stderr or '')[-300:]}")
        qc()
log('=== 循环结束 ===')
