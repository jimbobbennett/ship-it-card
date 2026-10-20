"""GitHub Enterprise host support across the github, CLI and web layers (no network)."""

import httpx
import pytest
from fastapi.testclient import TestClient

from shipit import __main__ as cli
from shipit import github, web
from shipit.art import procedural_art
from shipit.card import card_png
from shipit.core import Card
from shipit.github import BadPRUrl, PRRef, fetch_pr, parse_pr_url, validate_host
from shipit.stats import CardStats, build_stats

# --- github layer ---


def test_parse_ghe_url():
    ref = parse_pr_url("https://ghe.example.com/o/r/pull/5", host="ghe.example.com")
    assert ref == PRRef("o", "r", 5)
    assert parse_pr_url("https://GHE.Example.com/o/r/pull/5", host="ghe.EXAMPLE.com") == ref


def test_host_url_mismatch_rejected():
    with pytest.raises(BadPRUrl):
        parse_pr_url("https://github.com/o/r/pull/5", host="ghe.example.com")
    with pytest.raises(BadPRUrl):
        parse_pr_url("https://ghe.example.com/o/r/pull/5")
    with pytest.raises(BadPRUrl):
        parse_pr_url("https://ghe.example.com.evil.com/o/r/pull/5", host="ghe.example.com")


@pytest.mark.parametrize(
    "host",
    [
        "evil.com/x",
        "a@b.com",
        "https://x.com",
        "x.com#",
        "x y",
        "x.com?a",
        "a\\b",
        "",
        "-x.com",
        "x" * 300,
        "x.com/",
        "x.com:abc",
        "x.com:0",
        "x.com:00000",
        "x.com:65536",
        "x.com:99999",
    ],
)
def test_validate_host_rejects(host):
    with pytest.raises(BadPRUrl):
        validate_host(host)


@pytest.mark.parametrize(
    "host",
    ["ghe.example.com", "ghe.example.com:8443", "x.com:1", "x.com:65535", "localhost"],
)
def test_validate_host_accepts(host):
    assert validate_host(host) == host


