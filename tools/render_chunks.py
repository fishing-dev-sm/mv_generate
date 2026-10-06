#!/usr/bin/env python3
"""分窗渲染全片（规避单进程载入 12255 帧导致浏览器内存崩）。

用法：
  # 全片重渲（每窗 25s，共 9 窗，约 40 分钟）
  venv/bin/python tools/render_chunks.py

  # 只重渲受影响的时间窗（改了一条歌词/换了 take 之后最常用）
  venv/bin/python tools/render_chunks.py --from 125 --to 150
  venv/bin/python tools/render_chunks.py --windows 5,6,7

产物：
  out/full-frames/f%04d.png（连续编号，可直接 ffmpeg 合成）
  out/chunk-render.log（每窗耗时/帧数，历史追加）

说明：引擎会自动读取 song/analysis/lines.json（逐字歌词）与 wave-envelope.json，
不需要额外传参；缺任何一个都能跑（歌词层会退回 v1 段落样式）。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIN = 25.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", default="shots-full.json")
    ap.add_argument("--out-frames", default="out/full-frames")
    ap.add_argument("--log", default="out/chunk-render.log")
    ap.add_argument("--from", dest="t_from", type=float, default=None)
    ap.add_argument("--to", dest="t_to", type=float, default=None)
    ap.add_argument("--windows", default=None, help="只渲这些窗号，逗号分隔，如 5,6,7")
    ap.add_argument("--keep", action="store_true", help="保留每窗原始目录（默认搬进 out/full-frames 后删）")
    args = ap.parse_args()

    cfg = json.loads((ROOT / args.shots).read_text(encoding="utf-8"))
    t_end = float(cfg["t1"])
    frames_dir = ROOT / args.out_frames
    frames_dir.mkdir(parents=True, exist_ok=True)

    windows = []
    a = 0.0
    while a < t_end - 1e-6:
        windows.append((a, min(a + WIN, t_end)))
        a += WIN

    if args.windows is not None:
        want = {int(x) for x in args.windows.split(",")}
        windows = [w for i, w in enumerate(windows) if i in want]
    elif args.t_from is not None:
        lo = args.t_from
        hi = args.t_to if args.t_to is not None else t_end
        windows = [w for w in windows if w[1] > lo + 1e-6 and w[0] < hi - 1e-6]

    log = open(ROOT / args.log, "a", encoding="utf-8")
    log.write(f"\n[chunks] {len(windows)} 窗 总时长 {t_end}s {time.strftime('%F %T')}\n")
    log.flush()

    for i, (a, b) in enumerate(windows):
        shots = [s for s in cfg["shots"] if s["t1"] > a + 1e-6 and s["t0"] < b - 1e-6]
        sub = dict(cfg)
        sub.update({"t0": a, "t1": b, "shots": shots})
        sf = ROOT / f"shots-chunk{int(a/25):02d}.json"
        sf.write_text(json.dumps(sub, ensure_ascii=False, indent=1), encoding="utf-8")
        od = ROOT / f"out/chunk{int(a/25):02d}"
        shutil.rmtree(od, ignore_errors=True)
        t = time.time()
        p = subprocess.run(
            ["node", "engine/render2.js", "--shots", sf.name,
             "--words", "song/analysis/words-fixed.json",
             "--beats", "song/analysis/beatmap.json",
             "--out", os.path.relpath(od, ROOT) + "/"],
            cwd=ROOT, capture_output=True, text=True)
        got = sorted(os.listdir(od)) if od.is_dir() else []
        base = int(round(a * float(cfg.get("fps", 24))))
        log.write(f"[chunk {int(a/25):02d}] {a:.2f}-{b:.2f}s shots={len(shots)} "
                  f"frames={len(got)} 起始帧={base} 用时{time.time()-t:.0f}s rc={p.returncode}\n")
        if p.returncode != 0:
            log.write((p.stdout[-1500:] + p.stderr[-1500:]) + "\n")
        log.flush()
        for j, f in enumerate(got):
            os.replace(od / f, frames_dir / f"f{base + j:04d}.png")
        if not args.keep:
            shutil.rmtree(od, ignore_errors=True)
    log.write(f"[chunks] 完成 {time.strftime('%F %T')}\n")
    log.close()
    print("done:", ", ".join(f"{a:.0f}-{b:.0f}" for a, b in windows))


if __name__ == "__main__":
    main()
