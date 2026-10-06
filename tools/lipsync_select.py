#!/usr/bin/env python3
"""候选选拔：对每条演唱镜，比较 原始 / 第1轮续镜 / 当前 三个装配，按 QC 取最优。"""
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lipsync_qc as q
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); FPS=24
plan=json.load(open(f'{ROOT}/out/lipsync-plan.json'))
# 第 1 轮切点（从循环日志解析）
cuts1={}
for l in open(f'{ROOT}/out/lipsync-loop.log'):
    m=re.search(r'\[fix\] (s\d{3}) 续镜#1 切点 ([\d.]+)s', l)
    if m: cuts1[m.group(1)]=float(m.group(2))
def evaluate(sh, pieces):
    d=q.qc_shot(sh, [{"src":f'{ROOT}/clips/final/{p["src"]}.mp4',"f0":p["f0"],"n":p["n"]} for p in pieces])
    return d
chosen={}
for sh in sorted(plan):
    sid,w0,take=q.SEG[sh]; t0,t1=q.T0[sh],q.T1[sh]
    cands={}
    cands['orig']=[{"src":take,"f0":int(round((t0-w0)*FPS)),"n":int(round((t1-t0)*FPS))}]
    if sh in cuts1:
        c=cuts1[sh]
        if c <= t0+0.35: c=t0
        keep=int(round((c-t0)*FPS)); rest=int(round((t1-c)*FPS))
        p1=[{"src":take,"f0":int(round((t0-w0)*FPS)),"n":keep}] if keep>0 else []
        p1.append({"src":f"cont-{sh}-1","f0":0,"n":rest})
        cands['fix1']=p1
    cands['cur']=plan[sh]
    res={}
    for name,pieces in cands.items():
        d=evaluate(sh,pieces)
        res[name]=(d['first_fail'], d['r_median'], pieces)
    # 选拔：无持续掉线优先，其次 r 中位高
    order=sorted(res.items(), key=lambda kv: (kv[1][0] is not None, -kv[1][1]))
    best=order[0][0]
    print(f"{sh}: " + ' | '.join(f"{n} {'掉线@'+str(v[0]) if v[0] else '过线'} r中位{v[1]:.3f}" for n,(v) in res.items()) + f"  → 选 {best}")
    chosen[sh]=res[best][2]
json.dump(chosen, open(f'{ROOT}/out/lipsync-plan.json','w'), ensure_ascii=False, indent=1)
print('已写回最优 plan')
