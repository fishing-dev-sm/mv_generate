#!/usr/bin/env python3
"""分镜重锚：把 board-final.md 的 55 镜从旧曲时序映射到新母带。

输入：
  lyrics/final.md            —— L 行号约定来源（物理行号）
  lyrics/draft-industry.md   —— 新歌词（导演改版）
  song/analysis/words-fixed.json —— 新母带逐词时间（DP 回填后）
  song/analysis/beatmap.json —— 新母带拍点
  storyboard/board-final.md  —— 旧分镜（t0/t1 为旧曲时间）
  segments.json              —— 旧 24 段（分组/plates 沿用）
输出：
  storyboard/board-v2.md     —— 新分镜（仅 t0/t1 与 H3 窗口列更新）
  segments-v2.json           —— 新 24 段窗口（H3 帧网格 17k+5 吸附）
  stdout 摘要（行映射审核表、被删行、段落边界）
"""
import json
import os
import re
import sys
from difflib import SequenceMatcher

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def norm(s):
    return "".join(re.findall(r"[一-鿿a-zA-Z0-9]", s)).lower()


def load_final_lmap():
    """final.md 物理行号 -> 歌词文本（L 行号约定）。"""
    lmap = {}
    with open(os.path.join(ROOT, "lyrics/final.md"), encoding="utf8") as f:
        for n, line in enumerate(f, 1):
            t = line.strip()
            if t and not t.startswith("#") and not t.startswith("<!--") \
               and not t.startswith("-") and not re.fullmatch(r"\[[^\]]+\]", t):
                lmap[n] = t
    return lmap


def load_draft_lines():
    """新歌词行（清洗同 §4：去注释/提示/标签）。"""
    out = []
    with open(os.path.join(ROOT, "lyrics/draft-industry.md"), encoding="utf8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#") or s.startswith("<!--") \
               or s.startswith("创作说明") or s.startswith("-"):
                continue
            if re.fullmatch(r"\[[^\]]+\]", s):
                continue
            if s.startswith("（") and s.endswith("）"):
                continue
            out.append(s)
    return out


def line_times(draft_lines, words):
    """字符级对齐：拼接歌词全文 vs 拼接 token 流，opcodes 定位每行首个命中字符的 token 时间；
    未命中行（whisper 漏行）返回 None，由调用方线性插值。"""
    lyric_full, line_off = "", []
    for ln in draft_lines:
        line_off.append(len(lyric_full))
        lyric_full += norm(ln)
    tok_full, tok_off = "", []
    for w in words:
        tok_off.append(len(tok_full))
        tok_full += norm(w["word"])

    def tok_at(char_pos):
        import bisect
        return max(0, min(bisect.bisect_right(tok_off, char_pos) - 1, len(words) - 1))

    times = {}
    sm = SequenceMatcher(None, lyric_full, tok_full, autojunk=False)
    for i, off in enumerate(line_off):
        if not norm(draft_lines[i]):
            continue
        for tag, a0, a1, b0, b1 in sm.get_opcodes():
            if tag == "equal" and a0 <= off < a1:
                times[i] = words[tok_at(b0 + (off - a0))]["start"]
                break
    # 未命中行：相邻锚定行线性插值
    anchored = sorted(times)
    for i in range(len(draft_lines)):
        if i in times or not norm(draft_lines[i]):
            continue
        prev = max([a for a in anchored if a < i], default=None)
        nxt = min([a for a in anchored if a > i], default=None)
        if prev is not None and nxt is not None:
            times[i] = times[prev] + (times[nxt] - times[prev]) * (i - prev) / (nxt - prev)
        elif prev is not None:
            times[i] = times[prev] + 3.0
        elif nxt is not None:
            times[i] = max(0.0, times[nxt] - 3.0)
    return times


def nearest_beat(beats, t, direction="down"):
    cands = [b for b in beats if b <= t + 0.22] if direction == "down" else beats
    return min(cands, key=lambda b: abs(b - t)) if cands else t


H3_GRID = [17 * k + 5 for k in range(5, 22)]   # 90..362


