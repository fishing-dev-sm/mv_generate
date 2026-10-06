#!/usr/bin/env python3
"""一行一首的自查接触印相：每行歌词取「唱完那一瞬间」的成片帧，12 张一页。

用途：审"这 66 行分别是什么装置、落位对不对、有没有重复"——一页看完，不必拉片。

用法：venv/bin/python tools/line_sheet.py [--frames out/full-v3-frames] [--out out/v3-qc]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
FPS = 24


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", default="shots-full-v3.json")
    ap.add_argument("--frames", default="out/full-v3-frames")
    ap.add_argument("--out", default="out/v3-qc")
    args = ap.parse_args()
    cfg = json.loads((ROOT / args.shots).read_text(encoding="utf-8"))
    lines = cfg["visual"]["lyrics"]["lines"]
    frames = ROOT / args.frames
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)

    cw, ch, cols, per = 640, 360, 2, 8
    for si in range(0, len(lines), per):
        chunk = list(enumerate(lines))[si:si + per]
        rows = (len(chunk) + cols - 1) // cols
        sheet = Image.new("RGB", (cw * cols, (ch + 22) * rows), (14, 14, 16))
        dr = ImageDraw.Draw(sheet)
        for k, (i, L) in enumerate(chunk):
            ats = [t for t in (L.get("at") or []) if t]
            peak = (max(ats) + 0.2) if ats else (L["t0"] + 0.5)
            peak = min(max(peak, L["t0"] + 0.1), L["t1"] - 0.05)
            f = frames / f"f{int(round(peak * FPS)):04d}.png"
            x, y = (k % cols) * cw, (k // cols) * (ch + 22)
            if f.exists():
                sheet.paste(Image.open(f).convert("RGB").resize((cw, ch)), (x, y))
            label = f"{i:>2} {L['style']:<8} {L['zone']:<4} {peak:7.2f}s  {L['text'][:26]}"
            dr.text((x + 6, y + ch + 5), label, fill=(255, 120, 190))
        p = out / f"lines{si // per}.png"
        sheet.save(p)
        print("[linesheet]", p)


if __name__ == "__main__":
    main()
