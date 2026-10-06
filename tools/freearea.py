#!/usr/bin/env python3
"""留白区分析：给每个镜头量一张「哪里能放字」的地图。

为什么要有这个工具：视觉层的落位纪律是「进画面留白区，不与底片主体打架」。
55 个镜头靠肉眼逐个看会漏也会偏，这里改成量出来的：

  对每镜均匀采样若干帧（取自**最终底片** out/base-frames2，不是原始 clip），
  在 1920×1080 画面坐标上算两张图——
    lum   亮度（0–1）：亮 = 底片主体 / 高光 → 压字会糊
    busy  局部梯度能量（0–1）：有纹理、有边缘、有动作 → 压字会乱
  再对一组候选矩形（zone）打分：free = 1 − (0.6·busy + 0.4·lum)
  按分数排序，就是这一镜「字该放哪儿」的客观答案。

产物：
  out/freearea.json          逐镜分数 + 逐格地图 + zone 排序
  out/freearea/sXXX.png      每镜一张 16:9 缩略图 + zone 网格叠印（用眼睛复核）
用法：
  python3 tools/freearea.py [--shots shots-full.json] [--base out/base-frames2]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT_W, OUT_H = 1920, 1080

# 候选落位矩形（画面坐标）：chrome 已占四角 / 左标尺 x<50 / 翻牌长条 y788-874 /
# ticker y>1024，所以候选一律落在 y∈[170,780] 这条「可读带」里。
ZONES = {
    "TL": (120, 196, 800, 210),
    "TC": (560, 186, 800, 210),
    "TR": (1000, 196, 800, 210),
    "ML": (120, 430, 800, 210),
    "MC": (560, 420, 800, 220),
    "MR": (1000, 430, 800, 210),
    "LL": (120, 560, 820, 200),
    "LR": (980, 560, 820, 200),
    "WIDE": (150, 300, 1620, 170),
    "BIG": (360, 250, 1200, 420),
}


def cover_map(x_o, y_o, iw, ih):
    """画面坐标 → 源帧坐标（引擎的 cover-fit：铺满 1920×1080 居中裁切）。"""
    s = max(OUT_W / iw, OUT_H / ih)
    ox = (OUT_W - iw * s) / 2
    oy = (OUT_H - ih * s) / 2
    return (np.asarray(x_o) - ox) / s, (np.asarray(y_o) - oy) / s


def frame_maps(img: Image.Image, gw=16, gh=9):
    """一帧 → 亮度图 / 忙乱图 / 运动图（都归一到 0–1，网格 gw×gh）。"""
    iw, ih = img.size
    small = img.convert("L")
    a = np.asarray(small, dtype=np.float32) / 255.0
    gx = np.zeros_like(a)
    gy = np.zeros_like(a)
    gx[:, 1:-1] = np.abs(a[:, 2:] - a[:, :-2]) * 0.5
    gy[1:-1, :] = np.abs(a[2:, :] - a[:-2, :]) * 0.5
    busy = gx + gy
    # 网格归并（用画面坐标的等分，因此先把源图按 cover-fit 重采样到 1920×1080）
    lum_full = np.asarray(img.convert("L").resize((OUT_W, OUT_H), Image.BILINEAR), dtype=np.float32) / 255.0
    busy_full = np.asarray(
        Image.fromarray(np.clip(busy * 255.0 * 4, 0, 255).astype(np.uint8)).resize((OUT_W, OUT_H), Image.BILINEAR),
        dtype=np.float32) / 255.0

    def grid(m):
        g = m.reshape(gh, OUT_H // gh, gw, OUT_W // gw).mean(axis=(1, 3))
        return g

    return grid(lum_full), grid(busy_full)


def zone_score(free_img, zone):
    x, y, w, h = zone
    # 从逐格地图插值到像素级「可放性」，再取矩形均值
    gh, gw = free_img.shape
    ys = np.clip(((np.arange(y, y + h) + 0.5) / OUT_H * gh - 0.5).round().astype(int), 0, gh - 1)
    xs = np.clip(((np.arange(x, x + w) + 0.5) / OUT_W * gw - 0.5).round().astype(int), 0, gw - 1)
    return float(free_img[np.ix_(ys, xs)].mean())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", default="shots-full.json")
    ap.add_argument("--base", default="out/base-frames2")
    ap.add_argument("--samples", type=int, default=6)
    ap.add_argument("--thumbs", action="store_true", default=True)
    ap.add_argument("--no-thumbs", dest="thumbs", action="store_false")
    args = ap.parse_args()

    cfg = json.loads((ROOT / args.shots).read_text(encoding="utf-8"))
    fps = float(cfg.get("fps", 24))
    base = ROOT / args.base
    files = sorted(base.glob("f*.png"))
    if not files:
        raise SystemExit(f"底片帧目录为空：{base}")
    nframes = len(files)
    thumb_dir = ROOT / "out/freearea"
    if args.thumbs:
        thumb_dir.mkdir(parents=True, exist_ok=True)

    report = {"base": str(base), "nframes": nframes, "fps": fps, "shots": {}}
    for s in cfg["shots"]:
        t0, t1 = float(s["t0"]), float(s["t1"])
        span = max(0.0, t1 - t0)
        ts = [t0 + span * (i + 0.5) / args.samples for i in range(args.samples)]
        idxs = [min(nframes - 1, max(0, int(round(t * fps)))) for t in ts]
        lums, busys, thumbs = [], [], []
        for i in idxs:
            im = Image.open(files[i]).convert("RGB")
            lu, bu = frame_maps(im)
            lums.append(lu)
            busys.append(bu)
            thumbs.append(im)
        lum = np.median(np.stack(lums), axis=0)
        busy = np.median(np.stack(busys), axis=0)
        free = 1.0 - np.clip(0.62 * busy + 0.42 * lum, 0, 1)
        zs = {k: round(zone_score(free, v), 3) for k, v in ZONES.items()}
        order = sorted(zs.items(), key=lambda kv: -kv[1])
        report["shots"][s["id"]] = {
            "t0": t0, "t1": t1,
            "lum": np.round(lum, 3).tolist(),
            "busy": np.round(busy, 3).tolist(),
            "zones": zs,
            "rank": [k for k, _ in order],
        }
        if args.thumbs:
            # 拼一张「最忙的一帧」做底：它最难放字，按它定位置最保守
            k = int(np.argmax([b.mean() for b in busys]))
            canv = thumbs[k].convert("RGB").resize((OUT_W, OUT_H), Image.LANCZOS)
            d = ImageDraw.Draw(canv, "RGBA")
            for name, (x, y, w, h) in ZONES.items():
                v = zs[name]
                col = (0, 220, 140, 150) if v >= 0.72 else ((255, 175, 0, 130) if v >= 0.6 else (255, 70, 70, 110))
                d.rectangle([x, y, x + w, y + h], outline=col, width=3)
                d.text((x + 8, y + 6), f"{name} {v:.2f}", fill=col)
            d.text((8, 8), f"{s['id']}  {t0:.2f}-{t1:.2f}s  best={order[0][0]}"
                            f"({order[0][1]:.2f})", fill=(255, 255, 255, 230))
            canv.save(thumb_dir / f"{s['id']}.png")
        print(f"{s['id']:5s} {t0:7.2f}-{t1:7.2f}  " +
              "  ".join(f"{k}:{v:.2f}" for k, v in order[:4]))

    (ROOT / "out/freearea.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("-> out/freearea.json", "| thumbs -> out/freearea/" if args.thumbs else "")


if __name__ == "__main__":
    main()