def grid_frames(span):
    """最小满足 dur >= span-0.1 的 H3 帧数；超 15.08s 上限返回 None（需拆组）。"""
    ok = [n for n in H3_GRID if n / 24 >= span - 0.1]
    return ok[0] if ok else None


def main():
    lmap = load_final_lmap()
    draft = load_draft_lines()
    wf = json.load(open(os.path.join(ROOT, "song/analysis/words-fixed.json")))
    beats = json.load(open(os.path.join(ROOT, "song/analysis/beatmap.json")))["beats"]
    dt = line_times(draft, wf["words"])

    # final L 行 -> 新词行：行序列全局对齐（正确处理重复副歌的第 N 次出现）
    l2time, report = {}, []
    fkeys = sorted(lmap)
    fseq = [norm(re.sub(r"^（[^）]*）", "", lmap[n])) for n in fkeys]
    dseq = [norm(d) for d in draft]
    sm = SequenceMatcher(None, fseq, dseq, autojunk=False)
    for tag, a0, a1, b0, b1 in sm.get_opcodes():
        if tag == "equal":
            for k in range(a1 - a0):
                if dt.get(b0 + k) is not None:
                    l2time[fkeys[a0 + k]] = dt[b0 + k]
        elif tag == "replace":
            pairs = min(a1 - a0, b1 - b0)
            for k in range(pairs):     # 块内按序配对（改词行）
                fa, db = fkeys[a0 + k], b0 + k
                if dt.get(db) is not None:
                    l2time[fa] = dt[db]
                    report.append(f"  L{fa} 改词: {lmap[fa][:24]} -> {draft[db][:24]}")
            for k in range(pairs, a1 - a0):
                report.append(f"  L{fkeys[a0+k]} DELETED: {lmap[fkeys[a0+k]][:28]}")
        elif tag == "delete":
            for k in range(a1 - a0):
                report.append(f"  L{fkeys[a0+k]} DELETED: {lmap[fkeys[a0+k]][:28]}")

    # 解析旧分镜行
    board = open(os.path.join(ROOT, "storyboard/board-final.md"), encoding="utf8").read()
    rows = []
    for m in re.finditer(r"^\| (s\d{3}) \| ([\d.]+) \| ([\d.]+) \| (L\d+(?:–\d+)?) \|(.*)\|$",
                         board, re.M):
        sid, t0, t1, lref, rest = m.groups()
        rows.append({"id": sid, "t0": float(t0), "t1": float(t1), "lref": lref, "rest": rest})
    assert len(rows) == 55, f"分镜行数 {len(rows)} != 55"

    # 每镜新 t0（删行镜待二次分配）
    for r in rows:
        nums = [int(x) for x in re.findall(r"\d+", r["lref"])]
        t = l2time.get(nums[0])
        r["new_t0_raw"] = t
        r["dur"] = r["t1"] - r["t0"]
    for i, r in enumerate(rows):
        if r["new_t0_raw"] is not None:
            continue
        nxt = next((rows[j] for j in range(i + 1, len(rows)) if rows[j]["new_t0_raw"] is not None), None)
        r["new_t0_raw"] = (nxt["new_t0_raw"] - r["dur"]) if nxt else r["new_t0_raw"]
        report.append(f"  {r['id']}({r['lref']} 删行) 按旧时长 {r['dur']:.2f}s 回填")
    for r in rows:
        r["new_t0"] = 0.0 if r is rows[0] else round(nearest_beat(beats, r["new_t0_raw"]), 2)
    for i, r in enumerate(rows):
        r["new_t1"] = rows[i + 1]["new_t0"] if i + 1 < len(rows) else 200.30

    # 写 board-v2.md（只换 t0/t1 与 H3 窗口列）
    def repl(m):
        sid = m.group(1)
        r = next(x for x in rows if x["id"] == sid)
        line = m.group(0)
        parts = line.split("|")
        parts[2], parts[3] = f" {r['new_t0']:.2f} ", f" {r['new_t1']:.2f} "
        h3 = re.search(r"H3-(\d+)：", line)
        if h3:
            parts[9] = re.sub(r"H3-(\d+)：[^（]+（裁 [^）]+）",
                              f"H3-\\1：{r['new_t0']:.2f}–{r['new_t0']+5.17:.2f}"
                              f"（裁 {r['new_t0']:.2f}–{r['new_t1']:.2f}）", parts[9])
        return "|".join(parts)

    v2 = re.sub(r"^\| (s\d{3}) \| [\d.]+ \| [\d.]+ \| L\d+(?:–\d+)? \|.*\|$",
                repl, board, flags=re.M)
    open(os.path.join(ROOT, "storyboard/board-v2.md"), "w", encoding="utf8").write(v2)

    # segments-v2.json（导演裁决后的 27 段新分组：c02/c04/c05 拆组，全量重编号）
    old_segs = json.load(open(os.path.join(ROOT, "segments.json")))["segments"]
    plate_of = {}                      # 从文件名反解 shot -> plate
    for s in old_segs:
        for p in s["plates"]:
            plate_of[os.path.basename(p).split("-")[0]] = p
    sung_shots = {"s002", "s011", "s023", "s036", "s045", "s055"}
    GROUPS = [("c", ["s001"]), ("i", ["s002"]),
              ("c", ["s003", "s004", "s005"]), ("c", ["s006"]), ("i", ["s007"]),
              ("c", ["s008", "s009", "s010"]), ("i", ["s011"]),
              ("c", ["s012", "s013", "s014"]), ("c", ["s015", "s016", "s017"]),
              ("i", ["s018"]), ("c", ["s019", "s020"]), ("c", ["s021", "s022"]),
              ("i", ["s023"]), ("c", ["s024", "s025", "s026", "s027", "s028"]),
              ("c", ["s029", "s030", "s031"]), ("i", ["s032"]),
              ("c", ["s033", "s034", "s035"]), ("i", ["s036"]),
              ("c", ["s037", "s038"]), ("i", ["s039"]),
              ("c", ["s040", "s041", "s042"]), ("i", ["s043"]), ("i", ["s044"]),
              ("i", ["s045", "s046"]),
              ("c", ["s047", "s048", "s049", "s050", "s051"]),
              ("c", ["s052", "s053", "s054"]), ("i", ["s055"])]
    t0of = {r["id"]: r["new_t0"] for r in rows}
    t1of = {r["id"]: r["new_t1"] for r in rows}
    out, overs, counters = [], [], {"c": 0, "i": 0}
    for kind, shots in GROUPS:
        counters[kind] += 1
        sid = f"{kind}{counters[kind]:02d}"
        t0 = t0of[shots[0]]
        span = t1of[shots[-1]] - t0
        frames = grid_frames(span)
        if frames is None:
            overs.append(f"  {sid}: span={span:.2f}s > 15.08s（{'+'.join(shots)}）需拆组")
            window = [round(t0, 2), round(t1of[shots[-1]], 2)]
        else:
            window = [round(t0, 2), round(t0 + frames / 24, 2)]
        out.append({"id": sid, "kind": "container" if kind == "c" else "individual",
                    "shots": shots, "window": window, "frames": frames,
                    "sung": any(sh in sung_shots for sh in shots),
                    "plates": [plate_of[sh] for sh in shots if sh in plate_of]})
    json.dump({"segments": out},
              open(os.path.join(ROOT, "segments-v2.json"), "w"), ensure_ascii=False, indent=2)

    print("== 行映射审核 ==")
    print("\n".join(report) if report else "  全部直接匹配")
    print("\n== 关键锚点 ==")
    for r in rows:
        if r["id"] in ("s001", "s002", "s011", "s023", "s036", "s045", "s052", "s055"):
            print(f"  {r['id']}: {r['t0']:.2f}->{r['new_t0']:.2f}  {r['t1']:.2f}->{r['new_t1']:.2f}")
    print("\n== 新 24 段 ==")
    for s in out:
        print(f"  {s['id']}: {s['window'][0]:.2f}–{s['window'][1]:.2f} ({s['frames']}f)")
    if overs:
        print("\n== 超 H3 上限待拆组 ==")
        print("\n".join(overs))


if __name__ == "__main__":
    main()
