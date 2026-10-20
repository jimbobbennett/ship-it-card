"""Render a CardStats + artwork into a trading-card PNG."""

from __future__ import annotations

import colorsys
import io
import math
import random
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .stats import CardStats

FONTS = Path(__file__).parent / "fonts"

Colour = tuple[int, int, int]
# (font family key, size, variation weight name or None)
FontSpec = tuple[str, int, "str | None"]


@dataclass(frozen=True)
class Theme:
    """Every layout number, colour and font used by the card renderer."""

    # Canvas and general spacing.
    w: int = 1080
    h: int = 1512
    pad: int = 36
    inset: int = 36  # content inset from the panel edge (applied on top of pad)

    # Colours.
    panel: Colour = (17, 19, 31)
    panel_light: Colour = (32, 35, 54)
    ink: Colour = (244, 245, 250)
    muted: Colour = (150, 156, 180)
    human: Colour = (70, 76, 104)
    bot: Colour = (224, 122, 72)
    rarity_colours: Mapping[str, Colour] = field(
        default_factory=lambda: {
            "Common": (168, 178, 193),
            "Uncommon": (84, 214, 160),
            "Rare": (88, 160, 255),
            "Epic": (190, 110, 255),
            "Legendary": (255, 196, 64),
        }
    )
    rarity_stars: Mapping[str, int] = field(
        default_factory=lambda: {"Common": 1, "Uncommon": 2, "Rare": 3, "Epic": 4, "Legendary": 5}
    )
    # Tag text -> tag box width, for chips that carry a tag.
    tag_widths: Mapping[str, int] = field(default_factory=lambda: {"AI": 30, "BOT": 44})

    # Fonts.
    font_dir: Path = FONTS
    font_files: Mapping[str, str] = field(
        default_factory=lambda: {
            "display": "Bungee-Regular.ttf",
            "body": "SpaceGrotesk.ttf",
            "mono": "JetBrainsMono.ttf",
        }
    )

    # Frame.
    border_radius: int = 56
    panel_radius: int = 34
    sparkle_edge_extra: int = 20

    # Header.
    score_font: FontSpec = ("mono", 76, "ExtraBold")
    score_y: int = 62
    score_label_font: FontSpec = ("mono", 22, "Bold")
    score_label_y: int = 92
    score_label_dx: int = 70
    title_gap: int = 90
    title_font: str = "display"
    title_sizes: tuple[int, ...] = (52, 46, 40, 34)
    title_two_line_max: int = 46
    title_y_single: int = 64
    title_y_double: int = 54
    title_line_gap: int = 6
    sub_font: FontSpec = ("body", 30, "Medium")
    sub_y: int = 174
    sub_stars_dx: int = 28
    sub_gap: int = 16
    header_star_step: int = 34
    header_star_half: int = 14
    header_star_cy: int = 192
    header_star_outer: int = 14
    header_star_inner: int = 6

    # Art.
    art_y: int = 236
    art_height: int = 702
    art_radius: int = 18
    art_outline_radius: int = 22
    art_outline_pad: int = 4
    art_outline_width: int = 6

    # Type bar.
    type_bar_y: int = 966
    pill_font: FontSpec = ("display", 26, None)
    pill_height: int = 48
    pill_radius: int = 24
    pill_pad: int = 20
    pill_gap: int = 16  # extra space between pills beyond 2 * pill_pad
    pill_text_dy: int = 9
    rarity_font: FontSpec = ("mono", 24, "Bold")
    rarity_label_gap: int = 16
    rarity_label_dy: int = 10
    rarity_star_step: int = 30
    rarity_star_dx: int = 12
    rarity_star_cy: int = 24
    rarity_star_half_w: int = 10
    rarity_star_half_h: int = 12

    # Abilities.
    abilities_y: int = 1044
    abilities_step: int = 72
    abilities_max: int = 3
    abilities_text_dy: int = 18
    abilities_line_width: int = 2
    ability_name_font: FontSpec = ("display", 32, None)
    ability_value_font: FontSpec = ("mono", 34, "Bold")

    # Crew.
    crew_y: int = 1276
    crew_label: str = "CREW"
    crew_label_font: FontSpec = ("mono", 22, "Bold")
    crew_label_dy: int = 14
    crew_label_width: int = 96
    crew_chip_font: FontSpec = ("body", 26, "Bold")
    crew_tag_font: FontSpec = ("mono", 16, "ExtraBold")
    crew_max: int = 5
    crew_name_max: int = 14
    crew_chip_pad: int = 36
    crew_tag_extra: int = 10
    crew_chip_height: int = 50
    crew_chip_radius: int = 25
    crew_text_dx: int = 18
    crew_text_dy: int = 10
    crew_tag_gap: int = 8
    crew_tag_top: int = 14
    crew_tag_bottom: int = 36
    crew_tag_radius: int = 6
    crew_tag_text_dx: int = 5
    crew_tag_text_dy: int = 15
    crew_chip_gap: int = 12
    crew_right_reserve: int = 70
    crew_more_dx: int = 4
    crew_more_dy: int = 10

    # Footer.
    flavor_font: FontSpec = ("body", 30, "Light")
    flavor_min_size: int = 12
    flavor_y: int = 1368
    meta_font: FontSpec = ("mono", 20, "Medium")
    meta_y: int = 1424

    @property
    def left(self) -> int:
        return self.pad + self.inset

    @property
    def right(self) -> int:
        return self.w - self.pad - self.inset


