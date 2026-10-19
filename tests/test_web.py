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
    monkeypatch.setattr(web, "make_card", lambda url: card)
    web._cache.clear()
    response = TestClient(web.app).get("/card.png", params={"url": "https://github.com/o/r/pull/1"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"


def test_bad_url_shows_friendly_error():
    web._cache.clear()
    response = TestClient(web.app).get("/card", params={"url": "<script>alert(1)</script>"})
    assert response.status_code == 200
    assert "<script>alert(1)</script>" not in response.text
    assert "pull request URL" in response.text