def _capture(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        path = request.url.path
        return httpx.Response(200, json=[] if path.endswith(("commits", "reviews")) else {})

    real = httpx.Client
    monkeypatch.setattr(
        github.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )
    return requests


def test_fetch_pr_default_and_ghe_urls(monkeypatch):
    requests = _capture(monkeypatch)
    fetch_pr(PRRef("o", "r", 5))
    assert {r.url.host for r in requests} == {"api.github.com"}
    assert requests[0].url.path == "/repos/o/r/pulls/5"
    requests.clear()
    fetch_pr(PRRef("o", "r", 5), host="ghe.example.com")
    assert {r.url.host for r in requests} == {"ghe.example.com"}
    assert requests[0].url.path == "/api/v3/repos/o/r/pulls/5"


def test_tokens(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "gh-secret")
    monkeypatch.delenv("GHE_TOKEN", raising=False)
    requests = _capture(monkeypatch)
    fetch_pr(PRRef("o", "r", 5))
    assert requests[0].headers["authorization"] == "Bearer gh-secret"
    requests.clear()
    fetch_pr(PRRef("o", "r", 5), host="ghe.example.com")
    assert all("authorization" not in r.headers for r in requests)
    monkeypatch.setenv("GHE_TOKEN", "ghe-secret")
    requests.clear()
    fetch_pr(PRRef("o", "r", 5), host="ghe.example.com")
    assert requests[0].headers["authorization"] == "Bearer ghe-secret"


def test_make_card_passes_host(monkeypatch, pr_data):
    from shipit import core

    seen = {}
    monkeypatch.setattr(core, "parse_pr_url", lambda url, host=None: seen.setdefault("p", host))
    monkeypatch.setattr(core, "fetch_pr", lambda ref, host=None: seen.setdefault("f", host))
    monkeypatch.setattr(core, "build_stats", lambda data, show_bots=False: build_stats(pr_data))
    monkeypatch.setattr(core, "get_art", lambda stats, use_gemini=True: (b"", "procedural"))
    monkeypatch.setattr(core, "card_png", lambda stats, art: b"png")
    core.make_card("u", host="ghe.example.com")
    assert seen == {"p": "ghe.example.com", "f": "ghe.example.com"}


# --- CLI ---


def _fake_card():
    stats = CardStats("o/r#1", "t", "o/r", 1, "a", "Python", "", "Feature", True, 1, 1, 1, 1, 0,
                      None, 10, "Common")  # fmt: skip
    return Card(stats, b"png", "procedural")


def test_host_flag_passed(monkeypatch, tmp_path):
    seen = {}

    def fake(url, use_gemini=True, show_bots=False, host=None):
        seen["host"] = host
        return _fake_card()

    monkeypatch.setattr(cli, "make_card", fake)
    out = str(tmp_path / "c.png")
    argv = ["--host", "ghe.example.com", "https://ghe.example.com/o/r/pull/1", "-o", out]
    assert cli.main(argv) == 0
    assert seen["host"] == "ghe.example.com"
    assert cli.main(["https://github.com/o/r/pull/1", "-o", out]) == 0
    assert seen["host"] is None


@pytest.mark.parametrize(
    "argv",
    [
        ["--host", "evil.com/x", "https://github.com/o/r/pull/1"],
        ["--host", "ghe.example.com", "https://github.com/o/r/pull/1"],
    ],
)
def test_bad_host_is_argparse_error(argv, monkeypatch):
    def no_network(**kw):
        raise AssertionError("network")

    monkeypatch.setattr("shipit.github.httpx.Client", no_network)
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
    assert exc.value.code == 2


def test_host_in_help(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    assert "--host" in capsys.readouterr().out


# --- web ---


def _host_client(monkeypatch, pr_data):
    stats = build_stats(pr_data)
    card = Card(stats, card_png(stats, procedural_art(stats.slug, stats.rarity)), "procedural")
    calls = []

    def fake(url, show_bots=False, host=None):
        calls.append(host)
        return card

    monkeypatch.setattr(web, "make_card", fake)
    monkeypatch.setenv("GHE_HOSTS", "ghe.example.com, Other.Example.com,ghe.example.com:8443")
    web._cache.clear()
    return TestClient(web.app), calls


def test_host_passed_cached_per_host_and_img_src(monkeypatch, pr_data):
    client, calls = _host_client(monkeypatch, pr_data)
    params = {"url": "https://ghe.example.com/o/r/pull/1"}
    client.get("/card.png", params={**params, "host": "ghe.example.com"})
    client.get("/card.png", params={**params, "host": "ghe.example.com"})  # cached
    client.get("/card.png", params={**params, "host": "other.example.com"})
    assert calls == ["ghe.example.com", "other.example.com"]
    page = client.get("/card", params={**params, "host": "ghe.example.com:8443"}).text
    assert "&host=ghe.example.com%3A8443" in page


def test_bad_host(monkeypatch, pr_data):
    client, calls = _host_client(monkeypatch, pr_data)
    params = {"url": "https://github.com/o/r/pull/1", "host": "<b>evil.com/x"}
    assert client.get("/card.png", params=params).status_code == 400
    page = client.get("/card", params=params)
    assert page.status_code == 200
    assert "<b>" not in page.text
    assert "valid GitHub host" in page.text
    assert calls == []


def test_unlisted_host_rejected(monkeypatch, pr_data):
    client, calls = _host_client(monkeypatch, pr_data)
    params = {"url": "https://internal.corp/o/r/pull/1", "host": "internal.corp"}
    assert client.get("/card.png", params=params).status_code == 400
    assert "not allowed" in client.get("/card", params=params).text
    assert calls == []


def test_no_allowlist_rejects_all_hosts(monkeypatch, pr_data):
    client, calls = _host_client(monkeypatch, pr_data)
    monkeypatch.delenv("GHE_HOSTS")
    params = {"url": "https://ghe.example.com/o/r/pull/1", "host": "ghe.example.com"}
    assert client.get("/card.png", params=params).status_code == 400
    assert calls == []
