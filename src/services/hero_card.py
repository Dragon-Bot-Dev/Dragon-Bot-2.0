"""Renders a player's heroes (with equipped gear) and pets as a single PNG.

Takes plain dicts, not coc.py objects, so it can be tested without the API:

    heroes: [{"name", "level", "is_max", "gear": [{"name", "level", "is_max"}]}]
    pets:   [{"name", "level", "is_max"}]

Artwork is fetched from ClashKing's asset host (https://assets.clashk.ing,
served from github.com/ClashKingInc/ClashKingAssets) and cached in memory.
The host only provides square icon.webp art per item (no full-body models),
so cards use those icons. Any icon that can't be fetched becomes a labelled
placeholder tile, so a CDN outage degrades the image instead of breaking it.
"""

import asyncio
import io
import os
import time

import aiohttp
from PIL import Image, ImageDraw, ImageFont

ASSET_BASE = "https://assets.clashk.ing"
FONT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "fonts", "LilitaOne-Regular.ttf")

HERO_ORDER = ["barbarian king", "archer queen", "grand warden", "royal champion", "minion prince", "dragon duke"]

FOOTER_LINES = (
    "Unofficial fan content, not endorsed by Supercell. See supercell.com/fan-content-policy",
    "Art: ClashKing assets (assets.clashk.ing)",
)

# Layout
PAD = 16
GAP = 12
COLS = 3
CARD_W, CARD_H = 200, 236
HERO_ICON = 140
GEAR_ICON = 46
GEAR_STEP = 62
PET_COLS = 6
PET_W, PET_H = 96, 118
PET_GAP = 8
PET_ICON = 68
WIDTH = PAD * 2 + COLS * CARD_W + (COLS - 1) * GAP

BG = (24, 24, 27)
CARD_BG = (38, 38, 43)
CARD_EDGE = (62, 62, 70)
GOLD = (255, 204, 64)
WHITE = (245, 245, 245)
PLACEHOLDER_BG = (66, 66, 76)

# bytes (or None for "doesn't exist") per (category, name). Icons are small
# (~10-20 KB), and there are only ~60 of them, so caching forever is fine.
_icon_cache = {}
# Transient failures (timeouts, 5xx) are retried after a short pause instead of
# being cached as missing forever.
_retry_after = {}
_RETRY_SECONDS = 300


def _clean(name):
    # Mirrors the name-cleaning rule in the ClashKingAssets README.
    return (name.lower().replace(" ", "_").replace(".", "").replace("?", "")
            .replace("\\q", "").replace("’", "").replace("'", ""))


def icon_url(category, name):
    cleaned = _clean(name)
    if category == "equipment":
        return f"{ASSET_BASE}/equipment/{cleaned}.webp"
    return f"{ASSET_BASE}/{category}/{cleaned}/icon.webp"


async def _fetch_one(session, sem, key):
    if key in _icon_cache:
        return
    if _retry_after.get(key, 0) > time.time():
        return
    category, name = key
    async with sem:
        try:
            async with session.get(icon_url(category, name)) as resp:
                if resp.status == 200:
                    _icon_cache[key] = await resp.read()
                elif resp.status == 404:
                    _icon_cache[key] = None
                else:
                    _retry_after[key] = time.time() + _RETRY_SECONDS
        except Exception as e:
            print(f"⚠️ Icon fetch failed for {key}: {e}")
            _retry_after[key] = time.time() + _RETRY_SECONDS


async def fetch_icons(keys):
    """Downloads any (category, name) icons not already cached."""
    pending = [k for k in set(keys) if k not in _icon_cache]
    if not pending:
        return
    sem = asyncio.Semaphore(10)
    timeout = aiohttp.ClientTimeout(total=5)
    async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": "DragonBot/2.0"}) as session:
        await asyncio.gather(*(_fetch_one(session, sem, k) for k in pending))


def _font(size):
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except OSError:
        return ImageFont.load_default()


def _text_outlined(draw, xy, text, font, fill):
    draw.text(xy, text, font=font, fill=fill, stroke_width=2, stroke_fill=(0, 0, 0))


