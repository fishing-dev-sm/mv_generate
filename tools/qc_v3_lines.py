#!/usr/bin/env python3
"""v3 字幕行表体检（不渲染，纯读表）。

三条硬规则（§9.4-B）：
  ① 入场不提前：装置入场 gate 必须落在拍上、且在行首发声之前
  ② 落位在留白区：行的 zone 应当在该镜 free 排名里（否则压在人/亮部上）
  ③ 不留死板：行内容唱完后到被下一行切走之间的空转（hold tail）不该太长

用法：venv/bin/python tools/qc_v3_lines.py [--shots shots-full-v3.json]
"""

from __future__ import annotations

import argparse
import bisect
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", default="shots-full-v3.json")
    args = ap.parse_args()
    cfg = json.loads((ROOT / args.shots).read_text(encoding="utf-8"))
    beat = json.loads((ROOT / "song/analysis/beatmap.json").read_text(encoding="utf-8"))
    bt = beat["beats"]
    lines = cfg["visual"]["lyrics"]["lines"]
    shots = cfg["shots"]

    def shot_at(t):
        for s in shots:
            if s["t0"] - 1e-6 <= t < s["t1"]:
                return s
        return shots[-1]

    def nearest_beat(t):
        i = bisect.bisect_left(bt, t)
        cand = [bt[j] for j in (i - 1, i, i + 1) if 0 <= j < len(bt)]
        return min(cand, key=lambda x: abs(x - t)) if cand else t

    def chars_of(L):
        if L.get("at"):
            return L["at"]
        cs = [c for c in L["text"].replace(" ", "")]
        n = len(cs)
        a, b = L["t0"], L["t1"]
        return [round(a + (b - a) * i / n, 3) for i in range(n)]

    print(f"{'#':>3} {'style':<8} {'zone':<4} {'t0':>7} {'gate':>7} {'Δgate':>6} "
          f"{'入拍':>6} {'hold':>5}  {'zone∈free':<10} flags")
    issues = []
    starts = [chars_of(L)[0] for L in lines]
    for i, L in enumerate(lines):
        cs = chars_of(L)
        t0 = cs[0]
        nxt = starts[i + 1] if i + 1 < len(lines) else None
        # 真离场时刻：显式 cutAt 优先，否则 = 下一行首字的那一刻（硬切）
        exit_t = L["cutAt"] if L.get("cutAt") is not None else nxt
        last_e = cs[-1] + 0.25
        hold = (exit_t - last_e) if exit_t is not None else 0.0
        gate = L.get("gate", t0)
        s = shot_at(t0)
        free = s.get("free", [])
        zin = L["zone"] in free or L["zone"] == "MC"
        nb = nearest_beat(t0)
        beat_off = t0 - nb
        flags = []
        if gate > t0 + 1e-6:
            flags.append("gate晚于发声")
        if abs(gate - nearest_beat(gate)) > 0.02:
            flags.append("gate离拍")
        if not zin:
            flags.append(f"压内容({s['id']})")
        if hold > 1.2:
            flags.append(f"空转{hold:.1f}s")
        if flags:
            issues.append((i, L["style"], flags))
        print(f"{i:>3} {L['style']:<8} {L['zone']:<4} {t0:>7.2f} {gate:>7.3f} "
              f"{gate - nearest_beat(gate):>6.3f} {beat_off:>6.2f} {hold:>5.2f}  "
              f"{'✓' if zin else '✗':<10} {' '.join(flags)}")

    # 逐字时间与拍网格的贴合度（这是「卡点」的量化口径）
    all_cs = [t for L in lines for t in chars_of(L)]
    near = sum(1 for t in all_cs if abs(t - nearest_beat(t)) <= 0.06)
    print(f"\n逐字共 {len(all_cs)} 个；落在拍 ±60ms 内 {near} 个 "
          f"({100.0 * near / len(all_cs):.1f}%)")
    print(f"有标记的行 {len(issues)}/{len(lines)}")

    # ---------------- 意义层原子件体检 ----------------
    ZONE_RECT = {"TL": (120, 196, 810, 210), "TC": (555, 186, 810, 210), "TR": (990, 196, 810, 210),
                 "ML": (120, 420, 810, 210), "MC": (555, 410, 810, 220), "MR": (990, 420, 810, 210),
                 "LL": (120, 546, 820, 200), "LR": (980, 546, 820, 200), "WIDE": (150, 292, 1620, 180)}

    def rect(t):
        return (t["x"], t["y"], t["w"], t["h"])

    def hit(a, b, pad=0):
        ax, ay, aw, ah = a
        bx, by, bw, bh = b
        return not (ax + aw + pad <= bx or bx + bw + pad <= ax
                    or ay + ah + pad <= by or by + bh + pad <= ay)

    cards = []
    for s in shots:
        for c in s.get("cards", []):
            cards.append((s["id"], c))
    print(f"\n[意义层] 共 {len(cards)} 张原子件，分布在 "
          f"{len({sid for sid, _ in cards})} 个镜")
    card_bad = 0
    for sid, c in cards:
        r = rect(c)
        flags = []
        if r[0] < 56 or r[1] < 130 or r[0] + r[2] > 1864 or r[1] + r[3] > 792:
            flags.append("出安全区")
        # 与「生命周期内任何一行字幕的落位区」相交都不行
        for i, L2 in enumerate(lines):
            cs2 = chars_of(L2)
            a2 = cs2[0]
            nxt = chars_of(lines[i + 1])[0] if i + 1 < len(lines) else L2["t1"]
            e2 = L2.get("cutAt", nxt)
            if c["enterAt"] < e2 - 1e-6 and c["exitAt"] > a2 + 1e-6:
                z = ZONE_RECT.get(L2["zone"], ZONE_RECT["ML"])
                if hit(r, z, 10):
                    flags.append(f"压字幕行{i}({L2['zone']})")
        for sid2, c2 in cards:
            if (sid2, id(c2)) >= (sid, id(c)): continue
            if c2.get("_shot") != sid: continue
            if hit(r, rect(c2), 6):
                flags.append(f"压同镜卡片{c2['atom']}")
        if flags:
            card_bad += 1
            print(f"  ✗ {sid} {c['atom']:<10} x={r[0]:<5} y={r[1]:<4} "
                  f"{c['enterAt']:.2f}-{c['exitAt']:.2f}  {' '.join(flags)}")
    # 同镜两卡互压（补一遍：上面那圈要靠 _shot 标记，这里直接两两比）
    by_shot = {}
    for sid, c in cards:
        by_shot.setdefault(sid, []).append(c)
    for sid, arr in by_shot.items():
        for i in range(len(arr)):
            for j in range(i + 1, len(arr)):
                if arr[i]["enterAt"] < arr[j]["exitAt"] and arr[j]["enterAt"] < arr[i]["exitAt"]:
                    if hit(rect(arr[i]), rect(arr[j]), 6):
                        print(f"  ✗ {sid} 同镜互压：{arr[i]['atom']} × {arr[j]['atom']}")
                        card_bad += 1
    print(f"原子件问题 {card_bad} 张 / {len(cards)}")


if __name__ == "__main__":
    main()
