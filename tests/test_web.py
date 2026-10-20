import dataclasses

from fastapi.testclient import TestClient

from shipit import web
from shipit.art import procedural_art
from shipit.card import card_png
from shipit.core import Card
from shipit.stats import build_stats


def test_index():
    assert "ship-it-card" in TestClient(web.app).get("/").text


def test_card_png(monkeypatch, pr_data):
    stats = build_stats(pr_data)
    card = Card(stats, card_png(stats, procedural_art(stats.slug, stats.rarity)), "procedural")
    monkeypatch.setattr(web, "make_card", lambda url, show_bots=False: card)
    web._cache.clear()
    response = TestClient(web.app).get("/card.png", params={"url": "https://github.com/o/r/pull/1"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"


def test_show_bots_cache_and_img_src(monkeypatch, pr_data):
    stats = build_stats(pr_data)
    card = Card(stats, card_png(stats, procedural_art(stats.slug, stats.rarity)), "procedural")
    calls = []

    def fake(url, show_bots=False):
        calls.append(show_bots)
        return card

    monkeypatch.setattr(web, "make_card", fake)
    web._cache.clear()
    client = TestClient(web.app)
    params = {"url": "https://github.com/o/r/pull/1"}
    client.get("/card.png", params=params)
    client.get("/card.png", params={**params, "show_bots": "true"})
    client.get("/card.png", params=params)  # cached
    client.get("/card.png", params={**params, "show_bots": "true"})  # cached
    assert calls == [False, True]

    off = client.get("/card", params=params).text
    on = client.get("/card", params={**params, "show_bots": "true"}).text
    assert "show_bots" not in off
    assert "&show_bots=true" in on


def test_bad_url_shows_friendly_error():
    web._cache.clear()
    response = TestClient(web.app).get("/card", params={"url": "<script>alert(1)</script>"})
    assert response.status_code == 200
    assert "<script>alert(1)</script>" not in response.text
    assert "pull request URL" in response.text


def _fake_card(pr_data, title=None):
    stats = build_stats(pr_data)
    if title is not None:
        stats = dataclasses.replace(stats, title=title)
    return Card(stats, b"png", "procedural")


def _reset():
    web._cache.clear()
    web._recent.clear()


def test_empty_home_has_no_gallery():
    _reset()
    text = TestClient(web.app).get("/").text
    assert '<div class="gallery">' not in text
    assert "<form" in text and "ship-it-card" in text


def test_card_appears_on_home(monkeypatch, pr_data):
    _reset()
    card = _fake_card(pr_data)
    monkeypatch.setattr(web, "make_card", lambda url, show_bots=False: card)
    client = TestClient(web.app)
    url = "https://github.com/o/r/pull/1"
    q = "https%3A%2F%2Fgithub.com%2Fo%2Fr%2Fpull%2F1"
    client.get("/card", params={"url": url})
    text = client.get("/").text
    assert f'<a href="/card?url={q}">' in text
    assert f'src="/card.png?url={q}"' in text
    assert 'loading="lazy"' in text
    assert card.stats.title in text
    assert card.stats.slug.split("#")[0] in text
    client.get("/card", params={"url": url, "show_bots": "true"})
    assert f'href="/card?url={q}&show_bots=true"' in client.get("/").text
    assert '<div class="gallery">' not in client.get("/card", params={"url": url}).text


def test_order_cap_and_no_duplicates(monkeypatch, pr_data):
    _reset()
    card = _fake_card(pr_data)
    monkeypatch.setattr(web, "make_card", lambda url, show_bots=False: card)
    client = TestClient(web.app)
    for i in range(25):
        client.get("/card.png", params={"url": f"https://github.com/o/r/pull/{i}"})
    client.get("/card.png", params={"url": "https://github.com/o/r/pull/24"})  # repeat
    text = client.get("/").text
    assert text.count('loading="lazy"') == 20
    assert 'pull%2F24"' in text and 'pull%2F5"' in text
    assert 'pull%2F4"' not in text
    assert text.index('pull%2F24"') < text.index('pull%2F23"')
    assert len(web._recent) == 20
    assert len({(e["url"], e["show_bots"]) for e in web._recent}) == 20


def test_repeat_url_not_duplicated(monkeypatch, pr_data):
    _reset()
    card = _fake_card(pr_data)
    monkeypatch.setattr(web, "make_card", lambda url, show_bots=False: card)
    client = TestClient(web.app)
    for _ in range(3):
        client.get("/card", params={"url": "https://github.com/o/r/pull/1"})
    assert len(web._recent) == 1


def test_failed_lookup_not_recorded(monkeypatch):
    _reset()

    def boom(url, show_bots=False):
        raise web.BadPRUrl("nope")

    monkeypatch.setattr(web, "make_card", boom)
    TestClient(web.app).get("/card", params={"url": "https://example.com/x"})
    assert not web._recent
    assert 'loading="lazy"' not in TestClient(web.app).get("/").text


def test_title_is_escaped(monkeypatch, pr_data):
    _reset()
    card = _fake_card(pr_data, title="<script>alert(1)</script>")
    monkeypatch.setattr(web, "make_card", lambda url, show_bots=False: card)
    client = TestClient(web.app)
    client.get("/card.png", params={"url": "https://github.com/o/r/pull/1"})
    text = client.get("/").text
    assert "<script>alert(1)</script>" not in text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text