DEFAULT_THEME = Theme()

# Legacy module-level aliases, derived from the default theme.
W, H = DEFAULT_THEME.w, DEFAULT_THEME.h
PAD = DEFAULT_THEME.pad
RARITY_COLOURS = DEFAULT_THEME.rarity_colours
RARITY_STARS = DEFAULT_THEME.rarity_stars
PANEL = DEFAULT_THEME.panel
PANEL_LIGHT = DEFAULT_THEME.panel_light
INK = DEFAULT_THEME.ink
MUTED = DEFAULT_THEME.muted
HUMAN = DEFAULT_THEME.human
BOT = DEFAULT_THEME.bot
TAG_WIDTHS = DEFAULT_THEME.tag_widths


@lru_cache(maxsize=32)
def _load_font(path: str, size: int, weight: str | None) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(path, size)
    if weight:
        try:
            f.set_variation_by_name(weight)
        except (OSError, ValueError):
            pass
    return f


def font(theme: Theme, name: str, size: int, weight: str | None = None) -> ImageFont.FreeTypeFont:
    return _load_font(str(theme.font_dir / theme.font_files[name]), size, weight)


def _spec(theme: Theme, spec: FontSpec, size: int | None = None) -> ImageFont.FreeTypeFont:
    name, default_size, weight = spec
    return font(theme, name, default_size if size is None else size, weight)


def render_card(stats: CardStats, art: Image.Image, theme: Theme | None = None) -> Image.Image:
    theme = theme or DEFAULT_THEME
    accent = theme.rarity_colours.get(stats.rarity, theme.rarity_colours["Common"])
    card = Image.new("RGBA", (theme.w, theme.h), (0, 0, 0, 0))
    _frame(card, stats, accent, theme)
    draw = ImageDraw.Draw(card)

    _header(draw, stats, accent, theme)
    _art(card, draw, art, accent, theme)
    _type_bar(draw, stats, accent, theme)
    _abilities(draw, stats, accent, theme)
    _crew(draw, stats, accent, theme)
    _footer(draw, stats, theme)
    return card


def _rarity_level(stats: CardStats, theme: Theme | None = None) -> int:
    colours = (theme or DEFAULT_THEME).rarity_colours
    return list(colours).index(stats.rarity) if stats.rarity in colours else 0


def _mix(a, b, t: float) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _rounded_mask(box, radius: int, theme: Theme) -> Image.Image:
    mask = Image.new("L", (theme.w, theme.h), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=radius, fill=255)
    return mask


