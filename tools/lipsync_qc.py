#!/usr/bin/env python3
"""§7 同步检查内核：逐演唱镜做"时间分辨"的匹配度 + 偏移曲线，定位漂移点。
口径：嘴跟的是 clip 自己返回的音轨 → 比较 clip 音轨 与 母带同窗（带限包络）。
输出：每镜 windows[]（逐窗 r/lag）、first_fail（第一个掉出阈值的时刻，歌曲秒）、r0_all。
"""
import io, json, os, re, subprocess, sys
import numpy as np
from scipy.signal import butter, filtfilt, hilbert
import soundfile as sf
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import mass_produce as mp
ROOT = os.path.expanduser("~/mv-workspace")
FPS = 24; W = 0.6           # 窗口 0.6s
HOP = 0.1                   # 窗移 0.1s
MAXLAG = 6                  # ±6 帧（0.25s）
THRESH = 0.5                # 阈值（论文：match drops under the threshold）
TAKE = {"c07":"c07-attempt2","i03":"i03-attempt4","c14":"c14-attempt2"}
T0={}; T1={}
for m in re.finditer(r'\| (s\d{3}) \| ([\d.]+) \| ([\d.]+) \|', open(f'{ROOT}/storyboard/board-final.md',encoding='utf8').read()):
    T0[m.group(1)]=float(m.group(2)); T1[m.group(1)]=float(m.group(3))
SEG={}
for s in json.load(open(f'{ROOT}/segments.json'))['segments']:
    for sh in s['shots']: SEG[sh]=(s['id'], s['window'][0], TAKE.get(s['id'], s['id']))

def env_of(path, ss=None, t=None):
    cmd=['ffmpeg','-y','-v','error']
    if ss is not None: cmd+=['-ss',f'{ss:.4f}']
    cmd+=['-i',path]
    if t is not None: cmd+=['-t',f'{t:.4f}']
    cmd+=['-vn','-ac','1','-ar','16000','-f','wav','-']
    raw=subprocess.run(cmd,capture_output=True).stdout
    x,sr=sf.read(io.BytesIO(raw),dtype='float32')
    if x.ndim>1: x=x.mean(axis=1)
    b,a=butter(4,[300/(sr/2),3400/(sr/2)],btype='band'); x=filtfilt(b,a,x)
    e=np.abs(hilbert(x)); hop=int(sr/FPS); n=len(e)//hop
    return np.array([e[i*hop:(i+1)*hop].mean() for i in range(n)])

def zc(v):
    v=np.asarray(v,float); s=v.std()
    return (v-v.mean())/(s if s>1e-9 else 1.0)

def piece_audio(pieces, out_wav):
    """把各 piece 的音轨按顺序拼成一条 wav（= 成片里该镜'嘴所跟随'的音轨）"""
    tmpd='/tmp/qcw_pieces'; os.makedirs(tmpd, exist_ok=True)
    txt=[]
    for k,p in enumerate(pieces):
        f=f'{tmpd}/p{k:02d}.wav'
        subprocess.run(['ffmpeg','-y','-v','error','-ss',f"{p['f0']/FPS:.4f}",'-t',f"{p['n']/FPS:.4f}",
                        '-i',p['src'],'-vn','-ac','1','-ar','16000',f],check=True)
        txt.append(f"file '{f}'")
    lst=f'{tmpd}/list.txt'; open(lst,'w').write('\n'.join(txt)+'\n')
    subprocess.run(['ffmpeg','-y','-v','error','-f','concat','-safe','0','-i',lst,'-c','copy',out_wav],check=True)
    return out_wav

def qc_shot(sh, pieces, save_png=None):
    sid,w0,take = SEG[sh]; t0,t1 = T0[sh],T1[sh]
    ca = piece_audio(pieces, f'/tmp/qcw_{sh}.wav')
    ce = env_of(ca); me = env_of(f'{ROOT}/song/song.mp3', t0, t1-t0)
    n=min(len(ce),len(me)); ce,me=ce[:n],me[:n]
    win=int(round(W*FPS)); hop=int(round(HOP*FPS))
    wins=[]
    i=0
    while i+win<=n:
        a,b=zc(ce[i:i+win]),zc(me[i:i+win])
        best=(-1.0001,0)
        for l in range(-MAXLAG,MAXLAG+1):
            if l>=0: x,y=a[l:],b[:len(b)-l] if l else b
            else: x,y=a[:len(a)+l],b[-l:]
            m=min(len(x),len(y))
            if m<6: continue
            r=float((x[:m]*y[:m]).mean())
            if r>best[0]: best=(r,l)
        e_me=float(np.abs(me[i:i+win]).mean())
        wins.append({"t": round(t0+i/FPS,2), "r0": round(float((a*b).mean()),3),
                     "r": round(best[0],3), "lag": best[1], "e": round(e_me,4)})
        i+=hop
    emed=float(np.median([w["e"] for w in wins])) if wins else 0.0
    for w in wins: w["vocal"] = w["e"] >= 0.30*emed      # 人声能量门
    fail=next((w for w in wins if w["vocal"] and w["r"] < THRESH), None)
    # 连续掉线（≥3 窗）才算真漂移；孤立单窗记为噪声
    run=0; sustained=None
    for w in wins:
        if w["vocal"] and w["r"] < THRESH:
            run+=1
            if run>=3 and sustained is None: sustained=w["t"]
        else: run=0
    return {"shot":sh,"seg":sid,"take":take,"t0":t0,"t1":t1,"n_windows":len(wins),
            "n_vocal_windows": sum(1 for w in wins if w.get("vocal")),
            "r_median":round(float(np.median([w['r'] for w in wins if w.get('vocal')]) if any(w.get('vocal') for w in wins) else 0),3),
            "first_fail": (sustained if sustained is not None else None),
            "first_dip": fail, "windows": wins}

def default_plan():
    plan={}
    for sh in sorted(mp.SING_SHOTS):
        sid,w0,take=SEG[sh]
        f0=int(round((T0[sh]-w0)*FPS)); n=int(round((T1[sh]-T0[sh])*FPS))
        plan[sh]=[{"src":take,"f0":f0,"n":n}]
    return plan

def load_plan():
    p=f'{ROOT}/out/lipsync-plan.json'
    if os.path.exists(p): return json.load(open(p))
    pl=default_plan(); json.dump(pl, open(p,'w'), ensure_ascii=False, indent=1); return pl

if __name__=='__main__':
    plan=load_plan()
    out={}
    for sh in sorted(mp.SING_SHOTS):
        sid,w0,take=SEG[sh]
        pieces=[{"src":f'{ROOT}/clips/final/{p["src"]}.mp4',"f0":p["f0"],"n":p["n"]} for p in plan[sh]]
        d=qc_shot(sh,pieces)
        out[sh]=d
        mark=('✅' if not d['first_fail'] else f"❌ 持续掉线@{d['first_fail']}s") + ('' if not d['first_dip'] else f"  (孤立低点@{d['first_dip']['t']}s r={d['first_dip']['r']})")
        print(f"{sh:5} {sid:12} 窗数{d['n_windows']:3d} r中位 {d['r_median']:+.3f}  {mark}")
    json.dump(out, open(f'{ROOT}/out/qc7-per-shot.json','w'), ensure_ascii=False, indent=1)
