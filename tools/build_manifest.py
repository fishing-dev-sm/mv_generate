"""Parse board-final.md plate_prompt section -> plates/manifest.json.

Expands placeholders: C -> 主角 canon, S -> 统一风格后缀.
s005 (纯代码卡) gets prompt=None and is excluded from image generation.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOARD = ROOT / 'storyboard' / 'board-final.md'
OUT = ROOT / 'plates' / 'manifest.json'

CANON = '年轻女性，黑色凌乱狼尾中长发（后颈发尾较长），苍白肤色，淡妆冷脸，黑色无袖上衣'
STYLE = ('冷峻电影感，蓝黑与钢蓝色调，一盏红色小灯是画面中唯一暖色，'
         '细腻胶片颗粒，画面上半或指定区域留白供字幕，无文字无字母无数字，1344×768 横构图')

C_TOKEN = re.compile(r'(?<![A-Za-z0-9])C(?![A-Za-z0-9])')


def main():
    text = BOARD.read_text(encoding='utf-8')
    section = text.split('## plate_prompt 全文', 1)[1]
    entries = []
    for line in section.splitlines():
        m = re.match(r'- \*\*(s\d{3})\*\*(?:（[^）]*）)?：(.*)', line.strip())
        if not m:
            continue
        sid, body = m.group(1), m.group(2).strip()
        has_char = bool(C_TOKEN.search(body))
        if body.startswith('（无 plate'):
            entries.append({'id': sid, 'has_character': False, 'prompt': None,
                            'note': '纯代码卡，不生成 plate'})
            continue
        # strip trailing production notes like （60% 数据由代码 overlay，不进 plate）
        body = re.sub(r'（[^（）]*(?:overlay|例外)[^（）]*）\s*$', '', body).strip()
        # expand S (whole trailing token, possibly followed by nothing after note strip)
        body = re.sub(r'，?\s*S\s*$', '，' + STYLE, body)
        # expand C -> canon
        body = C_TOKEN.sub(CANON, body)
        entries.append({'id': sid, 'has_character': has_char, 'prompt': body})
    OUT.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding='utf-8')
    n_char = sum(1 for e in entries if e['has_character'])
    n_none = sum(1 for e in entries if e['prompt'] is None)
    print(f'total={len(entries)} character={n_char} no-character={len(entries)-n_char-n_none} no-plate={n_none}')


if __name__ == '__main__':
    main()
