#!/usr/bin/env python3
"""扩窗重出（参数化）：窗口前移 EXT 秒，让 H3 唱出前摇 → 恢复与母带的对齐。
用法: ev_extend_regen.py <sid> <ext_sec> <seed>"""
import json, os, re, subprocess, sys, datetime
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.path.join(ROOT,"tools"))
import mass_produce as mp, h3_r2v_audio as h3sub
mp._load_board_t0()
sid, EXT, SEED = sys.argv[1], float(sys.argv[2]), int(sys.argv[3])
seg=dict({s["id"]:s for s in json.load(open(os.path.join(ROOT,"segments.json")))["segments"]}[sid])
wf=json.load(open(os.path.join(ROOT,"song/analysis/words-fixed.json")))
NEW0=round(seg["window"][0]-EXT,3); NEW1=seg["window"][1]
dur=round(NEW1-NEW0,3); frames=h3sub.h3.frames_for_duration(dur)
os.makedirs(os.path.join(ROOT,"ref-audio-v3-ext"), exist_ok=True)
ref=os.path.join(ROOT,f"ref-audio-v3-ext/{sid}.wav")
subprocess.run(["ffmpeg","-y","-v","error","-ss",str(NEW0),"-t",str(dur),"-i",os.path.join(ROOT,"song/song.mp3"),
                "-ac","1","-ar","44100",ref], check=True)
seg2=dict(seg); seg2["window"]=[NEW0,NEW1]; seg2["frames"]=frames
prompt=mp.build_prompt(seg2,wf)
prompt="\n".join(l for l in prompt.split("\n") if not re.match(r"^(第 \d+ 个画面的歌词|画外歌声的歌词)", l.strip()))
prompt+=("。演唱时机严格跟随 <Audio 1>：她的开口与 <Audio 1> 里的人声逐句重合，不抢拍、不拖尾。"
         "画面是纯影像：不得把任何文字或说明文字画进画面")
client=h3sub.h3.ComfyClient(mp.SERVER)
names=[h3sub.upload_media(client,os.path.join(ROOT,p)) for p in seg["plates"]]
aud=h3sub.upload_media(client,ref)
graph=h3sub.h3.build_prompt(mode="r2v",prompt=prompt,width=1344,height=768,length=frames,steps=6,
    seed=SEED,ref_images=names,ref_image_size="match",filename_prefix="video/example_final")
graph["6"]["inputs"]["ref_audios.ref_audio_0"]=["200",0]
graph["200"]={"class_type":"LoadAudio","inputs":{"audio":aud}}
pid=client.queue(graph)
open(os.path.join(ROOT,"clips/final/gen.log"),"a").write(
 f"[root-regen] {datetime.datetime.now():%F %T} {sid} 扩窗重出 window=[{NEW0},{NEW1}] frames={frames} seed={SEED} pid={pid}\n")
print(f"[ext] {sid} window=[{NEW0},{NEW1}] frames={frames} seed={SEED} pid={pid}")
