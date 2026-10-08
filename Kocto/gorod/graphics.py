"""Optional Pillow presentation layer. No engine dependency on Pillow.

AI artwork is packaged as base64 JPEG source to support text-only repository
uploads; decoded in memory, never downloaded at runtime. Layout/text are native.
"""
from __future__ import annotations

import base64
import io
import os
from functools import lru_cache
from pathlib import Path

from .engine import DATA_DIR, DataError, load_json

try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    AVAILABLE = True
except ImportError:
    AVAILABLE = False


def config():
    obj = load_json(DATA_DIR / 'graphics.json')
    if obj.get('schema_version') != 1:
        raise DataError('graphics.json: неподдерживаемая версия')
    for key in ('city', 'portraits'):
        if not isinstance(obj.get(key), str):
            raise DataError('graphics.json: отсутствует ' + key)
        asset = (DATA_DIR / obj[key]).resolve()
        if not asset.is_relative_to(DATA_DIR.resolve()) or not asset.is_file():
            raise DataError('graphics.json: нет ресурса ' + key)
    if not isinstance(obj.get('portrait_names'), list) or len(obj['portrait_names']) != 4:
        raise DataError('graphics.json: нужно 4 имени портретов')
    if not isinstance(obj.get('palette'), dict):
        raise DataError('graphics.json: нет палитры')
    for key in ('paper', 'ink', 'blue', 'red'):
        val = obj['palette'].get(key)
        if not isinstance(val, str) or len(val) != 7 or not val.startswith('#'):
            raise DataError('graphics.json: неверный цвет '+key)
        try:
            int(val[1:], 16)
        except ValueError as exc:
            raise DataError('graphics.json: неверный цвет '+key) from exc
    return obj


@lru_cache(maxsize=2)
def artwork(kind):
    if not AVAILABLE:
        raise DataError('Графика отключена: установите Pillow')
    path = DATA_DIR / config()[kind]
    try:
        raw = base64.b64decode(path.read_bytes(), validate=True)
        im = Image.open(io.BytesIO(raw))
        im.load()
        return im.convert('RGB')
    except Exception as exc:
        raise DataError('Повреждена графика: ' + str(path)) from exc


@lru_cache(maxsize=24)
def city(width, height):
    return ImageOps.contain(artwork('city'), (max(1, width), max(1, height)), Image.Resampling.LANCZOS)


@lru_cache(maxsize=24)
def portrait(index, size):
    if index not in range(4):
        raise DataError('Нет портрета ' + str(index))
    sheet = artwork('portraits')
    w, h = sheet.size
    x, y = index % 2, index // 2
    # Crop out the narrow external/inter-panel white gutter.
    panel = sheet.crop((x*w//2+10, y*h//2+10, (x+1)*w//2-10, (y+1)*h//2-10))
    return panel.resize((size, size), Image.Resampling.LANCZOS)


@lru_cache(maxsize=32)
def font(size, headline=False):
    win = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
    candidates = ([win/'georgiab.ttf', win/'arialbd.ttf'] if headline else [win/'arial.ttf'])
    candidates += [Path('/usr/share/fonts/msttcore/georgiab.ttf') if headline else Path('/usr/share/fonts/msttcore/arial.ttf'),
                   Path('/usr/share/fonts/truetype/msttcorefonts/Arial.ttf'),
                   Path('/usr/share/fonts/dejavu/DejaVuSans.ttf'),
                   Path('/usr/share/fonts/google-noto/NotoSans-Regular.ttf')]
    for p in candidates:
        if p.is_file():
            try:
                return ImageFont.truetype(str(p), size)
            except OSError:
                continue
    # Pillow 11's bundled font supports Cyrillic; explicit check prevents tofu.
    try:
        return ImageFont.truetype('DejaVuSans.ttf', size)
    except OSError as exc:
        raise DataError('Нет шрифта с кириллицей для газеты. Текстовая вкладка остаётся доступной.') from exc


def wrapped(text, f, width):
    lines = []
    for para in str(text).split('\n'):
        line = ''
        for word in para.split():
            trial = (line+' '+word).strip()
            if f.getlength(trial) <= width:
                line = trial
                continue
            if line:
                lines.append(line)
                line = ''
            if f.getlength(word) <= width:
                line = word
            else:
                # A single extremely long name/word must not overflow the paper.
                part = ''
                for char in word:
                    if part and f.getlength(part+char) > width:
                        lines.append(part)
                        part = ''
                    part += char
                line = part
        lines.append(line)
    return lines


def newspaper(articles, week, width=900):
    if not AVAILABLE:
        raise DataError('Для экспорта газеты нужен Pillow')
    width = max(480, min(int(width), 1800))
    margin = 32
    small, body, head, mast = font(17), font(20), font(28, True), font(38, True)
    blocks, y = [], 114
    if not articles:
        articles = [{'paper_name': 'Редакция', 'headline': 'Город ждёт ваших слов',
                     'lead': 'Завершите первую неделю — здесь появится выпуск о поступках кандидатов.'}]
    for a in articles:
        for text, f, gap in ((a['paper_name'], small, 8), (a['headline'], head, 12), (a['lead'], body, 24)):
            lines = wrapped(text, f, width-2*margin)
            step = int(f.size*1.45)
            blocks.append((lines, f, y, step))
            y += step*len(lines)+gap
        y += 22
    height = y+42
    if height > 25000:
        raise DataError('Слишком длинный газетный выпуск')
    palette = config()['palette']
    im = Image.new('RGB', (width, height), palette['paper'])
    draw = ImageDraw.Draw(im)
    draw.text((margin, 20), 'ГОРОД ПОМНИТ', font=mast, fill=palette['ink'])
    draw.text((margin, 70), f'Выпуск недели {week} · Хроника города', font=small, fill='#59636b')
    draw.line((margin, 100, width-margin, 100), fill=palette['ink'], width=2)
    for lines, f, top, step in blocks:
        for j, text in enumerate(lines):
            draw.text((margin, top+j*step), text, font=f, fill=palette['ink'])
    draw.line((margin, height-40, width-margin, height-40), fill='#9e978b', width=1)
    draw.text((margin, height-32), 'Слова — ваши. Последствия — городские.', font=small, fill='#59636b')
    return im
