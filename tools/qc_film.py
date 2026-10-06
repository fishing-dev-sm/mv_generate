#!/usr/bin/env python3
"""成片体检（渲染完成后跑）：帧数 / 音轨 / 每一行字幕是否真的画出来了 / 接触印相。

「有没有画出来」不是靠眼看：把渲染帧与底片帧按同样的 cover-fit 对齐后相减，
差值就是视觉层本身；在某行自己的落位区里数差值像素，少于阈值就报「疑似没画」。

用法：
  venv/bin/python tools/qc_film.py --film out/preview-v3.mp4
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
FPS = 24


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def cover_fit(img: Image.Image, W: int, H: int) -> Image.Image:
    sw, sh = img.size
    k = max(W / sw, H / sh)
    dw, dh = int(round(sw * k)), int(round(sh * k))
    im = img.resize((dw, dh), Image.BILINEAR)
    return im.crop(((dw - W) // 2, (dh - H) // 2, (dw - W) // 2 + W, (dh - H) // 2 + H))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", default="shots-full-v3.json")
    ap.add_argument("--frames", default="out/full-v3-frames")
    ap.add_argument("--base-frames", default="out/base-frames2")
    ap.add_argument("--base", default="out/base-noJS-v2.mp4")
    ap.add_argument("--film", default=None)
    ap.add_argument("--sheets", default="out/v3-qc")
    args = ap.parse_args()

    cfg = json.loads((ROOT / args.shots).read_text(encoding="utf-8"))
    W, H = cfg.get("width", 1920), cfg.get("height", 1080)
    frames = ROOT / args.frames
    base_frames = ROOT / args.base_frames
    n_expect = int(round(cfg["t1"] * FPS))
    n_have = len(list(frames.glob("f*.png")))
    print(f"[帧数] 期望 {n_expect}（{cfg['t1']}s @ {FPS}fps）  实际 {n_have}")
    if n_have < n_expect:
        print("  ✗ 帧数不足")

    if args.film:
        film = ROOT / args.film
        p = run(["ffprobe", "-v", "error", "-show_entries",
                 "stream=codec_type,codec_name,nb_frames,r_frame_rate,width,height",
                 "-of", "json", str(film)])
        try:
            info = json.loads(p.stdout)
            vs = [s for s in info["streams"] if s["codec_type"] == "video"][0]
            aud = [s for s in info["streams"] if s["codec_type"] == "audio"]
            print(f"[成片] {vs['width']}x{vs['height']} {vs['r_frame_rate']} "
                  f"{vs['nb_frames']} 帧  音轨 {aud[0]['codec_name'] if aud else '无'}")
        except Exception as e:                                    # noqa: BLE001
            print("[成片] ffprobe 解析失败:", e)
        # 音轨：与底片逐样本比对（成片音轨应当是底片音轨的原样拷贝）
        import wave
        tmp = Path("/tmp/qcfilm")
        tmp.mkdir(exist_ok=True)
        for src, tag in ((film, "out"), (ROOT / args.base, "base")):
            run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-ac", "1",
                 "-ar", "22050", "-f", "wav", str(tmp / f"{tag}.wav")])
        def samples(p):
            w = wave.open(str(p))
            raw = w.readframes(w.getnframes())
            return np.frombuffer(raw, dtype="<i2").astype(np.float64)
        xa, xb = samples(tmp / "out.wav"), samples(tmp / "base.wav")
        n = min(len(xa), len(xb))
        c = np.corrcoef(xa[:n], xb[:n])[0, 1]
        print(f"[音轨] 与底片相关 = {c:.6f}（{n / 22050:.1f}s）"
              f"{'  ✓' if c > 0.999 else '  ✗'}")

    # 逐行存在性：渲染帧 − 底片帧 = 视觉层
    lines = cfg["visual"]["lyrics"]["lines"]
    print("\n[逐行存在性] 落位区内「视觉层像素」数")
    ZONES = {"TL": (120, 196, 810, 210), "TC": (555, 186, 810, 210), "TR": (990, 196, 810, 210),
             "ML": (120, 420, 810, 210), "MC": (555, 410, 810, 220), "MR": (990, 420, 810, 210),
             "LL": (120, 546, 820, 200), "LR": (980, 546, 820, 200), "WIDE": (150, 292, 1620, 180)}
    bad = []
    for i, L in enumerate(lines):
        ats = L.get("at") or []
        peak = (max(ats) + 0.2) if ats else (L["t0"] + 0.5)
        peak = min(max(peak, L["t0"] + 0.1), L["t1"] - 0.05)
        fi = int(round(peak * FPS))
        fr = frames / f"f{fi:04d}.png"
        bs = base_frames / f"f{fi:04d}.png"
        if not fr.exists() or not bs.exists():
            bad.append((i, L["style"], "缺帧")); continue
        a = np.asarray(Image.open(fr).convert("RGB"), dtype=np.int16)
        b = np.asarray(cover_fit(Image.open(bs).convert("RGB"), W, H), dtype=np.int16)
        d = np.abs(a - b).max(axis=2)
        x, y, w, h = ZONES.get(L["zone"], ZONES["ML"])
        # 视觉层会画出落位区一点（薄板/刻度），多给 40px 余量
        sub = d[max(0, y - 40):y + h + 40, max(0, x - 40):x + w + 40]
        cnt = int((sub > 40).sum())
        flag = "" if cnt > 400 else "  ← 疑似没画出来"
        if flag:
            bad.append((i, L["style"], f"{cnt}px"))
        print(f"{i:>3} {L['style']:<8} {L['zone']:<4} t={peak:>7.2f}  层像素 {cnt:>7d}{flag}")
    print(f"\n可疑行 {len(bad)}/{len(lines)}: {bad if bad else '—'}")

    # 接触印相：每 3 秒一帧
    sheet_dir = ROOT / args.sheets
    sheet_dir.mkdir(parents=True, exist_ok=True)
    step = 3 * FPS
    picks = list(range(0, n_have, step))
    cw, ch, cols = 400, 225, 6
    for si in range(0, len(picks), 24):
        chunk = picks[si:si + 24]
        rows = (len(chunk) + cols - 1) // cols
        sheet = Image.new("RGB", (cw * cols, ch * rows), (16, 16, 18))
        dr = ImageDraw.Draw(sheet)
        for k, fi in enumerate(chunk):
            f = frames / f"f{fi:04d}.png"
            if not f.exists():
                continue
            im = Image.open(f).convert("RGB").resize((cw, ch))
            x, y = (k % cols) * cw, (k // cols) * ch
            sheet.paste(im, (x, y))
            dr.text((x + 5, y + 4), f"{fi / FPS:6.2f}s", fill=(255, 120, 190))
        out = sheet_dir / f"sheet{si // 24}.png"
        sheet.save(out)
        print("[sheet]", out)


if __name__ == "__main__":
    sys.exit(main())
