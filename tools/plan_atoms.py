#!/usr/bin/env python3
"""把 Figma《01 · 设计规范（中文）》里的 21 件**意义层原子件**排进全片。

导演指令（2026-10-02）：
  「目前用到的 figma 设计元素较为单一……这些原子件也你通过你的审美去理解他们，
    将他们都充分的应用到最终的剪辑里，使得画面变得丰富、灵动。」

行表（shots-full-v3.json 的 visual.lyrics）解决的是"这句话本身长什么样"；
本表解决的是"这句话旁边那件**解释它的物证**长什么样"——图表卡 / 收据卡 / 终端窗口 /
清单卡 / 阶梯卡 / 环形仪表 / 引线标注 …… 共 21 件，全部来自 `4:2`–`5:354`。

三条落位纪律（脚本会自动体检）：
  ① 卡片放在**歌词装置的对面**（左/右），绝不压住正在唱的那一行；
  ② 卡片入场落在拍上（`enterAt` 吸附到下一个拍），节奏与歌词装置同网格；
  ③ 卡片只画在它自己的时间窗里（`exitAt`），跨镜时复制进每一个重叠的镜头。

用法：python3 tools/plan_atoms.py [--in shots-full-v3.json] [--out shots-full-v4.json]
"""

from __future__ import annotations

import argparse
import bisect
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 落位区（与 visual.js 的 ZONES 一致）——用来做"不压歌词"的体检
ZONES = {
    "TL": (120, 196, 810, 210), "TC": (555, 186, 810, 210), "TR": (990, 196, 810, 210),
    "ML": (120, 420, 810, 210), "MC": (555, 410, 810, 220), "MR": (990, 420, 810, 210),
    "LL": (120, 546, 820, 200), "LR": (980, 546, 820, 200), "WIDE": (150, 292, 1620, 180),
}
RIGHT_EDGE = 1830          # 卡片右对齐时的右边线（留 90px 安全边）