def _paste_icon(canvas, key, box_x, box_y, box_size, label):
    """Fits an icon inside a box_size square at (box_x, box_y), preserving
    aspect ratio and centering it. Falls back to a labelled placeholder."""
    raw = _icon_cache.get(key)
    if raw:
        try:
            icon = Image.open(io.BytesIO(raw)).convert("RGBA")
            icon.thumbnail((box_size, box_size), Image.LANCZOS)
            canvas.paste(icon, (box_x + (box_size - icon.width) // 2, box_y + (box_size - icon.height) // 2), icon)
            return
        except Exception as e:
            print(f"⚠️ Could not decode icon {key}: {e}")

    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((box_x, box_y, box_x + box_size, box_y + box_size), radius=8, fill=PLACEHOLDER_BG)
    initials = "".join(w[0] for w in label.split()[:2]).upper() or "?"
    font = _font(max(12, box_size // 2))
    w = draw.textlength(initials, font=font)
    draw.text((box_x + (box_size - w) / 2, box_y + box_size * 0.22), initials, font=font, fill=WHITE)


def _row_x_positions(count, cols, item_w, gap, total_w):
    """x offsets for `count` items laid out in rows of `cols`, with a
    short last row centered (matches the mockup's 3 + 2 hero layout)."""
    xs = []
    for i in range(count):
        row, col = divmod(i, cols)
        in_row = min(cols, count - row * cols)
        row_w = in_row * item_w + (in_row - 1) * gap
        xs.append((total_w - row_w) // 2 + col * (item_w + gap))
    return xs


def _wrap(draw, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def render_hero_image(heroes, pets):
    """Synchronous Pillow render using whatever is in the icon cache.
    Returns PNG bytes. Run via asyncio.to_thread."""
    hero_xs = _row_x_positions(len(heroes), COLS, CARD_W, GAP, WIDTH - PAD * 2)
    hero_rows = (len(heroes) + COLS - 1) // COLS
    pet_rows = (len(pets) + PET_COLS - 1) // PET_COLS

    scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    foot_font = _font(13)
    footer = [l for line in FOOTER_LINES for l in _wrap(scratch, line, foot_font, WIDTH - PAD * 2)]

    height = PAD
    height += hero_rows * (CARD_H + GAP)
    if pets:
        height += 34 + pet_rows * (PET_H + PET_GAP) + GAP
    height += len(footer) * 17 + PAD

    canvas = Image.new("RGBA", (WIDTH, height), BG)
    draw = ImageDraw.Draw(canvas)
    lvl_font, gear_font, head_font = _font(22), _font(14), _font(24)

    y = PAD
    for i, hero in enumerate(heroes):
        row = i // COLS
        cx, cy = PAD + hero_xs[i], y + row * (CARD_H + GAP)
        draw.rounded_rectangle((cx, cy, cx + CARD_W, cy + CARD_H), radius=14, fill=CARD_BG,
                               outline=GOLD if hero.get("is_max") else CARD_EDGE, width=2)
        _paste_icon(canvas, ("heroes", hero["name"]), cx + (CARD_W - HERO_ICON) // 2, cy + 28, HERO_ICON, hero["name"])
        _text_outlined(draw, (cx + 10, cy + 4), f"Lv {hero['level']}", lvl_font, GOLD if hero.get("is_max") else WHITE)

        for g, gear in enumerate(hero.get("gear", [])[:3]):
            gx, gy = cx + 12 + g * GEAR_STEP, cy + 172
            _paste_icon(canvas, ("equipment", gear["name"]), gx, gy, GEAR_ICON, gear["name"])
            _text_outlined(draw, (gx, gy + GEAR_ICON - 2), f"Lv {gear['level']}", gear_font,
                           GOLD if gear.get("is_max") else WHITE)
    y += hero_rows * (CARD_H + GAP)

    if pets:
        draw.text((PAD, y), "Pets", font=head_font, fill=WHITE)
        y += 34
        pet_xs = _row_x_positions(len(pets), PET_COLS, PET_W, PET_GAP, WIDTH - PAD * 2)
        for i, pet in enumerate(pets):
            row = i // PET_COLS
            px, py = PAD + pet_xs[i], y + row * (PET_H + PET_GAP)
            draw.rounded_rectangle((px, py, px + PET_W, py + PET_H), radius=10, fill=CARD_BG,
                                   outline=GOLD if pet.get("is_max") else CARD_EDGE, width=2)
            _paste_icon(canvas, ("pets", pet["name"]), px + (PET_W - PET_ICON) // 2, py + 8, PET_ICON, pet["name"])
            label = f"Lv {pet['level']}"
            w = draw.textlength(label, font=gear_font)
            _text_outlined(draw, (px + (PET_W - w) / 2, py + PET_H - 28), label, gear_font,
                           GOLD if pet.get("is_max") else WHITE)
        y += pet_rows * (PET_H + PET_GAP) + GAP

    for line in footer:
        draw.text((PAD, y), line, font=foot_font, fill=(150, 150, 158))
        y += 17

    out = io.BytesIO()
    canvas.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()


async def build_hero_image(heroes, pets):
    """Fetches any missing icons, then renders off the event loop."""
    keys = [("heroes", h["name"]) for h in heroes]
    keys += [("equipment", g["name"]) for h in heroes for g in h.get("gear", [])[:3]]
    keys += [("pets", p["name"]) for p in pets]
    await fetch_icons(keys)
    return await asyncio.to_thread(render_hero_image, heroes, pets)
