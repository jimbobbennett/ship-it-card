"""Render a CardStats + artwork into a trading-card PNG."""

from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .stats import CardStats

FONTS = Path(__file__).parent / "fonts"
W, H = 1080, 1512
PAD = 36

RARITY_COLOURS = {
    "Common": (168, 178, 193),
    "Uncommon": (84, 214, 160),
    "Rare": (88, 160, 255),
    "Epic": (190, 110, 255),
    "Legendary": (255, 196, 64),
}
RARITY_STARS = {"Common": 1, "Uncommon": 2, "Rare": 3, "Epic": 4, "Legendary": 5}

PANEL = (17, 19, 31)
PANEL_LIGHT = (32, 35, 54)
INK = (244, 245, 250)
MUTED = (150, 156, 180)
HUMAN = (70, 76, 104)
BOT = (224, 122, 72)

# Tag text -> tag box width, for chips that carry a tag.
TAG_WIDTHS = {"AI": 30, "BOT": 44}


@lru_cache(maxsize=32)
def font(name: str, size: int, weight: str | None = None) -> ImageFont.FreeTypeFont:
    files = {
        "display": "Bungee-Regular.ttf",
        "body": "SpaceGrotesk.ttf",
        "mono": "JetBrainsMono.ttf",
    }
    f = ImageFont.truetype(str(FONTS / files[name]), size)
    if weight:
        try:
            f.set_variation_by_name(weight)
        except (OSError, ValueError):
            pass
    return f


def render_card(stats: CardStats, art: Image.Image) -> Image.Image:
    accent = RARITY_COLOURS.get(stats.rarity, RARITY_COLOURS["Common"])
    card = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(card)

    draw.rounded_rectangle((0, 0, W - 1, H - 1), radius=56, fill=accent)
    draw.rounded_rectangle((PAD, PAD, W - PAD, H - PAD), radius=34, fill=PANEL)

    _header(draw, stats, accent)
    _art(card, draw, art, accent)
    _type_bar(draw, stats, accent)
    _abilities(draw, stats, accent)
    _crew(draw, stats, accent)
    _footer(draw, stats)
    return card


def card_png(stats: CardStats, art: Image.Image) -> bytes:
    buffer = io.BytesIO()
    render_card(stats, art).save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _header(draw: ImageDraw.ImageDraw, stats: CardStats, accent) -> None:
    score_font = font("mono", 76, "ExtraBold")
    label_font = font("mono", 22, "Bold")
    score = str(stats.ship_score)
    score_w = draw.textlength(score, font=score_font)
    right = W - PAD - 36
    draw.text((right - score_w, 62), score, font=score_font, fill=accent)
    draw.text((right - score_w - 70, 92), "SHIP", font=label_font, fill=MUTED)

    title_space = right - score_w - 90 - (PAD + 36)
    title_font, lines = _fit_title(draw, stats.title, title_space)
    y = 64 if len(lines) == 1 else 54
    for line in lines:
        draw.text((PAD + 36, y), line, font=title_font, fill=INK)
        y += title_font.size + 6

    sub = f"{stats.repo}  #{stats.number}"
    draw.text((PAD + 36, 174), sub, font=font("body", 30, "Medium"), fill=MUTED)


def _fit_title(draw, title: str, width: float):
    """Largest size (52 down to 34) that fits in two lines, else ellipsise."""
    for size in (52, 46, 40, 34):
        f = font("display", size)
        lines = _wrap(draw, title.upper(), f, width)
        if len(lines) == 1 or (len(lines) == 2 and size <= 46):
            return f, lines
    f = font("display", 34)
    lines = _wrap(draw, title.upper(), f, width)[:2]
    while draw.textlength(lines[-1] + "...", font=f) > width and len(lines[-1]) > 1:
        lines[-1] = lines[-1][:-1]
    lines[-1] = lines[-1].rstrip() + "..."
    return f, lines


def _wrap(draw, text: str, f, width: float) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=f) <= width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def _art(card: Image.Image, draw: ImageDraw.ImageDraw, art: Image.Image, accent) -> None:
    box = (PAD + 36, 236, W - PAD - 36, 236 + 702)
    size = (box[2] - box[0], box[3] - box[1])
    art = art.convert("RGB").resize(size, Image.LANCZOS)
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=18, fill=255)
    card.paste(art, box[:2], mask)
    draw.rounded_rectangle(
        (box[0] - 4, box[1] - 4, box[2] + 4, box[3] + 4), radius=22, outline=accent, width=6
    )