# ---------------------------------------------------------------------------
# 原子件排期表
#   (t0, t1, side, y, w, h, atom, params)
#     side  卡片放哪一侧：L=左列 / R=右列（x 由 w 与 side 推出）
#     t0/t1 期望时间窗（脚本会把入场吸附到拍上）
#   文案原则：数字要么来自歌词本身，要么来自本项目实测（BPM / 拍长 / 时长 / 镜数）；
#             不编造"看起来很真"的第三方数据。
# ---------------------------------------------------------------------------
PLAN = [

    (2.30, 6.60, "L", 250, 480, 300, "toast", dict(
        head="示例", time="示例", title="示例",
        body="示例",
        rows=["示例", "示例"])),
    (8.60, 12.70, "R", 300, 340, 300, "tracking", dict(
        label="示例")),
    (15.20, 19.00, "L", 240, 620, 330, "chart", dict(
        title="示例", meta="示例", base="示例",
        values=[40, 52, 61, 70, 85, 120], max=150, axis=["0", "50", "100", "125", "150"],
        note="示例", value="示例")),
    (23.80, 27.20, "R", 270, 380, 300, "gauge", dict(unit="示例")),
    (27.70, 30.50, "L", 300, 480, 260, "toggles", dict(
        title="示例", rows=[dict(k="示例", v="示例"), dict(k="示例", v="示例")],
        notes=["示例", "示例"])),
    (31.00, 34.10, "L", 190, 540, 520, "receipt", dict(
        head="示例", no="示例", sub="示例",
        big="示例",
        rows=[dict(k="示例", v="示例"), dict(k="示例", v="示例", old=True),
              dict(k="示例", v="示例")],
        pct=dict(k="示例", v="示例"), foot="示例", stamp="示例")),
    (34.60, 37.30, "L", 220, 480, 400, "checklist", dict(
        title="示例", meta="示例",
        rows=[dict(k="示例", v="示例"), dict(k="示例", v="示例"),
              dict(k="示例", v="示例"), dict(k="示例", v="示例")],
        note="示例")),
    (37.80, 39.90, "R", 260, 420, 280, "leader", dict(
        items=[dict(px=300, py=300, t="示例"),
               dict(px=520, py=180, t="示例")])),
    (41.40, 43.70, "L", 280, 560, 300, "donut", dict(
        value=0.6,
        legend=[dict(k="示例", v="示例", p=0.6),
                dict(k="示例", v="示例", p=0.4)])),
    (46.95, 47.75, "R", 300, 380, 180, "stat", dict(
        label="示例", start=0, end=143)),
    (48.20, 50.05, "L", 250, 600, 340, "terminal", dict(
        title="示例", path="示例", model="示例",
        lines=[dict(t="示例"),
               dict(t="示例", kind="add"),
               dict(t="示例", kind="del"),
               dict(t="示例", kind="add"),
               dict(t="示例")],
        hint="示例")),
    (50.30, 51.80, "L", 430, 480, 160, "strike", dict(
        parts=[dict(t="示例", old=True), dict(t="示例", old=False)],
        note="示例")),
    (54.00, 55.85, "R", 250, 720, 320, "fontmode", dict(
        masthead="示例", subtitle="示例",
        caller1="示例", caller2="示例")),
    (56.20, 57.15, "L", 320, 420, 200, "stat", dict(
        label="示例", start=1, end=1000000)),
    (57.60, 59.88, "R", 250, 560, 300, "carelabel", dict(
        title="示例", code="示例",
        rows=[dict(k="示例", v="示例", pct="100%"), dict(k="示例", v="示例", pct="100%")],
        note="示例")),
    (60.30, 63.40, "R", 220, 560, 400, "struct", dict(
        title="示例", tag="示例",
        layers=[dict(k="示例", v="示例"),
                dict(k="示例", v="示例"),
                dict(k="示例", v="示例")],
        note="示例")),
    (63.80, 66.60, "L", 230, 460, 340, "checklist", dict(
        title="示例", meta="示例",
        rows=[dict(k="示例", v="示例"), dict(k="示例", v="示例"), dict(k="示例", v="示例")],
        note="示例")),


    (67.00, 69.70, "L", 260, 460, 300, "toast", dict(
        head="示例", time="示例", title="示例",
        body="示例", rows=["示例", "示例"])),
    (70.20, 73.25, "R", 250, 620, 330, "chart", dict(
        title="示例", meta="示例",
        values=[120, 110, 90, 70, 40, 10], max=150, axis=["0", "50", "100", "150"],
        note="示例", value="示例")),
    (73.80, 76.50, "L", 240, 480, 340, "checklist", dict(
        title="示例", meta="示例",
        rows=[dict(k="示例", v="示例"), dict(k="示例", v="示例"),
              dict(k="示例", v="示例")],
        note="示例")),
    (77.50, 80.30, "R", 230, 600, 330, "terminal", dict(
        title="示例", path="示例", model="示例",
        lines=[dict(t="示例"),
               dict(t="示例", kind="del"),
               dict(t="示例", kind="add"),
               dict(t="示例")],
        hint="示例")),
    (80.70, 83.70, "L", 420, 400, 130, "microtags", dict(
        items=[dict(t="示例"), dict(t="示例"),
               dict(t="示例"), dict(t="示例", acc=True)])),
    (84.20, 87.10, "R", 220, 520, 400, "scanner", dict(
        title="示例", meta="示例", sub="示例",
        total=120, status="示例", plat="示例")),
    (89.90, 92.40, "R", 300, 380, 180, "stat", dict(
        label="示例", start=0, end=143)),
    (93.40, 94.60, "L", 430, 480, 160, "strike", dict(
        parts=[dict(t="示例", old=True), dict(t="示例", old=False)],
        note="示例")),
    (96.80, 98.40, "R", 250, 720, 320, "fontmode", dict(
        masthead="示例", subtitle="示例",
        caller1="示例", caller2="示例")),
    (100.30, 102.70, "R", 220, 560, 400, "struct", dict(
        title="示例", tag="示例",
        layers=[dict(k="示例", v="示例"),
                dict(k="示例", v="示例"),
                dict(k="示例", v="示例")],
        note="示例")),


    (103.20, 106.70, "R", 240, 620, 330, "chart", dict(
        title="示例", meta="示例",
        values=[130, 120, 100, 80, 60, 40], max=150, axis=["0", "50", "100", "150"],
        note="示例", value="示例")),
    (107.30, 109.10, "L", 300, 420, 200, "stat", dict(
        label="示例", start=0, end=1000000)),
    (110.60, 112.50, "L", 190, 540, 520, "receipt", dict(
        head="示例", no="示例", sub="示例",
        big="示例",
        rows=[dict(k="示例", v="示例"), dict(k="示例", v="示例", old=True),
              dict(k="示例", v="示例")],
        pct=dict(k="示例", v="示例"), foot="示例", stamp="示例")),
    (113.60, 116.40, "L", 260, 420, 280, "leader", dict(
        items=[dict(px=300, py=320, t="示例"),
               dict(px=560, py=200, t="示例")])),
    (117.00, 120.40, "R", 250, 470, 310, "toast", dict(
        head="示例", time="示例", title="示例",
        body="示例", rows=["示例", "示例"])),
    (121.20, 123.90, "R", 220, 500, 400, "specimen", {
        "title": "示例", "tag": "示例", "big": "示例", "from": "示例",
        "value": "示例",
        "rows": [dict(k="示例", v="示例"), dict(k="示例", v="示例"),
                 dict(k="示例", v="示例")]}),
    (125.00, 127.50, "L", 230, 460, 400, "ladder", dict(
        title="示例", tag="示例",
        rows=["示例", "示例", "示例"], dv="示例",
        note="示例")),
    (128.10, 130.90, "L", 240, 480, 340, "checklist", dict(
        title="示例", meta="示例",
        rows=[dict(k="示例", v="示例"), dict(k="示例", v="示例"),
              dict(k="示例", v="示例")],
        note="示例")),
    (131.20, 133.40, "R", 250, 560, 300, "carelabel", dict(
        title="示例", code="示例",
        rows=[dict(k="示例", v="示例", pct="0%"), dict(k="示例", v="示例", pct="100%")],
        note="示例")),
    (134.40, 137.60, "L", 280, 560, 300, "donut", dict(
        value=1.0,
        legend=[dict(k="示例", v="示例", p=1), dict(k="示例", v="示例", p=0)])),
    (138.40, 140.60, "L", 250, 600, 330, "terminal", dict(
        title="示例", path="示例", model="示例",
        lines=[dict(t="示例"),
               dict(t="示例", kind="add"),
               dict(t="示例", kind="add"),
               dict(t="示例")],
        hint="示例")),
    (141.00, 143.50, "L", 260, 460, 320, "echo", dict(
        word="示例", taps=4, db=["-8.0", "-5.5", "-8.0", "-8.7"],
        note="示例")),
    (144.00, 147.00, "R", 220, 520, 420, "ladder", dict(
        title="示例", tag="示例",
        rows=["示例", "示例", "示例"],
        dv="示例", note="示例")),
    (147.90, 150.60, "L", 280, 560, 300, "donut", dict(
        value=1.0,
        legend=[dict(k="示例", v="示例", p=1), dict(k="示例", v="示例", p=1)])),
    (150.90, 153.20, "L", 230, 460, 400, "ladder", dict(
        title="示例", tag="示例",
        rows=["示例", "示例", "示例"],
        dv="示例", note="示例")),
    (154.60, 157.30, "R", 250, 470, 310, "toast", dict(
        head="示例", time="示例", title="示例",
        body="示例", rows=["示例", "示例"])),
    (157.90, 159.90, "L", 300, 380, 300, "gauge", dict(unit="示例")),
    (160.50, 162.50, "R", 220, 500, 400, "specimen", {
        "title": "示例", "tag": "示例", "big": "示例", "from": "示例",
        "value": "示例",
        "rows": [dict(k="示例", v="示例"), dict(k="示例", v="示例"),
                 dict(k="示例", v="示例")]}),
    (164.00, 166.85, "L", 250, 560, 300, "carelabel", dict(
        title="示例", code="示例",
        rows=[dict(k="示例", v="示例", pct="100%"), dict(k="示例", v="示例", pct="100%")],
        note="示例")),
    (167.30, 171.00, "R", 260, 520, 300, "leader", dict(
        items=[dict(px=260, py=300, t="示例"),
               dict(px=520, py=170, t="示例")], dash=True)),


    (173.90, 175.20, "R", 300, 380, 180, "stat", dict(
        label="示例", start=0, end=143)),
    (180.70, 182.40, "R", 250, 720, 320, "fontmode", dict(
        masthead="示例", subtitle="示例",
        caller1="示例", caller2="示例")),
    (182.80, 184.00, "L", 320, 420, 200, "stat", dict(
        label="示例", start=1, end=1000000)),
    (187.30, 189.70, "L", 380, 420, 130, "microtags", dict(
        items=[dict(t="示例"), dict(t="示例"),
               dict(t="示例", acc=True), dict(t="示例")])),
    (190.40, 194.20, "L", 230, 600, 420, "mix", dict(
        title="示例", tag="示例",
        marks=["示例", "示例"], call="示例",
        taps=["back", "back", "back", "back"],
        note="示例")),
    (195.90, 199.60, "L", 300, 460, 200, "flapboard", dict(
        text="示例", accent=[2, 3, 4],
        note="示例",
        line="示例")),
]


