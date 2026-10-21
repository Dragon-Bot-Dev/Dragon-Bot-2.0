"""Renders a player's troops, siege machines, spells (and builder troops) as a
single PNG grid of icon tiles with levels. Shares icon fetching/caching and
drawing helpers with services.hero_card.

Takes plain dicts so it can be tested without the API:

    sections: [{"title": str,
                "items": [{"category": "troops"|"spells", "name", "level",
                           "max_level", "is_max"}]}]
"""

import asyncio
import io

from PIL import Image, ImageDraw

from services.hero_card import (
    BG, CARD_BG, CARD_EDGE, GOLD, WHITE, FOOTER_LINES, PAD, WIDTH,
    _font, _paste_icon, _text_outlined, _wrap, fetch_icons,
)

COLS = 7
TILE_W, TILE_H = 84, 104
TILE_GAP = 6
ICON = 64
HEADER_H = 36
SECTION_GAP = 10


def _label(draw, item, font):
    """'Lv 12' when maxed; otherwise 'Lv 10/12' so progress to max is visible."""
    text = f"Lv {item['level']}" if item.get("is_max") else f"Lv {item['level']}/{item['max_level']}"
    if draw.textlength(text, font=font) > TILE_W - 6:
        text = text[3:]  # drop "Lv " if it still doesn't fit
    return text


def render_levels_image(sections):
    """Synchronous Pillow render using whatever is in the icon cache.
    Returns PNG bytes. Run via asyncio.to_thread."""
    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    foot_font = _font(13)
    footer = [l for line in FOOTER_LINES for l in _wrap(scratch, line, foot_font, WIDTH - PAD * 2)]

    height = PAD
    for sec in sections:
        rows = (len(sec["items"]) + COLS - 1) // COLS
        height += HEADER_H + rows * (TILE_H + TILE_GAP) + SECTION_GAP
    height += len(footer) * 17 + PAD

    canvas = Image.new("RGBA", (WIDTH, height), BG)
    draw = ImageDraw.Draw(canvas)
    head_font, lvl_font = _font(24), _font(13)

    y = PAD
    for sec in sections:
        draw.text((PAD, y), sec["title"], font=head_font, fill=WHITE)
        y += HEADER_H
        for i, item in enumerate(sec["items"]):
            row, col = divmod(i, COLS)
            tx = PAD + col * (TILE_W + TILE_GAP)
            ty = y + row * (TILE_H + TILE_GAP)
            is_max = item.get("is_max")
            draw.rounded_rectangle((tx, ty, tx + TILE_W, ty + TILE_H), radius=10, fill=CARD_BG,
                                   outline=GOLD if is_max else CARD_EDGE, width=2)
            _paste_icon(canvas, (item["category"], item["name"]), tx + (TILE_W - ICON) // 2, ty + 8, ICON, item["name"])
            text = _label(draw, item, lvl_font)
            w = draw.textlength(text, font=lvl_font)
            _text_outlined(draw, (tx + (TILE_W - w) / 2, ty + TILE_H - 26), text, lvl_font,
                           GOLD if is_max else WHITE)
        rows = (len(sec["items"]) + COLS - 1) // COLS
        y += rows * (TILE_H + TILE_GAP) + SECTION_GAP

    for line in footer:
        draw.text((PAD, y), line, font=foot_font, fill=(150, 150, 158))
        y += 17

    out = io.BytesIO()
    canvas.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()


async def build_levels_image(sections):
    """Fetches any missing icons, then renders off the event loop."""
    await fetch_icons([(i["category"], i["name"]) for sec in sections for i in sec["items"]])
    return await asyncio.to_thread(render_levels_image, sections)
