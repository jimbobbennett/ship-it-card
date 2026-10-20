"""One call from PR URL to finished card, shared by the CLI and the web app."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, replace

from .art import get_art
from .card import card_png
from .github import fetch_pr, parse_pr_url
from .stats import CardStats, build_stats

FLAVOR_MAX = 80


def normalize_flavor(flavor: str | None) -> str | None:
    """Clean custom flavour text; None if unset/blank. Raises ValueError if over FLAVOR_MAX."""
    if flavor is None:
        return None
    cleaned = "".join(
        " " if unicodedata.category(c).startswith("C") or c.isspace() else c for c in flavor
    ).strip()
    if not cleaned:
        return None
    if len(cleaned) > FLAVOR_MAX:
        raise ValueError(f"flavor must be at most {FLAVOR_MAX} characters")
    return cleaned


@dataclass
class Card:
    stats: CardStats
    png: bytes
    art_source: str


def make_stats(
    url: str, show_bots: bool = False, host: str | None = None, flavor: str | None = None
) -> CardStats:
    """Stats only: no art generation and no rendering."""
    ref = parse_pr_url(url, host=host)
    pr = fetch_pr(ref) if host is None else fetch_pr(ref, host=host)
    stats = build_stats(pr, show_bots=show_bots)
    custom = normalize_flavor(flavor)
    return stats if custom is None else replace(stats, flavor=custom)


def make_card(
    url: str,
    use_gemini: bool = True,
    show_bots: bool = False,
    host: str | None = None,
    flavor: str | None = None,
) -> Card:
    stats = make_stats(url, show_bots=show_bots, host=host, flavor=flavor)
    art, source = get_art(stats, use_gemini=use_gemini)
    return Card(stats=stats, png=card_png(stats, art), art_source=source)
