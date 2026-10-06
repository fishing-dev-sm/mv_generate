#!/usr/bin/env python3
"""歌词回填 v2：把 whisper 听写文本替换为定稿歌词原文，保留 whisper 的时间边界。

匹配原理：STT 段经常把相邻两行歌词听成一个段，所以按"行→段归属"做：
对每行歌词，从当前段指针起向后看至多 3 段，用 SequenceMatcher 的匹配块
计算"行文本在段文本中的有序覆盖率"，≥0.6 即归属。一个段可收纳多行
（按各行归一化长度比例切分该段的时间窗），一行也可以跨过段边界
（取覆盖最好的段）。覆盖率不足的段视为间奏/念白无词。

输出 words-fixed.json 与 words.json 同构（segments + words），
words 含逐词（词边界为行内比例分配）时间；_meta 记录未覆盖行供人工复查。

用法: fix_lyrics.py <words.json> <歌词.md> <输出.json>
"""
import json
import re
import sys
from difflib import SequenceMatcher


def norm(s: str) -> str:
    return "".join(re.findall(r"[一-鿿a-z0-9]", s.lower()))


def lyric_lines(path: str):
    lines = []
    for raw in open(path, encoding="utf-8"):
        s = raw.strip()
        if not s or s.startswith("#") or s.startswith("[") or s.startswith("<!--") \
           or s.startswith("-") or s.startswith("创作说明") \
           or s.startswith("（") or s.startswith("("):
            continue
        lines.append(s)
    return lines


def coverage(a: str, b: str) -> float:
    """a 的字符在 b 中有序命中的比例（0..1）"""
    if not a:
        return 0.0
    m = SequenceMatcher(None, a, b)
    hit = sum(bl.size for bl in m.get_matching_blocks())
    return hit / len(a)


def main():
    words_path, lyric_path, out_path = sys.argv[1:4]
    data = json.load(open(words_path, encoding="utf-8"))
    segs = data["segments"]
    lyrics = [(norm(l), l) for l in lyric_lines(lyric_path)]

    # 1) DP 全局对齐：行 i -> 段 j 的奖励 = 覆盖率；行可跳过(惩罚-0.2)，段可跳过(0)
    nL, nS = len(lyrics), len(segs)
    cov = [[coverage(lyrics[i][0], norm(segs[j].get("text", "")))
            for j in range(nS)] for i in range(nL)]
    NEG = -10.0
    dp = [[NEG] * (nS + 1) for _ in range(nL + 1)]
    back = [[None] * (nS + 1) for _ in range(nL + 1)]
    dp[0][0] = 0.0
    for i in range(nL + 1):
        for j in range(nS + 1):
            cur = dp[i][j]
            if cur <= NEG / 2:
                continue
            if i < nL and j < nS:                       # 行 i 匹配段 j
                v = cur + cov[i][j]
                if v > dp[i + 1][j + 1]:
                    dp[i + 1][j + 1] = v
                    back[i + 1][j + 1] = ("match", i, j)
            if i < nL:                                   # 行 i 无音频（跳过）
                v = cur - 0.2
                if v > dp[i + 1][j]:
                    dp[i + 1][j] = v
                    back[i + 1][j] = ("misline", i, j)
            if j < nS:                                   # 段 j 无词（间奏/纯音乐）
                v = cur
                if v > dp[i][j + 1]:
                    dp[i][j + 1] = v
                    back[i][j + 1] = ("misseg", i, j)
    assign = [[] for _ in segs]
    missed = []
    i, j = nL, nS
    while i > 0 or j > 0:
        op, pi, pj = back[i][j]
        if op == "match":
            assign[pj].append(pi)
        elif op == "misline":
            missed.append((pi, lyrics[pi][1], cov[pi][pj] if pj < nS else 0.0))
        i, j = pi, pj
    missed.reverse()

    # 2) 按段切分时间，行内按词数切分
    out_words = []
    for s, seg in enumerate(segs):
        ids = assign[s]
        if not ids:
            continue
        t0, t1 = seg["start"], seg["end"]
        weights = [max(1, len(lyrics[i][0])) for i in ids]
        total = sum(weights)
        cur = t0
        for li, wt in zip(ids, weights):
            slot = (t1 - t0) * wt / total
            raw = lyrics[li][1]
            toks = raw.split()
            n = max(1, len(toks))
            for k, tok in enumerate(toks):
                out_words.append({
                    "word": tok,
                    "start": cur + slot * k / n,
                    "end": cur + slot * (k + 1) / n,
                })
            cur += slot

    out = {"segments": [{"start": s["start"], "end": s["end"]} for s in segs],
           "words": out_words,
           "_meta": {"lyric_lines": len(lyrics),
                     "covered": len(lyrics) - len(missed),
                     "missed_lines": [{"line": r, "coverage": round(c, 2)}
                                      for _, r, c in missed]}}
    json.dump(out, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"歌词行覆盖 {(len(lyrics)-len(missed))}/{len(lyrics)}")
    for li, raw, c in missed[:10]:
        print(f"  MISS: {raw[:36]}  (覆盖率 {c:.2f})")


if __name__ == "__main__":
    main()
