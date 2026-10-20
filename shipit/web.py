"""Web app: paste a PR URL, get a card. Run with `uvicorn shipit.web:app`."""

from __future__ import annotations

import html
import os
from collections import deque
from urllib.parse import quote
from xml.sax.saxutils import escape as xml_escape

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response

from .card import RARITY_COLOURS
from .core import FLAVOR_MAX, Card, make_card, normalize_flavor
from .github import BadPRUrl, validate_host

app = FastAPI(title="ship-it-card")
_cache: dict[tuple[str, bool, str | None, str | None], Card] = {}
RECENT_LIMIT = 20
# Newest last; one entry per (url, show_bots, host). Metadata only, shared by all visitors.
_recent: deque[dict] = deque(maxlen=RECENT_LIMIT)


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ship-it-card</title>
{head}<style>
  body {{ margin: 0; min-height: 100vh; display: grid; place-items: center;
         background: #0b0c14; color: #f4f5fa; font: 18px/1.5 system-ui, sans-serif; }}
  main {{ width: min(960px, 92vw); text-align: center; padding: 48px 0; }}
  h1 {{ font-size: 44px; margin: 0 0 4px; letter-spacing: -1px; }}
  p {{ color: #969cb4; margin: 0 0 28px; }}
  form {{ display: flex; gap: 8px; max-width: 560px; margin: 0 auto; }}
  input {{ flex: 1; padding: 14px 16px; border-radius: 12px; border: 1px solid #2a2e45;
           background: #11131f; color: inherit; font-size: 16px; }}
  button {{ padding: 14px 22px; border: 0; border-radius: 12px; background: #ffc440;
            font-weight: 700; font-size: 16px; cursor: pointer; }}
  table.score {{ width: 100%; margin-top: 24px; border-collapse: collapse; font-size: 15px;
                text-align: left; }}
  table.score caption {{ color: #969cb4; text-align: left; padding-bottom: 6px; }}
  table.score th, table.score td {{ padding: 6px 8px; border-bottom: 1px solid #2a2e45; }}
  table.score .pts {{ text-align: right; }}
  main > img {{ display: block; width: 100%; max-width: 560px; margin: 32px auto 0;
               border-radius: 28px; }}
  .gallery {{ display: grid; gap: 20px; margin-top: 40px; text-align: left;
              grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); }}
  .gallery a {{ color: inherit; text-decoration: none; }}
  .gallery img {{ width: 100%; height: auto; display: block; border-radius: 14px; }}
  .gallery .t {{ font-size: 15px; font-weight: 600; margin-top: 8px; overflow-wrap: anywhere; }}
  .gallery .r {{ font-size: 13px; color: #969cb4; overflow-wrap: anywhere; }}
  .err {{ color: #ff8a8a; margin-top: 20px; }}
</style></head>
<body><main>
  <h1>ship-it-card</h1>
  <p>Every merged PR deserves a trading card.</p>
  <form action="/card" method="get">
    <input name="url" placeholder="https://github.com/owner/repo/pull/123" value="{value}" required>
    <button type="submit">Ship it</button>
  </form>
  {body}
</main></body></html>"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return PAGE.format(value="", body=_gallery(), head="")


def _gallery() -> str:
    if not _recent:
        return ""
    tiles = []
    for entry in reversed(_recent):
        q = quote(entry["url"], safe="")
        extra = "&show_bots=true" if entry["show_bots"] else ""
        if entry.get("host") is not None:
            extra += f"&host={quote(entry['host'], safe='')}"
        title = html.escape(entry["title"], quote=True)
        repo = html.escape(entry["repo"], quote=True)
        tiles.append(
            f'<a href="/card?url={q}{extra}">'
            f'<img src="/card.png?url={q}{extra}" alt="{title}" loading="lazy">'
            f'<div class="t">{title}</div><div class="r">{repo}</div></a>'
        )
    return '<div class="gallery">' + "".join(tiles) + "</div>"


@app.get("/card", response_class=HTMLResponse)
def card_page(
    request: Request,
    url: str = Query(..., max_length=300),
    show_bots: bool = False,
    host: str | None = Query(None, max_length=300),
    flavor: str | None = Query(None, max_length=FLAVOR_MAX),
) -> str:
    safe = html.escape(url, quote=True)
    try:
        card = _get_card(url, show_bots, host, flavor)
    except HTTPException as exc:
        return PAGE.format(
            value=safe, body=f'<div class="err">{html.escape(exc.detail)}</div>', head=""
        )
    alt = html.escape(f"Ship-it card for {card.stats.slug}", quote=True)
    extra = "&show_bots=true" if show_bots else ""
    if host is not None:
        extra += f"&host={quote(host, safe='')}"
    custom = normalize_flavor(flavor)
    if custom is not None:
        extra += f"&flavor={quote(custom, safe='')}"
    query = f"url={quote(url, safe='')}{extra}"
    img = f'<img src="/card.png?{query}" alt="{alt}">'
    text = f'<p class="flavor">{html.escape(custom)}</p>' if custom is not None else ""
    base = str(request.base_url)
    head = _og_tags(card, f"{base}card?{query}", f"{base}card.png?{query}")
    return PAGE.format(value=safe, body=img + text + _breakdown_html(card), head=head)


def _og_tags(card: Card, page_url: str, image_url: str) -> str:
    stats = card.stats
    title = f"{stats.title} · {stats.slug}"
    description = f"{stats.rarity} · Ship score {stats.ship_score} — {stats.title}"
    values = [
        ("property", "og:title", title),
        ("property", "og:description", description),
        ("property", "og:image", image_url),
        ("property", "og:type", "website"),
        ("property", "og:url", page_url),
        ("name", "twitter:card", "summary_large_image"),
        ("name", "twitter:title", title),
        ("name", "twitter:description", description),
        ("name", "twitter:image", image_url),
    ]
    return "".join(
        f'<meta {attr}="{key}" content="{html.escape(value, quote=True)}">\n'
        for attr, key, value in values
    )


def _breakdown_html(card: Card) -> str:
    breakdown = card.stats.score_breakdown
    if breakdown is None:
        return ""
    rows = "".join(
        f"<tr><td>{html.escape(line.label)}</td><td>{html.escape(line.value)}</td>"
        f'<td class="pts">{line.points:+d}</td></tr>'
        for line in breakdown.lines
    )
    return (
        '<table class="score"><caption>How this score was calculated</caption>'
        '<tr><th>Factor</th><th>Value</th><th class="pts">Points</th></tr>'
        f'{rows}<tr><th colspan="2">Total</th><th class="pts">{breakdown.total}</th></tr></table>'
    )


@app.get("/card.png")
def card_image(
    url: str = Query(..., max_length=300),
    show_bots: bool = False,
    host: str | None = Query(None, max_length=300),
    flavor: str | None = Query(None, max_length=FLAVOR_MAX),
) -> Response:
    card = _get_card(url, show_bots, host, flavor)
    return Response(card.png, media_type="image/png")


BADGE_MAX_TITLE = 40
BADGE_MAX_AGE = 600


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _text_width(text: str) -> int:
    """Deterministic rough width (px) at ~11px Verdana."""
    return round(sum(4 if c in "iljtfI.,:;'|! " else 8 if c in "mwMW" else 6.5 for c in text)) + 10


def _badge_svg(repo: str, title: str, rarity: str, score: int) -> str:
    if len(title) > BADGE_MAX_TITLE:
        title = title[: BADGE_MAX_TITLE - 1].rstrip() + "…"
    label = f"{repo} · {title}"
    message = f"{rarity} {score}"
    fill = _hex(RARITY_COLOURS.get(rarity, RARITY_COLOURS["Common"]))
    lw, mw = _text_width(label), _text_width(message)
    full = xml_escape(f"{label}: {message}", {'"': "&quot;"})
    lab, msg = xml_escape(label), xml_escape(message)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{lw + mw}" height="20" '
        f'role="img" aria-label="{full}">'
        f"<title>{xml_escape(f'{label}: {message}')}</title>"
        f'<rect width="{lw}" height="20" fill="#555"/>'
        f'<rect x="{lw}" width="{mw}" height="20" fill="{fill}"/>'
        '<g font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11" '
        'text-anchor="middle">'
        f'<text x="{lw / 2}" y="14" fill="#fff">{lab}</text>'
        f'<text x="{lw + mw / 2}" y="14" fill="#111">{msg}</text>'
        "</g></svg>"
    )


@app.get("/badge.svg")
def badge(url: str = Query(..., max_length=300)) -> Response:
    stats = _get_card(url).stats
    svg = _badge_svg(stats.repo, stats.title, stats.rarity, stats.ship_score)
    return Response(
        svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": f"public, max-age={BADGE_MAX_AGE}"},
    )


def _allowed_hosts() -> set[str]:
    """Hosts permitted via ?host=, from SHIPIT_ALLOWED_HOSTS (comma-separated).

    Deny by default: with the variable unset, no custom host is accepted, so the web app
    can't be used for SSRF or to leak GHE_TOKEN to an arbitrary host.
    """
    raw = os.environ.get("SHIPIT_ALLOWED_HOSTS", "")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def _get_card(
    url: str, show_bots: bool = False, host: str | None = None, flavor: str | None = None
) -> Card:
    try:
        custom = normalize_flavor(flavor)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if host is not None:
        try:
            host = validate_host(host)
        except BadPRUrl as exc:
            raise HTTPException(400, "That doesn't look like a valid GitHub host.") from exc
        if host not in _allowed_hosts():
            raise HTTPException(400, "That GitHub host is not allowed on this server.")
    key = (url, show_bots, host, custom)
    if key in _cache:
        return _cache[key]
    try:
        kwargs: dict = {} if host is None else {"host": host}
        if custom is not None:
            kwargs["flavor"] = custom
        card = make_card(url, show_bots=show_bots, **kwargs)
    except BadPRUrl as exc:
        raise HTTPException(400, "That doesn't look like a GitHub pull request URL.") from exc
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        message = "PR not found." if status == 404 else f"GitHub returned {status}."
        raise HTTPException(502, message) from exc
    _cache[key] = card
    if custom is None:  # custom flavours don't create extra gallery entries
        _record(url, show_bots, card, host)
    return card


def _record(url: str, show_bots: bool, card: Card, host: str | None = None) -> None:
    for entry in list(_recent):
        if (entry["url"], entry["show_bots"], entry.get("host")) == (url, show_bots, host):
            _recent.remove(entry)
    _recent.append(
        {
            "url": url,
            "show_bots": show_bots,
            "host": host,
            "title": card.stats.title,
            "repo": card.stats.slug.split("#", 1)[0],
        }
    )