def _frame(card: Image.Image, stats: CardStats, accent, theme: Theme) -> None:
    """Draw the decorated border and panel; all of it sits behind the card content."""
    W, H, PAD = theme.w, theme.h, theme.pad
    level = _rarity_level(stats, theme)
    rng = random.Random(f"{stats.repo}#{stats.number}")
    panel_box = (PAD, PAD, W - PAD, H - PAD)

    # Border: diagonal sheen bands derived from the accent colour.
    dark, light = _mix(accent, (0, 0, 0), 0.45), _mix(accent, (255, 255, 255), 0.55)
    border = Image.new("RGB", (W, H), accent)
    bd = ImageDraw.Draw(border)
    period = 90 + 30 * (4 - level)
    for d in range(0, W + H, 3):
        t = abs(((d % period) / period) * 2 - 1)
        colour = _mix(dark, light, t)
        if level >= 3:  # holo hue drift for Epic / Legendary
            hue, sat, val = colorsys.rgb_to_hsv(*(c / 255 for c in colour))
            hue = (hue + 0.12 * (d / (W + H))) % 1.0
            colour = tuple(round(c * 255) for c in colorsys.hsv_to_rgb(hue, sat, val))
        bd.line((d, 0, d - H, H), fill=colour, width=4)
    card.paste(border, (0, 0), _rounded_mask((0, 0, W - 1, H - 1), theme.border_radius, theme))

    # Panel: dark base with a faint diagonal pattern.
    panel = Image.new("RGB", (W, H), theme.panel)
    pd = ImageDraw.Draw(panel)
    grid = _mix(theme.panel, accent, 0.07)
    for d in range(0, W + H, 28):
        pd.line((d, 0, d - H, H), fill=grid, width=2)
    card.paste(panel, (0, 0), _rounded_mask(panel_box, theme.panel_radius, theme))

    # Glossy shine band, wider and brighter for rarer cards.
    shine = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    band = 40 + 30 * level
    start = rng.randint(300, 700)
    ImageDraw.Draw(shine).polygon(
        [(start, 0), (start + band, 0), (start + band - H // 2, H), (start - H // 2, H)],
        fill=(255, 255, 255, 10 + 5 * level),
    )
    clip = _rounded_mask(panel_box, theme.panel_radius, theme)
    shine.putalpha(Image.composite(shine.getchannel("A"), Image.new("L", (W, H), 0), clip))
    card.alpha_composite(shine)

    # Sparkles along the frame and panel gutters; more of them for rarer cards.
    sparkles = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    spd = ImageDraw.Draw(sparkles)
    for _ in range((0, 4, 8, 16, 28)[level]):
        side = rng.randrange(4)
        along = rng.randint(70, (W if side < 2 else H) - 70)
        edge = rng.randint(10, PAD + theme.sparkle_edge_extra)
        if side == 0:
            cx, cy = along, edge
        elif side == 1:
            cx, cy = along, H - edge
        elif side == 2:
            cx, cy = edge, along
        else:
            cx, cy = W - edge, along
        _sparkle(spd, cx, cy, rng.randint(6, 10 + 3 * level), level)
    card.alpha_composite(sparkles)


def _sparkle(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int, level: int) -> None:
    k = max(2, r // 4)
    points = [
        (cx, cy - r),
        (cx + k, cy - k),
        (cx + r, cy),
        (cx + k, cy + k),
        (cx, cy + r),
        (cx - k, cy + k),
        (cx - r, cy),
        (cx - k, cy - k),
    ]
    draw.polygon(points, fill=(255, 255, 255, 235))
    if level >= 3:  # extra diagonal glints on Epic / Legendary
        d = r // 2 + 1
        draw.line((cx - d, cy - d, cx + d, cy + d), fill=(255, 255, 255, 150), width=2)
        draw.line((cx - d, cy + d, cx + d, cy - d), fill=(255, 255, 255, 150), width=2)


def _header_stars(draw: ImageDraw.ImageDraw, stats: CardStats, accent, theme: Theme) -> None:
    """Rarity stars drawn as polygons, right-aligned under the score."""
    count = theme.rarity_stars.get(stats.rarity, 1)
    right = theme.right
    for i in range(count):
        cx = right - theme.header_star_half - (count - 1 - i) * theme.header_star_step
        cy = theme.header_star_cy
        pts = []
        for j in range(10):
            ang = -math.pi / 2 + j * math.pi / 5
            rad = theme.header_star_outer if j % 2 == 0 else theme.header_star_inner
            pts.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
        draw.polygon(pts, fill=accent)


def card_png(stats: CardStats, art: Image.Image, theme: Theme | None = None) -> bytes:
    buffer = io.BytesIO()
    render_card(stats, art, theme).save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _header(draw: ImageDraw.ImageDraw, stats: CardStats, accent, theme: Theme) -> None:
    score_font = _spec(theme, theme.score_font)
    label_font = _spec(theme, theme.score_label_font)
    score = str(stats.ship_score)
    score_w = draw.textlength(score, font=score_font)
    right, left = theme.right, theme.left
    draw.text((right - score_w, theme.score_y), score, font=score_font, fill=accent)
    draw.text(
        (right - score_w - theme.score_label_dx, theme.score_label_y),
        "SHIP",
        font=label_font,
        fill=theme.muted,
    )

    title_space = right - score_w - theme.title_gap - left
    title_font, lines = _fit_title(draw, stats.title, title_space, theme)
    y = theme.title_y_single if len(lines) == 1 else theme.title_y_double
    for line in lines:
        draw.text((left, y), line, font=title_font, fill=theme.ink)
        y += title_font.size + theme.title_line_gap

    sub = f"{stats.repo}  #{stats.number}"
    sub_font = _spec(theme, theme.sub_font)
    stars = theme.rarity_stars.get(stats.rarity, 1)
    stars_left = (
        right - theme.sub_stars_dx - (stars - 1) * theme.header_star_step - theme.header_star_half
    )
    sub_space = stars_left - theme.sub_gap - left
    if draw.textlength(sub, font=sub_font) > sub_space:
        # Keep the repo text clear of the star row by ellipsizing the repo name.
        suffix = f"...  #{stats.number}"
        repo = stats.repo
        while repo and draw.textlength(repo + suffix, font=sub_font) > sub_space:
            repo = repo[:-1]
        sub = repo + suffix
    draw.text((left, theme.sub_y), sub, font=sub_font, fill=theme.muted)
    _header_stars(draw, stats, accent, theme)


def _fit_title(draw, title: str, width: float, theme: Theme):
    """Largest size (first of title_sizes) that fits in two lines, else ellipsise."""
    for size in theme.title_sizes:
        f = font(theme, theme.title_font, size)
        lines = _wrap(draw, title.upper(), f, width)
        if len(lines) == 1 or (len(lines) == 2 and size <= theme.title_two_line_max):
            return f, lines
    f = font(theme, theme.title_font, theme.title_sizes[-1])
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


def _art(
    card: Image.Image, draw: ImageDraw.ImageDraw, art: Image.Image, accent, theme: Theme
) -> None:
    box = (theme.left, theme.art_y, theme.right, theme.art_y + theme.art_height)
    size = (box[2] - box[0], box[3] - box[1])
    art = art.convert("RGB").resize(size, Image.LANCZOS)
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size[0] - 1, size[1] - 1), radius=theme.art_radius, fill=255
    )
    card.paste(art, box[:2], mask)
    o = theme.art_outline_pad
    draw.rounded_rectangle(
        (box[0] - o, box[1] - o, box[2] + o, box[3] + o),
        radius=theme.art_outline_radius,
        outline=accent,
        width=theme.art_outline_width,
    )


def _type_bar(draw: ImageDraw.ImageDraw, stats: CardStats, accent, theme: Theme) -> None:
    y = theme.type_bar_y
    pill_font = _spec(theme, theme.pill_font)
    x = theme.left
    pad = theme.pill_pad
    for text, fill, ink in (
        (stats.card_type.upper(), accent, theme.panel),
        (stats.language.upper(), theme.panel_light, theme.ink),
    ):
        tw = draw.textlength(text, font=pill_font)
        draw.rounded_rectangle(
            (x, y, x + tw + 2 * pad, y + theme.pill_height), radius=theme.pill_radius, fill=fill
        )
        draw.text((x + pad, y + theme.pill_text_dy), text, font=pill_font, fill=ink)
        x += tw + 2 * pad + theme.pill_gap

    rarity_font = _spec(theme, theme.rarity_font)
    label = stats.rarity.upper()
    right = theme.right
    stars = theme.rarity_stars.get(stats.rarity, 1)
    step = theme.rarity_star_step
    star_x = right - stars * step
    hw, hh = theme.rarity_star_half_w, theme.rarity_star_half_h
    for i in range(stars):
        cx, cy = star_x + i * step + theme.rarity_star_dx, y + theme.rarity_star_cy
        draw.polygon([(cx, cy - hh), (cx + hw, cy), (cx, cy + hh), (cx - hw, cy)], fill=accent)
    lw = draw.textlength(label, font=rarity_font)
    draw.text(
        (star_x - lw - theme.rarity_label_gap, y + theme.rarity_label_dy),
        label,
        font=rarity_font,
        fill=accent,
    )


def _abilities(draw: ImageDraw.ImageDraw, stats: CardStats, accent, theme: Theme) -> None:
    y = theme.abilities_y
    left, right = theme.left, theme.right
    name_font = _spec(theme, theme.ability_name_font)
    value_font = _spec(theme, theme.ability_value_font)
    lw = theme.abilities_line_width
    dy = theme.abilities_text_dy
    for ability in stats.abilities[: theme.abilities_max]:
        draw.line((left, y, right, y), fill=theme.panel_light, width=lw)
        draw.text((left, y + dy), ability.name, font=name_font, fill=theme.ink)
        vw = draw.textlength(ability.value, font=value_font)
        draw.text((right - vw, y + dy), ability.value, font=value_font, fill=accent)
        y += theme.abilities_step
    draw.line((left, y, right, y), fill=theme.panel_light, width=lw)


def chip_style(kind: str, accent, theme: Theme | None = None) -> tuple[tuple, tuple, str | None]:
    """Return (fill, ink, tag) for a crew chip of the given kind."""
    theme = theme or DEFAULT_THEME
    if kind == "agent":
        return accent, theme.panel, "AI"
    if kind == "bot":
        return theme.bot, theme.panel, "BOT"
    return theme.human, theme.ink, None


def _crew(draw: ImageDraw.ImageDraw, stats: CardStats, accent, theme: Theme) -> None:
    y = theme.crew_y
    x = theme.left
    draw.text(
        (x, y + theme.crew_label_dy),
        theme.crew_label,
        font=_spec(theme, theme.crew_label_font),
        fill=theme.muted,
    )
    x += theme.crew_label_width
    chip_font = _spec(theme, theme.crew_chip_font)
    tag_font = _spec(theme, theme.crew_tag_font)
    shown = stats.crew[: theme.crew_max]
    right = theme.right
    shown_count = 0
    for member in shown:
        name_max = theme.crew_name_max
        label = member.name if len(member.name) <= name_max else member.name[: name_max - 1] + "."
        tw = draw.textlength(label, font=chip_font)
        fill, ink, tag = chip_style(member.kind, accent, theme)
        extra = theme.tag_widths[tag] + theme.crew_tag_extra if tag else 0
        width = tw + theme.crew_chip_pad + extra
        if x + width > right - theme.crew_right_reserve:
            break
        draw.rounded_rectangle(
            (x, y, x + width, y + theme.crew_chip_height), radius=theme.crew_chip_radius, fill=fill
        )
        draw.text((x + theme.crew_text_dx, y + theme.crew_text_dy), label, font=chip_font, fill=ink)
        if tag:
            tx = x + theme.crew_text_dx + tw + theme.crew_tag_gap
            tag_w = theme.tag_widths[tag]
            draw.rounded_rectangle(
                (tx, y + theme.crew_tag_top, tx + tag_w, y + theme.crew_tag_bottom),
                radius=theme.crew_tag_radius,
                fill=theme.panel,
            )
            draw.text(
                (tx + theme.crew_tag_text_dx, y + theme.crew_tag_text_dy),
                tag,
                font=tag_font,
                fill=fill,
            )
        x += width + theme.crew_chip_gap
        shown_count += 1
    hidden = len(stats.crew) - shown_count
    if hidden > 0:
        draw.text(
            (x + theme.crew_more_dx, y + theme.crew_more_dy),
            f"+{hidden}",
            font=chip_font,
            fill=theme.muted,
        )


def _footer(draw: ImageDraw.ImageDraw, stats: CardStats, theme: Theme) -> None:
    flavor_font = _spec(theme, theme.flavor_font)
    text = f"“{stats.flavor}”"
    size = theme.flavor_font[1]
    while draw.textlength(text, font=flavor_font) > theme.w - 2 * theme.pad and (
        size > theme.flavor_min_size
    ):
        size -= 1
        flavor_font = _spec(theme, theme.flavor_font, size)
    tw = draw.textlength(text, font=flavor_font)
    draw.text(((theme.w - tw) / 2, theme.flavor_y), text, font=flavor_font, fill=theme.ink)

    meta_font = _spec(theme, theme.meta_font)
    status = "MERGED" if stats.merged else "OPEN"
    left = f"@{stats.author}  ·  {status} {stats.year}"
    right = "SHIP-IT-CARD"
    draw.text((theme.left, theme.meta_y), left, font=meta_font, fill=theme.muted)
    rw = draw.textlength(right, font=meta_font)
    draw.text((theme.right - rw, theme.meta_y), right, font=meta_font, fill=theme.muted)
