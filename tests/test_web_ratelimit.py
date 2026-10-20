import pytest
from fastapi.testclient import TestClient

from shipit import web
from shipit.art import procedural_art
from shipit.card import card_png
from shipit.core import Card
from shipit.github import BadPRUrl
from shipit.stats import build_stats

URL = "https://github.com/octo/widgets/pull/42"
LIMIT = 3


@pytest.fixture
def calls(monkeypatch, pr_data):
    web._cache.clear()
    monkeypatch.setenv("SHIPIT_RATE_LIMIT", str(LIMIT))
    made = []

    def fake(url, show_bots=False, **kwargs):
        if "bad" in url:
            raise BadPRUrl(url)
        made.append(url)
        stats = build_stats(pr_data)
        return Card(stats, card_png(stats, procedural_art(stats.slug, stats.rarity)), "procedural")

    monkeypatch.setattr(web, "make_card", fake)
    return made


@pytest.fixture
def clock(monkeypatch):
    t = [1000.0]
    monkeypatch.setattr(web, "_now", lambda: t[0])
    return t


def client(ip="1.2.3.4"):
    return TestClient(web.app, client=(ip, 5000))


def u(n):
    return f"https://github.com/octo/widgets/pull/{n}"


ENDPOINTS = {
    "get_card": lambda c, n: c.get("/card", params={"url": u(n)}),
    "post_card": lambda c, n: c.post("/card", data={"url": u(n)}),
    "post_token": lambda c, n: c.post("/card", data={"url": u(n), "token": "ghp_secret123"}),
    "png": lambda c, n: c.get("/card.png", params={"url": u(n)}),
    "badge": lambda c, n: c.get("/badge.svg", params={"url": u(n)}),
}


@pytest.mark.parametrize("name", ENDPOINTS)
def test_limit_hit_returns_429(calls, clock, name):
    c = client()
    for n in range(LIMIT):
        assert ENDPOINTS[name](c, n).status_code == 200
    r = ENDPOINTS[name](c, 99)
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) == 3600
    assert "too many cards" in r.text
    assert "try again in 60 minutes" in r.text
    assert "ghp_secret123" not in r.text
    assert len(calls) == LIMIT


def test_cache_hits_do_not_count(calls, clock):
    c = client()
    for _ in range(LIMIT * 3):
        assert c.get("/card", params={"url": u(1)}).status_code == 200
        assert c.get("/card.png", params={"url": u(1)}).status_code == 200
    assert len(calls) == 1  # /card.png reuses the in-memory card


def test_png_disk_cache_hits_do_not_count(calls, clock):
    c = client()
    for _ in range(LIMIT * 3):
        assert c.get("/card.png", params={"url": u(1)}).status_code == 200
    assert len(calls) == 1


def test_per_ip_isolation(calls, clock):
    a, b = client("1.1.1.1"), client("2.2.2.2")
    for n in range(LIMIT):
        a.get("/card.png", params={"url": u(n)})
    assert a.get("/card.png", params={"url": u(50)}).status_code == 429
    assert b.get("/card.png", params={"url": u(50)}).status_code == 200


def test_window_expiry_and_rejections_do_not_extend(calls, clock):
    c = client()
    for n in range(LIMIT):
        assert c.get("/card.png", params={"url": u(n)}).status_code == 200
    clock[0] += 3000
    r = c.get("/card.png", params={"url": u(50)})
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) == 600
    clock[0] += 601  # rejection above did not push the window out
    assert c.get("/card.png", params={"url": u(50)}).status_code == 200


def test_xff_ignored_by_default(calls, clock):
    c = client()
    for n in range(LIMIT):
        c.get("/card.png", params={"url": u(n)}, headers={"X-Forwarded-For": f"9.9.9.{n}"})
    r = c.get("/card.png", params={"url": u(50)}, headers={"X-Forwarded-For": "8.8.8.8"})
    assert r.status_code == 429


def test_xff_honoured_with_trusted_hop(calls, clock, monkeypatch):
    monkeypatch.setenv("SHIPIT_TRUSTED_PROXY_HOPS", "1")
    c = client("10.0.0.1")  # the proxy
    for n in range(LIMIT):
        h = {"X-Forwarded-For": "spoofed, 7.7.7.7"}
        assert c.get("/card.png", params={"url": u(n)}, headers=h).status_code == 200
    h = {"X-Forwarded-For": "other-spoof, 7.7.7.7"}
    assert c.get("/card.png", params={"url": u(50)}, headers=h).status_code == 429
    h = {"X-Forwarded-For": "7.7.7.8"}
    assert c.get("/card.png", params={"url": u(50)}, headers=h).status_code == 200


def test_xff_missing_or_short_falls_back(calls, clock, monkeypatch):
    monkeypatch.setenv("SHIPIT_TRUSTED_PROXY_HOPS", "2")
    c = client("10.0.0.1")
    for n in range(LIMIT):
        c.get("/card.png", params={"url": u(n)}, headers={"X-Forwarded-For": "5.5.5.5"})
    assert c.get("/card.png", params={"url": u(50)}).status_code == 429


def test_limit_can_be_disabled(calls, clock, monkeypatch):
    monkeypatch.setenv("SHIPIT_RATE_LIMIT", "0")
    c = client()
    for n in range(LIMIT * 3):
        assert c.get("/card.png", params={"url": u(n)}).status_code == 200


def test_invalid_env_falls_back_to_defaults(monkeypatch):
    monkeypatch.setenv("SHIPIT_RATE_LIMIT", "lots")
    monkeypatch.setenv("SHIPIT_RATE_WINDOW", "-5")
    monkeypatch.setenv("SHIPIT_TRUSTED_PROXY_HOPS", "x")
    assert web._rate_limit() == web.DEFAULT_RATE_LIMIT
    assert web._rate_window() == web.DEFAULT_RATE_WINDOW
    assert web._env_int("SHIPIT_TRUSTED_PROXY_HOPS", 0, 0) == 0


def test_invalid_input_does_not_count(calls, clock, monkeypatch):
    monkeypatch.setenv("SHIPIT_ALLOWED_HOSTS", "ghe.example.com")
    c = client()
    for _ in range(LIMIT * 2):
        assert (
            c.get("/card.png", params={"url": u(1), "host": "nope.example.com"}).status_code == 400
        )
        assert c.get("/card.png", params={"url": "https://bad.example/bad"}).status_code == 400
        assert c.post("/card", data={"url": u(1), "token": "bad\ntoken"}).status_code == 400
    assert c.get("/card.png", params={"url": u(1)}).status_code == 200
    assert calls == [u(1)]


def test_limiter_table_is_bounded(clock, monkeypatch):
    monkeypatch.setattr(web, "_RATE_MAX_IPS", 5)
    for i in range(50):
        web._limiter.charge(f"ip{i}", 3, 3600)
    assert len(web._limiter._hits) <= 6
    clock[0] += 4000
    web._limiter.charge("fresh", 3, 3600)
    assert list(web._limiter._hits) == ["fresh"]
