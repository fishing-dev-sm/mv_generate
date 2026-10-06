#!/usr/bin/env python3
"""把 64 行歌词编成视觉层的**行表**（每行一个装置 + 一个落位区）。

这张表是**编辑判断**，不是推导出来的——脚本只负责把判断和三份实测数据粘起来：
  song/analysis/lines.json    逐字发声时刻（at[] 从这里抄，不做任何插值）
  song/analysis/beatmap.json  拍网格（每行的入场 gate 落在拍上）
  out/freearea.json           逐镜留白区排名（zone 选空的地方）+ 底片亮度（决定字色）

产物：shots-full-v3.json —— shots-full.json + visual 配置 + 逐镜元数据。
用法：python3 tools/plan_lyrics.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

TITLE = "示例项目 A"

# ---------------------------------------------------------------------------
# 行表：index → (style, zone, extras)
#   style  装置（visual.js 的 LY3 键）
#   zone   落位区（见 visual.js ZONES）
#   extras marks 强调词 / hit 重击词 / strikeAt 划改词 / value+unit+label 读数 /
#          rows 显式分行 / note 注脚 / echoAt 回声词 / names 名单
#   cutAt  显式离场点（必须落在拍上）：唱完之后**主动退场**。默认离场 = 下一行首字那一刻；
#          两行间隔 >1.2s 时，那块装置会静静杵在画面上不动 —— 那就成了导演最烦的「静止视觉层」，
#          所以这类行一律给一个拍点退场，让画面回到只剩 chrome 在动。
# ---------------------------------------------------------------------------
PLAN = {
    0:  ("tape",   "TR", {"rows": ["示例", "示例"], "note": "示例",
                          "cutAt": 6.92}),      # 末字 6.02 唱完 → 下一个 downbeat 退场（否则静杵 2.1s）
    1:  ("caller", "LL", {"rows": ["示例", "示例"],
                          "cutAt": 12.864}),    # 末字 12.04 → 12.864 退场（否则静杵 2.8s）
    2:  ("cue",    "TR", {"marks": ["示例"]}),
    3:  ("ledger", "MR", {"value": "示例", "unit": "元", "label": "示例",
                          "valueAt": 22.361}),   # 账单合计落在 downbeat 22.361（此行 23.44 就被下一行切走，

    4:  ("cue",    "ML", {"marks": ["示例"]}),
    5:  ("cue",    "TR", {"marks": ["示例"]}),
    6:  ("cue",    "TR", {"marks": ["示例"]}),
    7:  ("strike", "LR", {"strikeAt": "示例"}),
    8:  ("punch",  "TL", {"hit": "示例", "cutAt": 40.333}),
    9:  ("measure", "LR", {"value": "示例", "unit": "%", "label": "示例",
                          "cutAt": 44.629}),    # 读数 43.6 落下，保住 1.0s 可见再退场
    10: ("hook",   "TR", {}),
    11: ("cue",    "ML", {"marks": ["示例"],



                          "at": [round(46.70 + i * 0.0996, 3) for i in range(10)]}),
    12: ("strike", "TR", {"strikeAt": "示例"}),
    13: ("punch",  "LR", {"hit": "示例"}),
    14: ("hook",   "TL", {}),
    15: ("placard", "LL", {"marks": ["示例"]}),
    16: ("punch",  "MR", {"hit": "示例"}),
    17: ("placard", "ML", {"marks": ["示例"]}),
    18: ("cue",    "LL", {"marks": ["示例"]}),
    19: ("stack",  "MC", {"rows": ["示例", "示例", "示例"]}),
    20: ("cue",    "TR", {"marks": ["示例"]}),
    21: ("versus", "TL", {"left": "示例", "right": "示例", "tail": "示例"}),
    22: ("cue",    "MR", {"marks": ["示例"]}),
    23: ("tape",   "ML", {"rows": ["示例", "示例"], "note": "示例"}),
    24: ("strike", "LR", {"strikeAt": "示例"}),
    25: ("cue",    "TL", {"marks": ["示例"]}),
    26: ("hook",   "TR", {}),
    27: ("cue",    "ML", {"marks": ["示例"]}),
    28: ("strike", "TR", {"strikeAt": "示例"}),
    29: ("punch",  "LR", {"hit": "示例"}),
    30: ("hook",   "TL", {}),
    31: ("placard", "LL", {"marks": ["示例"]}),
    32: ("punch",  "MR", {"hit": "示例"}),
    33: ("placard", "ML", {"marks": ["示例"]}),
    34: ("savage", "TL", {"hits": ["示例", "示例"]}),
    35: ("cue",    "MR", {"marks": ["示例"], "cutAt": 109.343}),
    36: ("cue",    "MR", {"marks": ["示例"]}),
    37: ("cue",    "TR", {"marks": ["示例"]}),
    38: ("tape",   "ML", {"rows": ["示例", "示例"], "note": "示例"}),
    39: ("punch",  "LL", {"hit": "示例"}),
    40: ("cue",    "MC", {"marks": ["示例"]}),
    41: ("placard", "TR", {"marks": ["示例"]}),
    42: ("whisper", "LL", {}),
    43: ("whisper", "TR", {}),
    44: ("echo",   "TR", {"echoAt": "示例"}),
    45: ("placard", "MR", {"marks": ["示例"]}),
    46: ("cue",    "TL", {"marks": ["示例"]}),
    47: ("measure", "MR", {"value": "示例", "unit": "", "label": "示例"}),
    48: ("roster", "MC", {"names": ["示例", "示例", "示例"], "cutAt": 153.461}),
    49: ("caller", "TL", {"rows": ["示例", "示例"], "lamp": True, "amber": True}),
    50: ("measure", "MR", {"value": "示例", "unit": "", "label": "示例"}),
    51: ("strike", "LL", {"strikeAt": "示例", "cutAt": 162.911}),
    52: ("placard", "TR", {"marks": ["示例"]}),
    53: ("caller", "LL", {"rows": ["示例", "示例"]}),
    54: ("hook",   "TR", {}),
    55: ("cue",    "ML", {"marks": ["示例"]}),
    56: ("strike", "TR", {"strikeAt": "示例"}),
    57: ("punch",  "LR", {"hit": "示例"}),
    58: ("hook",   "TL", {}),
    59: ("placard", "LL", {"marks": ["示例"]}),
    60: ("punch",  "MR", {"hit": "示例"}),
    61: ("placard", "ML", {"marks": ["示例"]}),
    62: ("tally",  "TR", {"lead": "示例", "value": 99, "plus": True, "plusAt": 189.2}),
    63: ("caller", "TR", {"rows": ["示例", "示例"], "cutAt": 194.63}),
}

# 副歌「示例」的计数牌 Steps：按真实拍点跳（拍点抄自 beatmap），不是匀速动画
TALLY_STEPS = {
    62: [(186.921, 14), (187.339, 28), (187.780, 42), (188.198, 57),
         (188.616, 71), (189.057, 85), (189.200, 99)],
}

# ---------------------------------------------------------------------------
# 意义层原子件（Figma 4:2–5:364 的 21 件 + 旧 board 的 stat）：
#   每一件都是「解释这句梗」的图形。导演 2026-10-02 的批注是「用得太单一」——
#   之前整份行表把 cards 全剥了，画面上只剩 chrome + 字幕，所以这一版把原子件排回来。
#
# 两条纪律（写进表里就不靠自觉）：
#   ① **数字必须真实**：不出现本片查不到的数。（账单 0.033/点 × 590 点 = 19.47 元、
#      折算 77.9 元/分；废片率 60%；BPM 143.55；拍长 418ms；时长 200.3s；55 镜；66 行。）
#      凡是"示意性对比"一律不用 chart/gauge 这类带数字的件，改用 microtags / leader。
#   ② **不许压在人脸上**：每张卡的 slot 必须和该行字幕的 zone 不相交（qc_v3_lines.py 会验），
#      并且优先挑该镜留白排名里空的那一侧。
#
# 槽位（x, y, w, h）：避开 chrome —— 左侧标尺 x<60、顶栏 y<130、底部翻牌条 y>790、ticker y>1000。
# ---------------------------------------------------------------------------
CARD_SLOTS = {
    "LT":  (64, 148, 600, 300),      # 左上（字幕在右时才可用）
    "CT":  (660, 148, 600, 300),
    "RT":  (1256, 148, 600, 340),    # 右上
    "ML":  (64, 420, 600, 250),
    "MR":  (1256, 420, 600, 250),
    "LB":  (64, 470, 620, 310),      # 左下
    "RB":  (1236, 470, 620, 310),
    "LTt": (64, 140, 500, 500),      # 左侧高卡（收据/终端/标本/扫描仪）
    "RTt": (1360, 140, 496, 500),
    "wide": (560, 645, 800, 147),    # 片尾翻牌板
}

# out_lines 下标 → [card]。下标 0 = 片头题名，1..64 = 歌词行，65 = 片尾落版。
# snap=True 表示入场直接跟着该行的 gate，否则晚 0.35s 之后的第一个拍（先字幕、后卡片）。
CARDS = {
    0:  [{"atom": "microtags", "slot": "RT", "w": 420, "h": 120, "snap": True,
          "items": [{"t": "示例"}, {"t": "示例"},
                    {"t": "示例"}, {"t": "示例"}]}],
    1:  [{"atom": "toast", "slot": "LB",
          "head": "示例", "time": "示例", "title": "示例",
          "body": "示例",
          "rows": ["示例", "示例", "示例"]}],
    2:  [{"atom": "checklist", "slot": "RT",
          "title": "示例", "meta": "示例",
          "rows": [{"k": "示例"}, {"k": "示例"}, {"k": "示例"},
                   {"k": "示例", "v": "示例", "acc": True}],
          "note": "示例"}],
    3:  [{"atom": "chart", "slot": "LTt",
          "title": "示例", "meta": "示例", "base": "示例",
          "values": [78, 0], "max": 100, "axis": ["示例", "示例"],
          "note": "示例", "value": "示例"}],
    5:  [{"atom": "toggles", "slot": "RT",
          "title": "示例",
          "rows": [{"k": "示例", "v": "示例"}, {"k": "示例", "v": "示例"},
                   {"k": "示例", "v": "示例"}],
          "notes": ["示例", "示例"]}],
    6:  [{"atom": "terminal", "slot": "LTt",
          "title": "示例", "path": "示例", "model": "示例",
          "lines": [{"t": "示例", "kind": "add"},
                    {"t": "示例", "kind": "add"},
                    {"t": "示例", "kind": "del"},
                    {"t": "示例", "kind": "add"}],
          "hint": "示例"}],
    8:  [{"atom": "checklist", "slot": "RT",
          "title": "示例", "meta": "示例",
          "rows": [{"k": "示例"}, {"k": "示例"}, {"k": "示例"},
                   {"k": "示例", "v": "示例"}],
          "note": "示例"}],
    9:  [{"atom": "ladder", "slot": "RTt",
          "title": "示例", "tag": "示例",
          "rows": ["示例", "示例", "示例", "示例"], "dv": "示例",
          "note": "示例"}],
    10: [{"atom": "donut", "slot": "LT", "w": 620, "h": 300, "value": 0.6,
          "legend": [{"k": "示例", "v": "示例", "p": 0.6}, {"k": "示例", "v": "示例", "p": 0.4}]}],
    11: [{"atom": "microtags", "slot": "LT", "w": 400, "h": 120,
          "items": [{"t": "示例"}, {"t": "示例"},
                    {"t": "示例", "acc": True}, {"t": "示例"}]}],
    13: [{"atom": "specimen", "slot": "LTt", "w": 500, "h": 460,
          "title": "示例", "tag": "示例", "big": "示例", "from": "示例",
          "value": "示例",
          "rows": [{"k": "示例", "v": "示例"}, {"k": "示例", "v": "示例"}]}],
    14: [{"atom": "chart", "slot": "LT",
          "title": "示例", "meta": "示例", "base": "示例",
          "values": [100, 0], "max": 100, "axis": ["示例", "示例"],
          "note": "示例", "value": "示例"}],
    16: [{"atom": "specimen", "slot": "RTt", "w": 496, "h": 460,
          "title": "示例", "tag": "示例", "big": "示例", "from": "示例",
          "value": "示例",
          "rows": [{"k": "示例", "v": "示例"}, {"k": "示例", "v": "示例"}]}],
    18: [{"atom": "carelabel", "slot": "RT", "w": 600, "h": 340,
          "title": "示例", "code": "示例",
          "rows": [{"k": "示例", "v": "示例", "pct": "¥"}, {"k": "示例", "v": "示例", "pct": "—"},
                   {"k": "示例", "v": "示例", "pct": "%"}],
          "note": "示例"}],
    19: [{"atom": "struct", "slot": "RT", "w": 600, "h": 340,
          "title": "示例", "tag": "示例",
          "layers": [{"k": "示例", "v": "示例"}, {"k": "示例", "v": "示例"},
                     {"k": "示例", "v": "示例"}],
          "note": "示例"}],
    20: [{"atom": "scanner", "slot": "LTt", "w": 470,
          "title": "示例", "meta": "示例", "sub": "示例",
          "total": 24, "status": "示例", "plat": "示例"}],
    21: [{"atom": "terminal", "slot": "LTt",
          "title": "示例", "path": "示例", "model": "示例",
          "lines": [{"t": "示例", "kind": "add"},
                    {"t": "示例", "kind": "add"},
                    {"t": "示例", "kind": "del"},
                    {"t": "示例", "kind": "add"}],
          "hint": "示例"}],
    22: [{"atom": "microtags", "slot": "RT", "w": 420, "h": 120,
          "items": [{"t": "示例"}, {"t": "示例"},
                    {"t": "示例", "acc": True}, {"t": "示例"}]}],
    23: [{"atom": "specimen", "slot": "LTt", "w": 500, "h": 460,
          "title": "示例", "tag": "示例", "big": "示例", "from": "示例",
          "value": "示例",
          "rows": [{"k": "示例", "v": "示例"}, {"k": "示例", "v": "示例"}]}],
    24: [{"atom": "strike", "slot": "RT", "w": 600, "h": 240,
          "parts": [{"t": "示例", "old": True}, {"t": "示例", "old": False}],
          "note": "示例"}],
    25: [{"atom": "checklist", "slot": "LT",
          "title": "示例", "meta": "示例",
          "rows": [{"k": "示例"}, {"k": "示例"}, {"k": "示例"},
                   {"k": "示例", "v": "示例"}],
          "note": "示例"}],
    26: [{"atom": "specimen", "slot": "RTt", "w": 496, "h": 460,
          "title": "示例", "tag": "示例", "big": "示例", "from": "示例",
          "value": "示例",
          "rows": [{"k": "示例", "v": "示例"}, {"k": "示例", "v": "示例"}]}],
    35: [{"atom": "toast", "slot": "RT", "w": 600, "h": 310,
          "head": "示例", "time": "示例", "title": "示例",
          "body": "示例",
          "rows": ["示例", "示例", "示例"]}],
    36: [{"atom": "terminal", "slot": "LTt",
          "title": "示例", "path": "示例", "model": "示例",
          "lines": [{"t": "示例", "kind": "add"},
                    {"t": "示例", "kind": "add"},
                    {"t": "示例", "kind": "add"}],
          "hint": "示例"}],
    37: [{"atom": "struct", "slot": "LT",
          "title": "示例", "tag": "示例",
          "layers": [{"k": "示例", "v": "示例"},
                     {"k": "示例", "v": "示例"},
                     {"k": "示例", "v": "示例"}],
          "note": "示例"}],
    38: [{"atom": "receipt", "slot": "LTt",
          "head": "示例", "no": "示例", "sub": "示例",
          "big": "示例",
          "rows": [{"k": "示例", "v": "示例"}, {"k": "示例", "v": "示例"},
                   {"k": "示例", "v": "示例", "old": True}],
          "foot": "示例", "stamp": "示例"}],
    39: [{"atom": "checklist", "slot": "RT",
          "title": "示例", "meta": "示例",
          "rows": [{"k": "示例"}, {"k": "示例"}, {"k": "示例"},
                   {"k": "示例", "v": "示例"}],
          "note": "示例"}],
    40: [{"atom": "struct", "slot": "RTt",
          "title": "示例", "tag": "示例",
          "layers": [{"k": "示例", "v": "示例"}, {"k": "示例", "v": "示例"},
                     {"k": "示例", "v": "示例"}],
          "note": "示例"}],
    41: [{"atom": "microtags", "slot": "LT", "w": 420, "h": 120,
          "items": [{"t": "示例"}, {"t": "示例"},
                    {"t": "示例", "acc": True}, {"t": "示例"}]}],
    42: [{"atom": "fontmode", "slot": "LT", "w": 620, "h": 300,
          "masthead": "示例", "subtitle": "示例",
          "caller1": "示例", "caller2": "示例"}],
    43: [{"atom": "microtags", "slot": "RT", "w": 420, "h": 120,
          "items": [{"t": "示例"}, {"t": "示例"}, {"t": "示例"}]}],
    44: [{"atom": "donut", "slot": "LT", "w": 620, "h": 300, "value": 1,
          "legend": [{"k": "示例", "v": "示例", "p": 0}, {"k": "示例", "v": "示例", "p": 1}]}],
    45: [{"atom": "strike", "slot": "LT", "w": 620, "h": 240,
          "parts": [{"t": "示例", "old": True}, {"t": "示例", "old": False}],
          "note": "示例"}],
    46: [{"atom": "ladder", "slot": "LT", "w": 620, "h": 400,
          "title": "示例", "tag": "示例",
          "rows": ["示例", "示例", "示例", "示例", "示例"],
          "dv": "示例", "note": "示例"}],
    47: [{"atom": "checklist", "slot": "RT",
          "title": "示例", "meta": "示例",
          "rows": [{"k": "示例", "v": "示例"}, {"k": "示例", "v": "示例"},
                   {"k": "示例", "v": "示例"}],
          "note": "示例"}],
    48: [{"atom": "ladder", "slot": "LT", "w": 620, "h": 400,
          "title": "示例", "tag": "示例",
          "rows": ["示例", "示例", "示例", "示例"], "dv": "示例",
          "note": "示例"}],
    49: [{"atom": "microtags", "slot": "LT", "w": 420, "h": 120,
          "items": [{"t": "示例"}, {"t": "示例"},
                    {"t": "示例", "acc": True}, {"t": "示例"}]}],
    50: [{"atom": "leader", "slot": "RT", "w": 600, "h": 340,
          "items": [{"px": -180, "py": 300, "t": "示例"},
                    {"px": -120, "py": 150, "t": "示例"}], "dash": False}],
    51: [{"atom": "carelabel", "slot": "LT", "w": 620, "h": 340,
          "title": "示例", "code": "示例",
          "rows": [{"k": "示例", "v": "示例", "pct": ""}, {"k": "示例", "v": "示例", "pct": ""},
                   {"k": "示例", "v": "示例", "pct": "OK"}],
          "note": "示例"}],
    52: [{"atom": "strike", "slot": "RT", "w": 600, "h": 240,
          "parts": [{"t": "示例", "old": True}, {"t": "示例", "old": False}],
          "note": "示例"}],
    53: [{"atom": "fontmode", "slot": "LT", "w": 620, "h": 300,
          "masthead": "示例", "subtitle": "示例",
          "caller1": "示例", "caller2": "示例"}],
    54: [{"atom": "leader", "slot": "RT", "w": 600, "h": 420,
          "items": [{"px": -220, "py": 320, "t": "示例"},
                    {"px": -160, "py": 180, "t": "示例"}], "dash": True}],
    55: [{"atom": "microtags", "slot": "LT", "w": 420, "h": 120,
          "items": [{"t": "示例"}, {"t": "示例", "acc": True}]}],
    63: [{"atom": "toast", "slot": "LB", "w": 620, "h": 310,
          "head": "示例", "time": "示例", "title": "示例",
          "body": "示例",
          "rows": ["示例", "示例", "示例"]}],
    64: [{"atom": "mix", "slot": "LT", "w": 640, "h": 400,
          "title": "示例", "tag": "示例",
          "marks": ["示例", "示例"], "call": "示例",
          "taps": ["示例", "示例", "示例", "示例"],
          "note": "示例"}],
    65: [{"atom": "flapboard", "slot": "wide", "w": 800, "h": 140,
          "text": "示例", "accent": [3, 4],
          "note": "示例", "line": "示例"}],
}


def main():
    cfg = json.loads((ROOT / "shots-full.json").read_text(encoding="utf-8"))
    lines = json.loads((ROOT / "song/analysis/lines.json").read_text(encoding="utf-8"))
    beats = json.loads((ROOT / "song/analysis/beatmap.json").read_text(encoding="utf-8"))
    fa = json.loads((ROOT / "out/freearea.json").read_text(encoding="utf-8"))
    bt = beats["beats"]

    def gate_of(t0):
        """入场 gate：行首发声前 0.22s 之后的第一个拍（永不提前，且落在拍上）。"""
        want = t0 - 0.22
        for b in bt:
            if b >= want:
                return round(b, 3)
        return round(t0, 3)

    out_lines = []
    # 片头题名（0–2s 无人声）与片尾落版（193.1–200.3 无人声）也算「行」，
    # 它们走同样的行机制，于是同样受「入场落拍、离场硬切」的纪律约束。
    out_lines.append({
        "text": TITLE, "style": "title", "zone": "MC",
        "at": [0.42] * len(TITLE), "t0": 0.42, "t1": 1.86, "cutAt": gate_of(1.98),
        "kicker": "ESCAPE VELOCITY · MOTION LAYERS",
    })
    for i, L in enumerate(lines["lines"]):
        st, zone, ex = PLAN[i]
        rec = {"text": L["text"], "style": st, "zone": zone,
               "at": [round(c["t"], 3) for c in L["chars"]],
               "t0": L["t0"], "t1": L["t1"],
               "gate": gate_of(L["t0"]), "section": L["section"], "mood": L["mood"]}
        rec.update(ex)
        if i in TALLY_STEPS:
            rec["steps"] = [{"t": t, "v": v} for t, v in TALLY_STEPS[i]]
        out_lines.append(rec)
    # 片尾落版：入场钉在 downbeat 195.512（原来 195.6 离拍 88ms），并且**一直站到片尾**——
    # 落版的默认离场 = 末字 e + hold 1.0s = 196.85，那样最后 3.4 秒画面没有题名，像被剪掉了。
    out_lines.append({
        "text": TITLE, "style": "endcard", "zone": "MC",
        "at": [195.512] * len(TITLE), "t0": 195.512, "t1": round(cfg["t1"], 1),
        "gate": 195.512, "cutAt": round(cfg["t1"], 1),
    })

    # 逐镜元数据：亮度（决定字色）、章节名、镜号（chrome 报真号）
    sec = lines["sections"]
    shots = []
    for i, s in enumerate(cfg["shots"]):
        o = dict(s)
        o.pop("coverline", None)          # 封面行整体停用：改用 v3 装置
        o.pop("accent", None)
        o.pop("card", None)
        o.pop("dataCard", None)
        if o.get("type") == "plate":      # 底片模式下不再有占位板：底片本身就是权威画面
            o.pop("plate", None)
            o["type"] = "video"
        for k in ("frames", "frameOffset", "timemap"):
            o.pop(k, None)                # 帧由 out/base-frames2 按全片时间统一供，逐镜不再自带帧
        if o.get("captionMode") in ("coverline", "masthead", "caller", "mass"):
            o["captionMode"] = "subtitle"  # 一律走歌词层
        fs_ = fa["shots"].get(s["id"])
        if fs_:
            lum = sum(sum(r) for r in fs_["lum"]) / (len(fs_["lum"]) * len(fs_["lum"][0]))
            o["lum"] = round(lum, 3)
            o["free"] = fs_["rank"][:4]
        mid = (s["t0"] + s["t1"]) / 2
        if mid < sec[0]["t0"]:
            o["section"] = sec[0]["name"]
        elif mid > sec[-1]["t1"]:
            o["section"] = sec[-1]["name"]
        else:
            o["section"] = next((x["name"] for x in sec if mid <= x["t1"] + 0.6), sec[-1]["name"])
        o["lookNo"] = i + 1
        shots.append(o)

    # ---- 意义层：把原子件挂到「包含这张卡入场拍」的那一镜上 -------------------
    def beat_at_or_after(t):
        for b in bt:
            if b >= t - 1e-6:
                return round(b, 3)
        return round(t, 3)

    def line_first(i):
        L = out_lines[i]
        return L["at"][0] if L.get("at") else L["t0"]

    def line_exit(i):
        L = out_lines[i]
        if L.get("cutAt") is not None:
            return L["cutAt"]
        if i + 1 < len(out_lines):
            return line_first(i + 1)
        return round(cfg["t1"], 3)

    def shot_index_at(t):
        for k, s in enumerate(shots):
            if s["t0"] - 1e-6 <= t < s["t1"]:
                return k
        return len(shots) - 1

    ncards, skipped = 0, []
    for li, specs in sorted(CARDS.items()):
        L0 = out_lines[li]
        first = line_first(li)
        gate = L0.get("gate", first)
        out_t = line_exit(li)
        for spec in specs:
            sx, sy, sw, sh = CARD_SLOTS[spec["slot"]]
            w = int(spec.get("w", sw))
            h = int(spec.get("h", sh))
            enter = gate if spec.get("snap") else beat_at_or_after(first + 0.35)
            exit_t = float(spec.get("until", out_t))
            if sx + w > 1900 or sy + h > 792:        # 不许出画 / 压到底部翻牌条
                skipped.append((li, spec["atom"], "槽位越界"))
                continue
            if exit_t - enter < 0.5:                  # 太短就不挂（宁可少一件，不挂闪现的）
                skipped.append((li, spec["atom"], f"可见 {exit_t - enter:.2f}s"))
                continue
            card = {k: v for k, v in spec.items() if k not in ("slot", "snap", "until")}
            card.update({"x": sx, "y": sy, "w": w, "h": h,
                         "enterAt": round(enter, 3), "exitAt": round(exit_t, 3)})
            shots[shot_index_at(enter)].setdefault("cards", []).append(card)
            ncards += 1

    nchars = sum(len(l["text"].replace(" ", "")) for l in lines["lines"])
    total = round(cfg["t1"], 1)
    cfg["shots"] = shots
    cfg["bg"] = "base"
    cfg["base"] = "out/base-frames2"
    cfg.pop("accent", None)
    cfg.pop("textHalftone", None)
    cfg["visual"] = {
        "title": TITLE,
        "look": {"total": len(shots), "template": "镜次 {n} / {t}"},
        "countdown": {"mode": "seconds", "songEnd": total, "line1": "TO END", "line2": "示例项目 A",
                      "note": "SEC · REMAIN"},
        "flap": {"mode": "bars", "unit": "BAR", "live": True},
        "ruler": {"mode": "timeline", "t0": 0, "t1": total},
        "downbeatEvery": 4,
        "ticker": [
            f"{beats['bpm_from_beats']:.1f} BPM",
            f"拍长 {round(1000 * (bt[-2] - bt[-3]))} MS",
            f"时长 {total} S",
            f"{len(shots)} 镜",
            f"逐字 {nchars} 字",
            "24 FPS · 1920×1080",
            # 跑马灯是给观众看的技术长条，不是工作日志：**不出现工程内部文件名 / 稿号**。
            "ESCAPE VELOCITY · MOTION LAYERS",
        ],
        "lyrics": {"lines": out_lines},
    }
    (ROOT / "shots-full-v3.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"-> shots-full-v3.json  {len(shots)} 镜 / {len(out_lines)} 行 / 逐字 {nchars}")
    print("   styles:", ", ".join(sorted({r['style'] for r in out_lines})))
    print(f"   意义层原子件 {ncards} 张，分布在 "
          f"{len([s for s in shots if s.get('cards')])} 个镜")
    if skipped:
        print(f"   ⚠ 跳过 {len(skipped)}: {skipped}")


if __name__ == "__main__":
    main()
