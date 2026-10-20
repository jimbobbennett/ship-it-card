"""One call from PR URL to finished card, shared by the CLI and the web app."""

from __future__ import annotations

from dataclasses import dataclass

from .art import get_art
from .card import card_png
from .github import fetch_pr, parse_pr_url
from .stats import CardStats, build_stats


@dataclass
class Card:
    stats: CardStats
    png: bytes
    art_source: str


def make_stats(url: str, show_bots: bool = False, host: str | None = None) -> CardStats:
    """Stats only: no art generation and no rendering."""
    ref = parse_pr_url(url, host=host)
    pr = fetch_pr(ref) if host is None else fetch_pr(ref, host=host)
    return build_stats(pr, show_bots=show_bots)


def make_card(
    url: str, use_gemini: bool = True, show_bots: bool = False, host: str | None = None
) -> Card:
    stats = make_stats(url, show_bots=show_bots, host=host)
    art, source = get_art(stats, use_gemini=use_gemini)
    return Card(stats=stats, png=card_png(stats, art), art_source=source)
