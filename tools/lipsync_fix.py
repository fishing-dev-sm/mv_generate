#!/usr/bin/env python3
"""§7 修复器：对一个演唱镜执行一次"切镜 + 续镜"。
- 输入：shot, 掉线时刻 T（歌曲秒）
- 切点 = T 之前最后一个八分音符（0.22s 网格，取自 beatmap）
- 续镜 = 以"切点那一帧"为 <Picture 1>、母带 [cut, t1+0.5] 为 <Audio 1> 的 H3 r2v
- 产出：clips/final/cont-{shot}-{k}.mp4，并把该镜的 plan 更新为 [前半段 ...] + [续镜 0..n]
"""
import json, os, subprocess, sys, datetime, time
sys.path.insert(0,'tools'); import mass_produce as mp, h3_r2v_audio as h3sub
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FPS=24
TAKE={"c07":"c07-attempt2","i03":"i03-attempt4","c14":"c14-attempt2"}
T0={}; T1={}
import re
for m in re.finditer(r'\| (s\d{3}) \| ([\d.]+) \| ([\d.]+) \|', open(f'{ROOT}/storyboard/board-final.md',encoding='utf8').read()):
    T0[m.group(1)]=float(m.group(2)); T1[m.group(1)]=float(m.group(3))
SEG={}
for s in json.load(open(f'{ROOT}/segments.json'))['segments']:
    for sh in s['shots']: SEG[sh]=(s['id'], s['window'][0], TAKE.get(s['id'], s['id']))
wf=json.load(open(f'{ROOT}/song/analysis/words-fixed.json'))
beats=json.load(open(f'{ROOT}/song/analysis/beatmap.json'))['beats']

def last_eighth_before(t):
    grid=0.22
    k=int(t/grid)
    c=round(k*grid,3)
    while c >= t-1e-6: k-=1; c=round(k*grid,3)
    return max(c,0.0)

def frame_at(pieces, song_t):
    """在计划里定位 song_t 对应的源帧文件"""
    cur=T0_shot
    for p in pieces:
        dur=p['n']/FPS
        if song_t <= cur+dur+1e-6:
            fi=p['f0']+int(round((song_t-cur)*FPS))
            d=os.path.join(ROOT,f"clips/final/{p['src']}-frames")
            fs=sorted(f for f in os.listdir(d) if f.endswith('.png'))
            fi=min(max(fi,0),len(fs)-1)
            return os.path.join(d,fs[fi])
        cur+=dur
    return None

def gen_continuation(shot, cut, k, seed):
    sid,w0,take=SEG[shot]; t1=T1[shot]
    tail=0.5; end=min(t1+tail, 200.0)
    dur=end-cut; frames=h3sub.h3.frames_for_duration(dur)
    ref=os.path.join(ROOT,f"ref-audio-v3-ext/{shot}-cut{k}.wav")
    os.makedirs(os.path.dirname(ref),exist_ok=True)
    subprocess.run(['ffmpeg','-y','-v','error','-ss',f'{cut:.4f}','-t',f'{dur:.4f}','-i',f'{ROOT}/song/song.mp3',
                    '-ac','1','-ar','44100',ref],check=True)
    plate=frame_at(json.load(open(f'{ROOT}/out/lipsync-plan.json'))[shot], cut)
    words=' '.join(re.sub(r'[^\u4e00-\u9fff]','',x['word']) for x in wf['words'] if cut-0.2<=x['start']<end)
    prompt=(f"CUT 1：<Picture 1> 的角色跟着 <Audio 1> 的歌声演唱，嘴型和节奏严格跟随 <Audio 1> 里的人声，"
            f"她用女声演唱，是年轻女性的歌声，同一机位同一景别，动作与上一帧连续，镜头固定微推。"
            f"全片连续性条款：冷峻电影感，蓝黑与钢蓝色调，一盏红色小灯是画面中唯一暖色，细腻胶片颗粒。"
            f"画面是纯影像：不得把任何文字、歌词或说明文字画进画面，画面里不出现字幕条")
    if words: prompt += f"\n歌词：\"{words}\""
    client=h3sub.h3.ComfyClient(mp.SERVER)
    names=[h3sub.upload_media(client, plate)]
    aud=h3sub.upload_media(client, ref)
    graph=h3sub.h3.build_prompt(mode="r2v",prompt=prompt,width=1344,height=768,length=frames,steps=6,
        seed=seed,ref_images=names,ref_image_size="match",filename_prefix="video/ev_cont")
    graph["6"]["inputs"]["ref_audios.ref_audio_0"]=["200",0]
    graph["200"]={"class_type":"LoadAudio","inputs":{"audio":aud}}
    pid=client.queue(graph)
    print(f"[fix] {shot} 续镜#{k} 切点 {cut:.2f}s 长 {dur:.2f}s frames={frames} seed={seed} pid={pid}", flush=True)
    t0=time.time()
    while True:
        time.sleep(15)
        h=client._req("GET", f"/history/{pid}")
        if pid in h:
            st=h[pid].get("status",{})
            if st.get("status_str")=="error": raise RuntimeError(f"续镜生成失败: {st.get('messages')}")
            if st.get("completed"):
                img=h[pid]["outputs"]["15"]["images"][0]
                data=client._req("GET", f"/view?filename={img['filename']}&subfolder={img.get('subfolder','')}&type=output", raw=True, timeout=600)
                out=os.path.join(ROOT,f"clips/final/cont-{shot}-{k}.mp4")
                open(out+".part","wb").write(data); os.replace(out+".part", out)
                print(f"[fix] {shot} 续镜#{k} 完成 {os.path.getsize(out)/1e6:.2f}MB 用时{(time.time()-t0)/60:.1f}min", flush=True)
                return out, frames
        if time.time()-t0 > 40*60: raise TimeoutError("续镜超时")

if __name__=='__main__':
    shot=sys.argv[1]; T=float(sys.argv[2]); k=int(sys.argv[3])
    global T0_shot; T0_shot=T0[shot]
    plan=json.load(open(f'{ROOT}/out/lipsync-plan.json'))
    cut=last_eighth_before(T)
    if cut <= T0[shot] + 0.35:
        cut = T0[shot]          # 掉线在开头 → 整镜重出（续镜从第一帧接）
    seed=20278000 + int(re.sub(r'\D','',shot))*10 + k
    out, frames = gen_continuation(shot, cut, k, seed)
    # 更新 plan：保留 cut 之前的部分，其余用续镜
    sid,w0,take=SEG[shot]; t0,t1=T0[shot],T1[shot]
    new=[]; cur=t0
    for p in plan[shot]:
        dur=p['n']/FPS
        if cur+dur <= cut+1e-6: new.append(p)
        else:
            keep=int(round((cut-cur)*FPS))
            if keep>0: new.append({"src":p['src'],"f0":p['f0'],"n":keep})
            break
        cur+=dur
    new.append({"src":f"cont-{shot}-{k}","f0":0,"n":int(round((t1-cut)*FPS))})
    plan[shot]=new
    json.dump(plan, open(f'{ROOT}/out/lipsync-plan.json','w'), ensure_ascii=False, indent=1)
    print(f"[fix] {shot} plan 更新：{[ (p['src'],p['n']) for p in new ]}", flush=True)
