#!/usr/bin/env python3
"""底稿 v2：按 out/lipsync-plan.json 的最终装配逐镜出帧 → 拼成无 JS 底稿。"""
import json, os, re, shutil, subprocess, sys
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); FPS=24
TAKE={"c07":"c07-attempt2","i03":"i03-attempt4","c14":"c14-attempt2"}
T0={}; T1={}
for m in re.finditer(r'\| (s\d{3}) \| ([\d.]+) \| ([\d.]+) \|', open(f'{ROOT}/storyboard/board-final.md',encoding='utf8').read()):
    T0[m.group(1)]=float(m.group(2)); T1[m.group(1)]=float(m.group(3))
plan=json.load(open(f'{ROOT}/out/lipsync-plan.json'))
segs=json.load(open(f'{ROOT}/segments.json'))['segments']
tmp=f'{ROOT}/out/base-frames2'; shutil.rmtree(tmp, ignore_errors=True); os.makedirs(tmp)
idx=0; used={}
def emit(frames_dir, i0, n):
    global idx
    fs=sorted(f for f in os.listdir(frames_dir) if f.endswith('.png'))
    for k in range(n):
        i=min(i0+k, len(fs)-1)
        os.link(os.path.join(frames_dir,fs[i]), f'{tmp}/f{idx:04d}.png'); idx+=1
for seg in segs:
    sid=seg['id']; take=TAKE.get(sid,sid); w0=seg['window'][0]
    for sh in seg['shots']:
        if sh not in T0: continue
        if sh in plan and any(p['src'].startswith('cont-') for p in plan[sh]):
            for p in plan[sh]:
                emit(f"{ROOT}/clips/final/{p['src']}-frames", p['f0'], p['n'])
            used[sh]=len(plan[sh])
        else:
            i0=int(round((T0[sh]-w0)*FPS)); n=int(round((T1[sh]-T0[sh])*FPS))
            emit(f'{ROOT}/clips/final/{take}-frames', i0, n)
print('总帧', idx, '=', round(idx/FPS,2),'s；用到续镜的镜:', used)
out=f'{ROOT}/out/base-noJS-v2.mp4'
subprocess.run(['ffmpeg','-y','-v','error','-framerate','24','-i',f'{tmp}/f%04d.png','-i',f'{ROOT}/song/song.mp3',
                '-c:v','libx264','-crf','16','-preset','medium','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-shortest',out],check=True)
print('输出', out, round(os.path.getsize(out)/1e6,1),'MB')