def _type_bar(draw: ImageDraw.ImageDraw, stats: CardStats, accent) -> None:
    y = 966
    pill_font = font("display", 26)
    x = PAD + 36
    for text, fill, ink in (
        (stats.card_type.upper(), accent, PANEL),
        (stats.language.upper(), PANEL_LIGHT, INK),
    ):
        tw = draw.textlength(text, font=pill_font)
        draw.rounded_rectangle((x, y, x + tw + 40, y + 48), radius=24, fill=fill)
        draw.text((x + 20, y + 9), text, font=pill_font, fill=ink)
        x += tw + 56

    rarity_font = font("mono", 24, "Bold")
    label = stats.rarity.upper()
    right = W - PAD - 36
    stars = RARITY_STARS.get(stats.rarity, 1)
    star_x = right - stars * 30
    for i in range(stars):
        cx, cy = star_x + i * 30 + 12, y + 24
        draw.polygon([(cx, cy - 12), (cx + 10, cy), (cx, cy + 12), (cx - 10, cy)], fill=accent)
    lw = draw.textlength(label, font=rarity_font)
    draw.text((star_x - lw - 16, y + 10), label, font=rarity_font, fill=accent)


def _abilities(draw: ImageDraw.ImageDraw, stats: CardStats, accent) -> None:
    y = 1044
    left, right = PAD + 36, W - PAD - 36
    name_font = font("display", 32)
    value_font = font("mono", 34, "Bold")
    for ability in stats.abilities[:3]:
        draw.line((left, y, right, y), fill=PANEL_LIGHT, width=2)
        draw.text((left, y + 18), ability.name, font=name_font, fill=INK)
        vw = draw.textlength(ability.value, font=value_font)
        draw.text((right - vw, y + 18), ability.value, font=value_font, fill=accent)
        y += 72
    draw.line((left, y, right, y), fill=PANEL_LIGHT, width=2)


def chip_style(kind: str, accent) -> tuple[tuple, tuple, str | None]:
    """Return (fill, ink, tag) for a crew chip of the given kind."""
    if kind == "agent":
        return accent, PANEL, "AI"
    if kind == "bot":
        return BOT, PANEL, "BOT"
    return HUMAN, INK, None


def _crew(draw: ImageDraw.ImageDraw, stats: CardStats, accent) -> None:
    y = 1276
    x = PAD + 36
    draw.text((x, y + 14), "CREW", font=font("mono", 22, "Bold"), fill=MUTED)
    x += 96
    chip_font = font("body", 26, "Bold")
    tag_font = font("mono", 16, "ExtraBold")
    shown = stats.crew[:5]
    right = W - PAD - 36
    shown_count = 0
    for member in shown:
        label = member.name if len(member.name) <= 14 else member.name[:13] + "."
        tw = draw.textlength(label, font=chip_font)
        fill, ink, tag = chip_style(member.kind, accent)
        extra = TAG_WIDTHS[tag] + 10 if tag else 0
        width = tw + 36 + extra
        if x + width > right - 70:
            break
        draw.rounded_rectangle((x, y, x + width, y + 50), radius=25, fill=fill)
        draw.text((x + 18, y + 10), label, font=chip_font, fill=ink)
        if tag:
            tx = x + 18 + tw + 8
            tag_w = TAG_WIDTHS[tag]
            draw.rounded_rectangle((tx, y + 14, tx + tag_w, y + 36), radius=6, fill=PANEL)
            draw.text((tx + 5, y + 15), tag, font=tag_font, fill=fill)
        x += width + 12
        shown_count += 1
    hidden = len(stats.crew) - shown_count
    if hidden > 0:
        draw.text((x + 4, y + 10), f"+{hidden}", font=chip_font, fill=MUTED)


def _footer(draw: ImageDraw.ImageDraw, stats: CardStats) -> None:
    flavor_font = font("body", 30, "Light")
    text = f"“{stats.flavor}”"
    tw = draw.textlength(text, font=flavor_font)
    draw.text(((W - tw) / 2, 1368), text, font=flavor_font, fill=INK)

    meta_font = font("mono", 20, "Medium")
    status = "MERGED" if stats.merged else "OPEN"
    left = f"@{stats.author}  ·  {status} {stats.year}"
    right = "SHIP-IT-CARD"
    draw.text((PAD + 36, 1424), left, font=meta_font, fill=MUTED)
    rw = draw.textlength(right, font=meta_font)
    draw.text((W - PAD - 36 - rw, 1424), right, font=meta_font, fill=MUTED)