def rect(spec):
    return (spec["x"], spec["y"], spec["w"], spec["h"])


def overlap(a, b, m=12):
    return not (a[0] + a[2] + m <= b[0] or b[0] + b[2] + m <= a[0]
                or a[1] + a[3] + m <= b[1] or b[1] + b[3] + m <= a[1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", default="shots-full-v3.json")
    ap.add_argument("--out", dest="dst", default="shots-full-v4.json")
    ap.add_argument("--report", default="out/qc-atoms.json")
    args = ap.parse_args()

    cfg = json.loads((ROOT / args.src).read_text(encoding="utf-8"))
    beats = json.loads((ROOT / "song/analysis/beatmap.json").read_text(encoding="utf-8"))["beats"]

    def next_beat(t):
        i = bisect.bisect_left(beats, t - 1e-6)
        return round(beats[min(i, len(beats) - 1)], 3)

    # 歌词行的可见区间（入场 = 首字，离场 = cutAt 或下一行首字）
    lines = cfg["visual"]["lyrics"]["lines"]
    span = []
    for i, L in enumerate(lines):
        cs = L.get("at") or []
        s0 = cs[0] if cs else L["t0"]
        if i + 1 < len(lines):
            nxt = lines[i + 1]
            ncs = nxt.get("at") or []
            e0 = L.get("cutAt") or (ncs[0] if ncs else nxt["t0"])
        else:
            e0 = cfg["t1"]
        span.append((L["style"], L["zone"], s0, e0))

    def blocked(rect_, t):
        """t 时刻这张卡会不会压住正在唱的那一行"""
        for (style, zone, s0, e0) in span:
            if s0 - 1e-6 <= t < e0 - 1e-6 and overlap(rect_, ZONES[zone]):
                return f"{style}/{zone}"
        return None

    cards = []
    for (t0, t1, side, y, w, h, atom, params) in PLAN:
        x = 60 if side == "L" else RIGHT_EDGE - w
        r = (x, y, w, h)
        i0 = bisect.bisect_left(beats, t0 - 1e-6)
        enter = round(beats[min(i0, len(beats) - 1)], 3)
        # 离场：从入场拍往后走，走到"下一拍会压住歌词"或超过期望终点为止
        exit_ = enter
        i = i0
        while i < len(beats) and beats[i] <= t1 + 1e-6:
            b = round(beats[i], 3)
            if b > enter and blocked(r, b):
                break
            exit_ = b
            i += 1
        spec = {"atom": atom, "x": x, "y": y, "w": w, "h": h,
                "enterAt": enter, "exitAt": exit_, "side": side}
        spec.update(params)
        cards.append(spec)

    # ① 不压歌词（自动化后应当为 0）
    problems = []
    for c in cards:
        if c["exitAt"] - c["enterAt"] < 0.4:
            problems.append(f"{c['atom']}@{c['enterAt']:.2f} 窗口过短（{c['exitAt'] - c['enterAt']:.2f}s）")
        for (style, zone, s0, e0) in span:
            for t in (c["enterAt"], (c["enterAt"] + c["exitAt"]) / 2, c["exitAt"] - 0.02):
                if s0 - 1e-6 <= t < e0 - 1e-6 and overlap(rect(c), ZONES[zone]):
                    problems.append(f"{c['atom']}@{c['enterAt']:.2f}-{c['exitAt']:.2f} "
                                    f"压住 {style}/{zone} ({s0:.2f}-{e0:.2f})")
                    break

    # ② 卡片之间不重叠
    for i in range(len(cards)):
        for j in range(i + 1, len(cards)):
            a, b = cards[i], cards[j]
            if a["exitAt"] <= b["enterAt"] + 1e-6 or b["exitAt"] <= a["enterAt"] + 1e-6:
                continue
            if overlap(rect(a), rect(b)):
                problems.append(f"{a['atom']} 与 {b['atom']} 同时占位 ({a['enterAt']:.2f})")

    # ③ 卡片不许压 chrome（顶部 130 / 底部 bar 计数 780 以下）
    for c in cards:
        if c["y"] < 150:
            problems.append(f"{c['atom']} 顶到 chrome（y={c['y']}）")
        if c["y"] + c["h"] > 770:
            problems.append(f"{c['atom']} 压到翻牌长条（y+h={c['y'] + c['h']}）")

    # 注入：任何与该卡时间窗重叠的镜头都拿到同一份 spec（跨镜不断）
    for s in cfg["shots"]:
        mine = [c for c in cards if c["exitAt"] > s["t0"] + 1e-6 and c["enterAt"] < s["t1"] - 1e-6]
        if mine:
            s["cards"] = mine

    n_shots = sum(1 for s in cfg["shots"] if s.get("cards"))
    kinds = sorted({c["atom"] for c in cards})
    (ROOT / args.dst).write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    rep = {"cards": len(cards), "kinds": kinds, "shots_with_cards": n_shots,
           "problems": problems, "table": [{k: c[k] for k in
           ("atom", "side", "x", "y", "w", "h", "enterAt", "exitAt")} for c in cards]}
    (ROOT / args.report).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"-> {args.dst}: {len(cards)} 张原子件卡 / {len(kinds)} 种 / 落在 {n_shots} 个镜头上")
    print("   种类:", ", ".join(kinds))
    if problems:
        print(f"\n⚠ {len(problems)} 处冲突：")
        for p in problems:
            print("   -", p)
    else:
        print("   落位体检：0 冲突 ✓")


if __name__ == "__main__":
    main()
