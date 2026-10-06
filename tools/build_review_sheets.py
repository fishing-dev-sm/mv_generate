"""Build per-section review contact sheets for the full candidate pool (a-f).

Per shot: a 3-col x 2-row mini grid (a b c / d e f), each tile labeled
"s0NN · X"; missing candidates render as red-text dark placeholders.
Output: plates/review/contact-<Section>.jpg, 10 files, each <= 2400px wide.
s005 (pure code card) is excluded.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
PLATES = ROOT / 'plates'
REVIEW = PLATES / 'review'

SECTIONS = [
    ('Intro', ['s001', 's002', 's003']),
    ('V1', ['s004', 's005', 's006', 's007', 's008', 's009', 's010']),
    ('C1', ['s011', 's012', 's013', 's014', 's015', 's016']),
    ('V2', ['s017', 's018', 's019', 's020', 's021', 's022']),
    ('C2', ['s023', 's024', 's025', 's026', 's027', 's028']),
    ('V3', ['s029', 's030', 's031', 's032', 's033', 's034']),
    ('Bridge', ['s035', 's036', 's037']),
    ('V4', ['s038', 's039', 's040', 's041', 's042', 's043', 's044']),
    ('C3', ['s045', 's046', 's047', 's048', 's049', 's050', 's051', 's052']),
    ('Outro', ['s053', 's054', 's055']),
]

MAX_W = 2400
PAD = 10
TITLE_H = 44
LABEL_H = 28
BG = (10, 14, 20)
FG = (235, 240, 245)
MISS_BG = (28, 34, 44)
MISS_FG = (200, 90, 90)
CANDIDATES = ('a', 'b', 'c', 'd', 'e', 'f')
COLS = 3  # grid per shot: a b c / d e f


def font(size):
    for name in ('/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc',
                 '/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc',
                 'DejaVuSans-Bold.ttf', 'DejaVuSans.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


F_TITLE = font(30)
F_LABEL = font(22)


def tile(sid, cand, w, h):
    p = PLATES / f'{sid}-{cand}.png'
    if p.exists():
        return Image.open(p).convert('RGB').resize((w, h), Image.LANCZOS)
    img = Image.new('RGB', (w, h), MISS_BG)
    d = ImageDraw.Draw(img)
    msg = f'{sid} · {cand.upper()} MISSING'
    bb = d.textbbox((0, 0), msg, font=F_LABEL)
    d.text(((w - bb[2]) // 2, (h - bb[3]) // 2), msg, fill=MISS_FG, font=F_LABEL)
    return img


def build_section(name, ids):
    ids = [i for i in ids if i != 's005']  # pure code card, no plate
    img_w = (MAX_W - (COLS + 1) * PAD) // COLS
    img_h = round(img_w * 768 / 1344)
    cell_h = LABEL_H + img_h
    rows_per_shot = (len(CANDIDATES) + COLS - 1) // COLS
    block_h = rows_per_shot * cell_h
    W = COLS * img_w + (COLS + 1) * PAD
    H = TITLE_H + len(ids) * (block_h + PAD) + PAD
    sheet = Image.new('RGB', (W, H), BG)
    d = ImageDraw.Draw(sheet)
    d.text((PAD, 8), f'《示例项目 A》plate 抽卡池 a–f · {name}（{len(ids)} 镜）',
           fill=FG, font=F_TITLE)
    y = TITLE_H
    for sid in ids:
        for i, cand in enumerate(CANDIDATES):
            col, row = i % COLS, i // COLS
            x = PAD + col * (img_w + PAD)
            cy = y + row * cell_h
            d.text((x + 4, cy + 2), f'{sid} · {cand.upper()}', fill=FG, font=F_LABEL)
            sheet.paste(tile(sid, cand, img_w, img_h), (x, cy + LABEL_H))
        y += block_h + PAD
    REVIEW.mkdir(exist_ok=True)
    out = REVIEW / f'contact-{name}.jpg'
    sheet.save(out, quality=88)
    return out, sheet.size


def main():
    for name, ids in SECTIONS:
        out, size = build_section(name, ids)
        print(f'{out.name}: {size[0]}x{size[1]}')


if __name__ == '__main__':
    main()
