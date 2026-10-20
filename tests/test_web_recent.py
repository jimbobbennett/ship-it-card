from fastapi.testclient import TestClient

from shipit import web
from shipit.core import Card
from shipit.stats import build_stats


def test_styled_card_not_in_gallery(monkeypatch, pr_data):
    stats = build_stats(pr_data)
    monkeypatch.setattr(
        web, "make_card", lambda url, show_bots=False, style=None: Card(stats, b"\x89PNG", "x")
    )
    web._cache.clear()
    web._recent.clear()
    client = TestClient(web.app)
    url = "https://github.com/o/r/pull/1"
    client.get("/card", params={"url": url, "style": "pixel"})
    assert not web._recent
    client.get("/card", params={"url": url})
    assert len(web._recent) == 1
