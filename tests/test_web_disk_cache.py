import hashlib

import httpx
import pytest
from fastapi.testclient import TestClient

from shipit import web
from shipit.art import procedural_art
from shipit.card import card_png
from shipit.core import Card
from shipit.github import BadPRUrl
from shipit.stats import build_stats

URL = "https://github.com/octo/widgets/pull/42"


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    d = tmp_path / "disk"
    monkeypatch.setenv("SHIPIT_CARD_CACHE_DIR", str(d))
    monkeypatch.setenv("SHIPIT_ALLOWED_HOSTS", "ghe.example.com,other.example.com")
    web._cache.clear()
    return d


@pytest.fixture
def calls(monkeypatch, pr_data):
    made = []

    def fake(url, show_bots=False, host=None):
        made.append((url, show_bots, host))
        stats = build_stats(pr_data)
        return Card(stats, card_png(stats, procedural_art(stats.slug, stats.rarity)), "procedural")

    monkeypatch.setattr(web, "make_card", fake)
    return made


def test_persists_across_restart(cache_dir, calls):
    client = TestClient(web.app)
    first = client.get("/card.png", params={"url": URL})
    assert first.status_code == 200
    assert len(list(cache_dir.glob("*.png"))) == 1
    web._cache.clear()
    second = client.get("/card.png", params={"url": URL})
    assert second.content == first.content
    assert second.headers["content-type"] == "image/png"
    assert len(calls) == 1


def test_variants_get_separate_files(cache_dir, calls):
    client = TestClient(web.app)
    client.get("/card.png", params={"url": URL})
    client.get("/card.png", params={"url": URL, "show_bots": "true"})
    client.get("/card.png", params={"url": URL, "host": "ghe.example.com"})
    client.get("/card.png", params={"url": URL, "host": "other.example.com"})
    assert len(list(cache_dir.glob("*.png"))) == 4
    assert len(calls) == 4


def test_malicious_url_stays_in_cache_dir(cache_dir, calls):
    client = TestClient(web.app)
    for bad in ("../../etc/passwd", "a/b/../../../x", "/abs/path"):
        client.get("/card.png", params={"url": bad})
    files = list(cache_dir.rglob("*"))
    assert files and all(f.parent == cache_dir for f in files)
    assert all(len(f.stem) == 64 and f.suffix == ".png" for f in files)


@pytest.mark.parametrize("junk", [b"", b"not a png"])
def test_corrupt_cache_is_rerendered(cache_dir, calls, junk):
    client = TestClient(web.app)
    client.get("/card.png", params={"url": URL})
    (path,) = cache_dir.glob("*.png")
    path.write_bytes(junk)
    web._cache.clear()
    response = client.get("/card.png", params={"url": URL})
    assert response.status_code == 200
    assert response.content.startswith(web.PNG_MAGIC)
    assert len(calls) == 2
    assert path.read_bytes() == response.content


def test_unwritable_cache_dir_still_serves(tmp_path, monkeypatch, calls):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setenv("SHIPIT_CARD_CACHE_DIR", str(blocker / "sub"))
    web._cache.clear()
    response = TestClient(web.app).get("/card.png", params={"url": URL})
    assert response.status_code == 200
    assert response.content.startswith(web.PNG_MAGIC)


def test_unreadable_cache_file_still_serves(cache_dir, calls, monkeypatch):
    def boom(self):
        raise OSError("nope")

    monkeypatch.setattr(web.Path, "read_bytes", boom)
    web._cache.clear()
    assert TestClient(web.app).get("/card.png", params={"url": URL}).status_code == 200


def test_default_dir_and_hashed_name(monkeypatch):
    monkeypatch.delenv("SHIPIT_CARD_CACHE_DIR", raising=False)
    assert web._card_cache_dir() == web.Path(".cache/cards")
    path = web._card_cache_path("../x", False, None)
    assert path.parent == web.Path(".cache/cards")
    assert path.name == hashlib.sha256(repr(("../x", False, None)).encode()).hexdigest() + ".png"


def test_errors_write_nothing(cache_dir, monkeypatch):
    client = TestClient(web.app)

    def bad(url, show_bots=False, host=None):
        raise BadPRUrl("bad")

    def upstream(url, show_bots=False, host=None):
        request = httpx.Request("GET", "https://api.github.com/x")
        raise httpx.HTTPStatusError("x", request=request, response=httpx.Response(404))

    monkeypatch.setattr(web, "make_card", bad)
    assert client.get("/card.png", params={"url": URL}).status_code == 400
    monkeypatch.setattr(web, "make_card", upstream)
    assert client.get("/card.png", params={"url": URL}).status_code == 502
    assert client.get("/card.png", params={"url": URL, "host": "evil.com"}).status_code == 400
    assert client.get("/card.png", params={"url": URL, "host": "bad host!"}).status_code == 400
    assert not cache_dir.exists() or list(cache_dir.iterdir()) == []


def test_no_temp_files_left(cache_dir, calls):
    TestClient(web.app).get("/card.png", params={"url": URL})
    assert [p.suffix for p in cache_dir.iterdir()] == [".png"]
