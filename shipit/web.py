"""Web app: paste a PR URL, get a card. Run with `uvicorn shipit.web:app`."""

from __future__ import annotations

import html
import os
from urllib.parse import quote

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, Response

from .core import Card, make_card
from .github import BadPRUrl, validate_host

app = FastAPI(title="ship-it-card")
_cache: dict[tuple[str, bool, str | None], Card] = {}


def allowed_hosts() -> set[str]:
    """Trusted GHE hosts for the web app, from the comma-separated GHE_HOSTS env var."""
    raw = os.environ.get("GHE_HOSTS", "")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ship-it-card</title>
<style>
  body {{ margin: 0; min-height: 100vh; display: grid; place-items: center;
         background: #0b0c14; color: #f4f5fa; font: 18px/1.5 system-ui, sans-serif; }}
  main {{ width: min(560px, 92vw); text-align: center; padding: 48px 0; }}
  h1 {{ font-size: 44px; margin: 0 0 4px; letter-spacing: -1px; }}
  p {{ color: #969cb4; margin: 0 0 28px; }}
  form {{ display: flex; gap: 8px; }}
  input {{ flex: 1; padding: 14px 16px; border-radius: 12px; border: 1px solid #2a2e45;
           background: #11131f; color: inherit; font-size: 16px; }}
  button {{ padding: 14px 22px; border: 0; border-radius: 12px; background: #ffc440;
            font-weight: 700; font-size: 16px; cursor: pointer; }}
  img {{ width: 100%; margin-top: 32px; border-radius: 28px; }}
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
    return PAGE.format(value="", body="")


@app.get("/card", response_class=HTMLResponse)
def card_page(
    url: str = Query(..., max_length=300),
    show_bots: bool = False,
    host: str | None = Query(None, max_length=300),
) -> str:
    safe = html.escape(url, quote=True)
    try:
        card = _get_card(url, show_bots, host)
    except HTTPException as exc:
        return PAGE.format(value=safe, body=f'<div class="err">{html.escape(exc.detail)}</div>')
    alt = html.escape(f"Ship-it card for {card.stats.slug}", quote=True)
    extra = "&show_bots=true" if show_bots else ""
    if host is not None:
        extra += f"&host={quote(host, safe='')}"
    img = f'<img src="/card.png?url={quote(url, safe="")}{extra}" alt="{alt}">'
    return PAGE.format(value=safe, body=img)


@app.get("/card.png")
def card_image(
    url: str = Query(..., max_length=300),
    show_bots: bool = False,
    host: str | None = Query(None, max_length=300),
) -> Response:
    card = _get_card(url, show_bots, host)
    return Response(card.png, media_type="image/png")


def _get_card(url: str, show_bots: bool = False, host: str | None = None) -> Card:
    if host is not None:
        try:
            host = validate_host(host)
        except BadPRUrl as exc:
            raise HTTPException(400, "That doesn't look like a valid GitHub host.") from exc
        if host not in allowed_hosts():
            raise HTTPException(400, "That GitHub host is not allowed.")
    key = (url, show_bots, host)
    if key in _cache:
        return _cache[key]
    try:
        if host is None:
            card = make_card(url, show_bots=show_bots)
        else:
            card = make_card(url, show_bots=show_bots, host=host)
    except BadPRUrl as exc:
        raise HTTPException(400, "That doesn't look like a GitHub pull request URL.") from exc
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        message = "PR not found." if status == 404 else f"GitHub returned {status}."
        raise HTTPException(502, message) from exc
    _cache[key] = card
    return card
