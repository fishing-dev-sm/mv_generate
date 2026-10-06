#!/usr/bin/env python3
"""核韵脚本：按 MiniMax-Music3 结构标签分段，机械核验每段行末字韵脚是否符合声明。

用法: rhyme_audit.py <歌词.md>
规则:
  - [Tag] 开新段; <!-- 韵脚: X --> 声明该段韵脚（可缺省）
  - 括号开头的行（念白/舞台提示）只报告不判定
  - 每行取最后一个汉字，用 pypinyin 取韵母，与段内多数韵母比对
输出: 每段的逐行末字拼音表 + 脱韵行清单，退出码 1 = 有脱韵
"""
import re
import sys
from collections import Counter

from pypinyin import Style, pinyin

TAG = re.compile(r"^\s*\[([^\]]+)\]")
DECLARE = re.compile(r"<!--\s*韵脚[:：]\s*(.+?)\s*-->")
HANZI = re.compile(r"[一-鿿]")

# 韵母分组（十三辙宽式）
GROUPS = {
    "a": "发花", "ia": "发花", "ua": "发花",
    "e": "梭波", "o": "梭波", "uo": "梭波",
    "ie": "乜斜", "ve": "乜斜", "er": "儿化",
    "i": "一七", "v": "一七", "-i": "一七",
    "u": "姑苏",
    "ai": "怀来", "uai": "怀来",
    "ei": "灰堆", "ui": "灰堆", "uei": "灰堆",
    "ao": "遥迢", "iao": "遥迢",
    "ou": "由求", "iu": "由求", "iou": "由求",
    "an": "言前", "ian": "言前", "uan": "言前", "van": "言前",
    "en": "人辰", "in": "人辰", "un": "人辰", "vn": "人辰",
    "ang": "江阳", "iang": "江阳", "uang": "江阳",
    "eng": "中东", "ing": "中东", "ong": "中东", "ueng": "中东", "iong": "中东",
}


def final_of(char: str) -> str:
    py = pinyin(char, style=Style.FINALS, strict=True, neutral_tone_with_five=False)
    f = py[0][0]
    if f == "":
        f = pinyin(char, style=Style.FINALS, strict=False)[0][0]
    return f


def last_hanzi(line: str) -> str | None:
    chars = HANZI.findall(line)
    return chars[-1] if chars else None


def main(path: str) -> int:
    sections = []  # (tag, declared, lines)
    tag, declared, lines = "（开头）", None, []
    for raw in open(path, encoding="utf-8"):
        line = raw.rstrip("\n")
        m = TAG.match(line)
        if m:
            sections.append((tag, declared, lines))
            tag, declared, lines = m.group(1), None, []
            continue
        d = DECLARE.search(line)
        if d:
            declared = d.group(1)
            continue
        if not line.strip() or line.strip().startswith("#") or line.strip().startswith("<!--"):
            continue
        lines.append(line.strip())
    sections.append((tag, declared, lines))

    bad = 0
    for tag, declared, lines in sections:
        if not lines:
            continue
        print(f"\n== [{tag}]  声明韵脚: {declared or '（未声明）'} ==")
        rows = []
        for ln in lines:
            spoken = ln.startswith("（") or ln.startswith("(")
            ch = last_hanzi(ln)
            if ch is None:
                continue
            f = final_of(ch)
            g = GROUPS.get(f, f"?{f}")
            rows.append((ln, ch, f, g, spoken))
        # 非念白行的多数韵组 = 实际韵脚
        real = Counter(g for _, _, _, g, s in rows if not s)
        main_rhyme = real.most_common(1)[0][0] if real else None
        for ln, ch, f, g, spoken in rows:
            mark = ""
            if spoken:
                mark = "(念白/提示)"
            elif g != main_rhyme:
                mark = f"  << 脱韵! 应为 {main_rhyme}"
                bad += 1
            print(f"  {ch:>2} {f:<6}{g:<4} {ln[:38]}{mark}")
        print(f"  --> 实际韵脚: {main_rhyme} ({dict(real)})")
    print(f"\n{'核韵通过，无脱韵' if bad == 0 else f'发现 {bad} 行脱韵'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
