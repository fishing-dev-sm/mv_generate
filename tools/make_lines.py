#!/usr/bin/env python3
"""把「权威歌词」对齐到「逐字时间」，产出字幕引擎要用的行级/字级时间轴。

输入
  lyrics/final.md            —— 权威歌词（人手写的，文本正确，没有时间）
  song/analysis/words.json   —— ASR 逐字时间（时间准，文本有错字）
输出
  song/analysis/lines.json   —— 每行：章节 / 情绪 / 念白标记 / 文本 /
                                行起止 / 逐字时间 / 逐词时间

为什么要做这一步：现有的 words-fixed.json 是**词组级**对齐（140 条），
只够做「一句话淡入」，做不了逐字点亮、逐词重音、按情绪换字体这些设计。
words.json 有 830 条真·逐字时间，但文本是机器转录的（"本地"→"便门"、
"冒泡"→"猫跑"）。所以用 final.md 的正确文本去对 words.json 的时间轴：
正确文本 + 精确时间 = 卡拉 OK 级字幕数据。

对齐是**顺序**的（第 i 行的搜索窗口从第 i-1 行的结束位置开始），
所以不会出现把后面副歌的"示例"错配到前面某行的情况。
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 章节 → 情绪（视觉引擎按 mood 选样式；见 engine/visual.js 的 LYRIC）
MOOD_BY_SECTION = {
    ("Intro", 0): "announce",
    ("Verse", 0): "rant",
    ("Chorus", 0): "hype",
    ("Verse", 1): "rant",
    ("Chorus", 1): "hype",
    ("Verse", 2): "savage",
    ("Bridge", 0): "quiet",
    ("Verse", 3): "praise",
    ("Chorus", 2): "hype",
    ("Outro", 0): "announce",
}


_STRIP = re.compile(r"[\s\u3000·、，。！？；：\"'「」（）()\[\]…—\-—]+")


def display(s: str) -> str:
    """上屏形态：去空格/标点、统一全角，但**保留大小写**（AI / KPI / Qwen 不能被小写）。"""
    return _STRIP.sub("", unicodedata.normalize("NFKC", s))


def normalize(s: str) -> str:
    """对齐形态：在上屏形态基础上去大小写差异。"""
    return display(s).lower()


def parse_lyrics(path: Path):
    """解析 final.md → [(section, ordinal, speech, text), ...]（保持出现顺序）。"""
    out = []
    counts: dict[str, int] = {}
    section = None
    ordinal = 0
    speech = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        m = re.fullmatch(r"\[(\w+)\]", line)
        if m:
            section = m.group(1)
            ordinal = counts.get(section, 0)          # 该章节第几次出现（0 基）
            counts[section] = ordinal + 1
            speech = False
            continue
        if line.startswith("<!--") or line.startswith("#") or line.startswith("- ") or line.startswith("创作说明"):
            continue
        if section is None:
            continue
        if line.startswith("（"):                       # （念白）/（半念半唱）/（轻声）
            speech = True
            rest = line.strip("（）()")
            if not rest or rest.startswith(("群公告朗读", "念白", "半念半唱", "轻声")):
                continue
            line = rest
        out.append((section, ordinal, speech, line))
    return out


def char_stream(words):
    """words.json → 字符流 + 每个字符的 [start, end]，以及字符 → 原 token 索引。"""
    chars, starts, ends, tok = [], [], [], []
    for wi, w in enumerate(words):
        for c in normalize(w["word"]):
            chars.append(c)
            starts.append(float(w["start"]))
            ends.append(float(w["end"]))
            tok.append(wi)
    return chars, starts, ends, tok


def global_align(entries, chars, starts, ends):
    """整首一次性做**单调全局对齐**：歌词字符流 ←→ ASR 字符流。

    逐行贪心搜索会漂移（某一行没匹配好，窗口就跳到后面去了），
    整首对齐则天然单调：difflib 的匹配块按顺序给出，第 i 行的字
    只可能落在第 i 行真实唱的位置附近。

    返回：
      line_times[i] = {行内字符序号: (start, end)}   —— 命中字符的时间
    """
    L, lown, off = [], [], []
    for i, e in enumerate(entries):
        off.append(len(L))
        for c in normalize(e[3]):
            L.append(c)
            lown.append(i)
    L = "".join(L)
    C = "".join(chars)

    line_times = [dict() for _ in entries]
    for a, b, n in difflib.SequenceMatcher(None, L, C, autojunk=False).get_matching_blocks():
        if n == 0:
            continue
        for k in range(n):
            li = lown[a + k]
            line_times[li][(a + k) - off[li]] = (starts[b + k], ends[b + k])
    return line_times


def fill_char_times(want, partial):
    """把一行里没命中的字用相邻命中字线性插值补上，返回 [(t, e), ...]。"""
    times = [None] * len(want)
    for i, v in partial.items():
        if 0 <= i < len(times):
            times[i] = v
    known = [i for i, v in enumerate(times) if v]
    if not known:
        return []
    for i in range(len(times)):
        if times[i] is None:
            prev = max([k for k in known if k < i], default=None)
            nxt = min([k for k in known if k > i], default=None)
            if prev is None:
                times[i] = times[nxt]
            elif nxt is None:
                times[i] = times[prev]
            else:
                p0, p1 = times[prev], times[nxt]
                f = (i - prev) / (nxt - prev)
                times[i] = (p0[0] + (p1[1] - p0[0]) * f * 0.5, p0[1] + (p1[1] - p0[1]) * f)
    return times


def group_words(line_text, times):
    """按空白/标点把整行切成显示用的词组，时间取该组的首尾。"""
    out, i = [], 0
    for part in re.split(r"(\s+|、|，|。|！|？|；|：)", line_text):
        n = len(normalize(part))
        if n == 0:
            continue
        seg = times[i:i + n]
        if seg and all(seg):
            out.append({"w": part, "t": round(seg[0][0], 3), "e": round(seg[-1][1], 3)})
        i += n
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lyrics", default=str(ROOT / "lyrics/final.md"))
    ap.add_argument("--words", default=str(ROOT / "song/analysis/words.json"))
    ap.add_argument("--phrases", default=str(ROOT / "song/analysis/words-fixed.json"))
    ap.add_argument("--out", default=str(ROOT / "song/analysis/lines.json"))
    ap.add_argument("--min-ratio", type=float, default=0.42)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    entries = parse_lyrics(Path(args.lyrics))
    words = json.loads(Path(args.words).read_text(encoding="utf-8"))["words"]
    chars, starts, ends, _ = char_stream(words)
    line_times = global_align(entries, chars, starts, ends)

    lines = []
    for i, (section, ordinal, speech, text) in enumerate(entries):
        want = normalize(text)
        partial = line_times[i]
        ratio = len(partial) / max(1, len(want))
        t = fill_char_times(want, partial) if ratio >= args.min_ratio else []
        if t:
            t0, t1 = t[0][0], t[-1][1]
        else:
            t0 = t1 = None
        if args.debug:
            tt = "—" if not t else f"{t0:6.2f}-{t1:6.2f}"
            print(f"cov={ratio:4.2f} {section}{ordinal+1:<3} {tt:>15}  {text[:30]}")
        lines.append({
            "section": section, "ordinal": ordinal, "speech": speech,
            "mood": MOOD_BY_SECTION.get((section, ordinal), "rant"),
            "text": text, "t0": t0, "t1": t1,
            "ratio": round(ratio, 3),
            "chars": [{"c": c, "t": round(a, 3), "e": round(b, 3)}
                      for c, (a, b) in zip(display(text), t)] if t else [],
            "words": group_words(text, t) if t else [],
        })

    # 没对齐上的行：夹在前一行结束和下一行开始之间（宁可均分，也不要错位）
    for k, ln in enumerate(lines):
        if ln["t0"] is not None:
            continue
        prev = next((lines[q]["t1"] for q in range(k - 1, -1, -1) if lines[q]["t1"]), 0.0)
        nxt = next((lines[q]["t0"] for q in range(k + 1, len(lines)) if lines[q]["t0"]), None)
        if nxt is None:
            ln["t0"], ln["t1"] = prev, prev + 2.0
        else:
            ln["t0"], ln["t1"] = prev, nxt
        ln["interpolated"] = True

    # 章节时间范围
    sections = []
    for ln in lines:
        if sections and sections[-1]["name"] == ln["section"] and sections[-1]["ordinal"] == ln["ordinal"]:
            sections[-1]["t1"] = max(sections[-1]["t1"], ln["t1"])
            sections[-1]["lines"] += 1
        else:
            sections.append({"name": ln["section"], "ordinal": ln["ordinal"], "mood": ln["mood"],
                             "t0": ln["t0"], "t1": ln["t1"], "lines": 1,
                             "speech": bool(ln["speech"])})

    payload = {
        "_meta": {
            "source_lyrics": str(Path(args.lyrics).name),
            "source_timing": str(Path(args.words).name),
            "lines": len(lines),
            "aligned": sum(1 for l in lines if not l.get("interpolated")),
            "interpolated": sum(1 for l in lines if l.get("interpolated")),
            "mean_ratio": round(sum(l["ratio"] for l in lines) / max(1, len(lines)), 3),
        },
        "sections": sections,
        "lines": lines,
    }
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    m = payload["_meta"]
    print(f"lines={m['lines']} aligned={m['aligned']} interpolated={m['interpolated']} "
          f"mean_ratio={m['mean_ratio']} -> {args.out}")
    for s in sections:
        print(f"  {s['name']}{s['ordinal']+1:<2} {s['mood']:<8} {s['t0']:7.2f}-{s['t1']:7.2f}  {s['lines']} 行")
    weak = [l for l in lines if l["ratio"] < 0.7 and not l.get("interpolated")]
    if weak:
        print("低置信行（人工复核用）:")
        for l in weak[:12]:
            print(f"  {l['ratio']:.2f}  {l['t0']:.2f}  {l['text'][:34]}")


if __name__ == "__main__":
    main()
