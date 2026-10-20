"""Web app: paste a PR URL, get a card. Run with `uvicorn shipit.web:app`."""

from __future__ import annotations

import html
from collections import deque
from urllib.parse import quote

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, Response

from .core import Card, make_card
from .github import BadPRUrl

app = FastAPI(title="ship-it-card")
_cache: dict[tuple[str, bool], Card] = {}
RECENT_LIMIT = 20
# Newest last; one entry per (url, show_bots). Metadata only, shared by all visitors.
_recent: deque[dict] = deque(maxlen=RECENT_LIMIT)

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ship-it-card</title>
<style>
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
    return PAGE.format(value="", body=_gallery())


def _gallery() -> str:
    if not _recent:
        return ""
    tiles = []
    for entry in reversed(_recent):
        q = quote(entry["url"], safe="")
        extra = "&show_bots=true" if entry["show_bots"] else ""
        title = html.escape(entry["title"], quote=True)
        repo = html.escape(entry["repo"], quote=True)
        tiles.append(
            f'<a href="/card?url={q}{extra}">'
            f'<img src="/card.png?url={q}{extra}" alt="{title}" loading="lazy">'
            f'<div class="t">{title}</div><div class="r">{repo}</div></a>'
        )
    return '<div class="gallery">' + "".join(tiles) + "</div>"


@app.get("/card", response_class=HTMLResponse)
def card_page(url: str = Query(..., max_length=300), show_bots: bool = False) -> str:
    safe = html.escape(url, quote=True)
    try:
        card = _get_card(url, show_bots)
    except HTTPException as exc:
        return PAGE.format(value=safe, body=f'<div class="err">{html.escape(exc.detail)}</div>')
    alt = html.escape(f"Ship-it card for {card.stats.slug}", quote=True)
    extra = "&show_bots=true" if show_bots else ""
    img = f'<img src="/card.png?url={quote(url, safe="")}{extra}" alt="{alt}">'
    return PAGE.format(value=safe, body=img)


@app.get("/card.png")
def card_image(url: str = Query(..., max_length=300), show_bots: bool = False) -> Response:
    card = _get_card(url, show_bots)
    return Response(card.png, media_type="image/png")


def _get_card(url: str, show_bots: bool = False) -> Card:
    key = (url, show_bots)
    if key in _cache:
        return _cache[key]
    try:
        card = make_card(url, show_bots=show_bots)
    except BadPRUrl as exc:
        raise HTTPException(400, "That doesn't look like a GitHub pull request URL.") from exc
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        message = "PR not found." if status == 404 else f"GitHub returned {status}."
        raise HTTPException(502, message) from exc
    _cache[key] = card
    _record(url, show_bots, card)
    return card


def _record(url: str, show_bots: bool, card: Card) -> None:
    for entry in list(_recent):
        if (entry["url"], entry["show_bots"]) == (url, show_bots):
            _recent.remove(entry)
    _recent.append(
        {
            "url": url,
            "show_bots": show_bots,
            "title": card.stats.title,
            "repo": card.stats.slug.split("#", 1)[0],
        }
    )
