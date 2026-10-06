#!/usr/bin/env python3
"""打捞在跑的 ComfyUI prompt：按 seed 识别段 → 等完工 → 下载 → QC → 更新报告。
用法： venv/bin/python tools/salvage_running.py          # 自动识别在跑任务
      venv/bin/python tools/salvage_running.py c02      # 只打捞指定段
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mass_produce as mp
import h3_r2v_audio as h3sub

ROOT = mp.ROOT
FINAL = mp.FINAL
REPORT = mp.REPORT


def seg_seed(seg, attempt=1):
    base = 20261200 + int(seg["id"][1:]) if seg["id"][0] == "c" else 20261100 + int(seg["id"][1:])
    return base + (attempt - 1) * 1000


def qc_segment(seg, mp4):
    frames_dir = os.path.join(FINAL, f"{seg['id']}-frames")
    mp.extract_frames(mp4, frames_dir)
    info = {"shots": seg["shots"], "kind": seg["kind"], "salvaged": True}
    info["motion_pct"] = mp.qc_motion(frames_dir)
    info["firstframe_diff"] = mp.qc_firstframe(frames_dir, seg["plates"][0])
    if seg["kind"] == "container" and len([s for s in seg["shots"] if s in mp.SHOTS]) > 1:
        exp = [mp.BOARD_T0[s] - seg["window"][0] for s in seg["shots"][1:] if s in mp.SHOTS]
        cuts, ok = mp.qc_scene_cuts(mp4, exp)
        info["scene_cuts"] = cuts
        info["scene_ok"] = ok
    if seg["sung"]:
        wf = json.load(open(os.path.join(ROOT, "song/analysis/words-fixed.json")))
        lyrics = mp.lyrics_in_window(seg["window"][0], seg["window"][1], wf)
        info.update(mp.qc_sung(seg, mp4, os.path.join(ROOT, f"ref-audio-v3/{seg['id']}.wav"), lyrics))
    # QC 纪律（2026-09-30 导演改）：机器只记录，verdict 一律 pending_qc，等导演裁决
    info["verdict"] = "pending_qc"
    return info


def main():
    mp._load_board_t0()
    only = sys.argv[1] if len(sys.argv) > 1 else None
    segs = {s["id"]: s for s in json.load(open(os.path.join(ROOT, "segments.json")))["segments"]}
    client = h3sub.h3.ComfyClient(mp.SERVER)
    q = client._req("GET", "/queue")
    jobs = q.get("queue_running", []) + q.get("queue_pending", [])
    if not jobs:
        print("无在跑任务")
        return
    for job in jobs:
        pid, g = job[1], job[2]
        seed = g.get("8", {}).get("inputs", {}).get("noise_seed")
        sid = next((k for k, s in segs.items() if seed == seg_seed(s)), None)
        if only and sid != only:
            continue
        if not sid:
            print(f"pid {pid} seed {seed} 不属于任何段，跳过")
            continue
        print(f"打捞 {sid}（pid {pid}, seed {seed}）…", flush=True)
        mp.wait_and_download(client, segs[sid], pid, os.path.join(FINAL, f"{sid}.mp4"))
        info = qc_segment(segs[sid], os.path.join(FINAL, f"{sid}.mp4"))
        info["seed"] = seed
        rep = json.load(open(REPORT)) if os.path.exists(REPORT) else {}
        rep[sid] = info
        json.dump(rep, open(REPORT, "w"), ensure_ascii=False, indent=2)
        print(f"{sid}: verdict={info['verdict']} motion={info.get('motion_pct')} "
              f"ncc={info.get('ncc')} cuts={info.get('scene_cuts')}", flush=True)


if __name__ == "__main__":
    main()
