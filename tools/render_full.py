#!/usr/bin/env python3
"""全片分窗渲染（并行版）。

为什么分窗：单进程把 4807 张底片帧一次性塞进浏览器会 OOM（见 §17.1-5）。
为什么并行：一刀切 9 窗串行 ≈ 32 分钟；3 个 worker 并行 ≈ 12 分钟，内存够（每窗约 2.5G）。

用法：
  venv/bin/python tools/render_full.py                       # 全片，3 worker
  venv/bin/python tools/render_full.py --windows 3,4         # 只重渲这两窗
  venv/bin/python tools/render_full.py --from 150 --to 175   # 只重渲受影响时段

产物：
  out/full-v3-frames/f%04d.png   连续编号，可直接 ffmpeg 合成（帧号 = round(t*fps)）
  out/v3-render.log              每窗耗时/帧数，历史追加
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", default="shots-full-v3.json")
    ap.add_argument("--out-frames", default="out/full-v3-frames")
    ap.add_argument("--log", default="out/v3-render.log")
    ap.add_argument("--win", type=float, default=25.0)
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--from", dest="t_from", type=float, default=None)
    ap.add_argument("--to", dest="t_to", type=float, default=None)
    ap.add_argument("--windows", default=None, help="只渲这些窗号，逗号分隔，如 3,4")
    args = ap.parse_args()

    cfg = json.loads((ROOT / args.shots).read_text(encoding="utf-8"))
    fps = float(cfg.get("fps", 24))
    t_end = float(cfg["t1"])
    frames_dir = ROOT / args.out_frames
    frames_dir.mkdir(parents=True, exist_ok=True)

    wins = []
    a = 0.0
    while a < t_end - 1e-6:
        b = min(a + args.win, t_end)
        if t_end - b < 5.0:          # 尾巴并入前一窗，避免为几帧开一个浏览器
            b = t_end
        wins.append((a, b))
        if b >= t_end - 1e-6:
            break
        a = b

    if args.windows is not None:
        want = {int(x) for x in args.windows.split(",")}
        sel = [(i, w) for i, w in enumerate(wins) if i in want]
    elif args.t_from is not None:
        hi = args.t_to if args.t_to is not None else t_end
        sel = [(i, w) for i, w in enumerate(wins) if w[1] > args.t_from + 1e-6 and w[0] < hi - 1e-6]
    else:
        sel = list(enumerate(wins))

    lock = threading.Lock()
    logf = open(ROOT / args.log, "a", encoding="utf-8")

    def log(msg: str):
        with lock:
            logf.write(msg + "\n")
            logf.flush()
            print(msg, flush=True)

    log(f"\n[v3] {len(sel)} 窗 / 共 {len(wins)} 窗  总时长 {t_end}s  jobs={args.jobs} "
        f"{time.strftime('%F %T')}")

    def run_window(item):
        i, (a, b) = item
        shots = [s for s in cfg["shots"] if s["t1"] > a + 1e-6 and s["t0"] < b - 1e-6]
        sub = dict(cfg)
        sub.update({"t0": a, "t1": b, "shots": shots})
        sf = ROOT / f"shots-v3-w{i:02d}.json"
        sf.write_text(json.dumps(sub, ensure_ascii=False, indent=1), encoding="utf-8")
        od = ROOT / f"out/v3chunk{i:02d}"
        shutil.rmtree(od, ignore_errors=True)
        t = time.time()
        p = subprocess.run(
            ["node", "engine/render2.js", "--shots", sf.name,
             "--words", "song/analysis/words-fixed.json",
             "--beats", "song/analysis/beatmap.json",
             "--out", os.path.relpath(od, ROOT) + "/"],
            cwd=ROOT, capture_output=True, text=True)
        got = sorted(os.listdir(od)) if od.is_dir() else []
        base = int(round(a * fps))
        el = time.time() - t
        log(f"[v3 w{i:02d}] {a:.2f}-{b:.2f}s shots={len(shots)} frames={len(got)} "
            f"起始帧={base} 用时{el:.0f}s rc={p.returncode}")
        if p.returncode != 0 or len(got) != int(round((b - a) * fps)):
            log("  !! " + (p.stdout[-800:] + p.stderr[-800:]).replace("\n", "\n  !! "))
        for j, f in enumerate(got):
            os.replace(od / f, frames_dir / f"f{base + j:04d}.png")
        shutil.rmtree(od, ignore_errors=True)
        sf.unlink(missing_ok=True)

    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        list(ex.map(run_window, sel))

    n = len(list(frames_dir.glob("f*.png")))
    log(f"[v3] 完成，{frames_dir} 现有 {n} 帧 {time.strftime('%F %T')}")
    logf.close()


if __name__ == "__main__":
    main()
