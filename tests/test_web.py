import dataclasses
import html
import re
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from shipit import web
from shipit.art import procedural_art
from shipit.card import card_png
from shipit.core import Card
from shipit.stats import build_stats


def test_index():
    assert "ship-it-card" in TestClient(web.app).get("/").text


def _host_card(pr_data):
    stats = build_stats(pr_data)
    return Card(stats, card_png(stats, procedural_art(stats.slug, stats.rarity)), "procedural")


def test_host_rejected_unless_allowlisted(monkeypatch, pr_data):
    calls = []

    def fake(url, show_bots=False, host=None):
        calls.append(host)
        return _host_card(pr_data)

    monkeypatch.setattr(web, "make_card", fake)
    monkeypatch.delenv("SHIPIT_ALLOWED_HOSTS", raising=False)
    web._cache.clear()
    client = TestClient(web.app)
    url = "https://localhost/o/r/pull/1"
    for host in ("localhost", "127.0.0.1", "evil.example.com"):
        response = client.get("/card.png", params={"url": url, "host": host})
        assert response.status_code == 400
    assert "not allowed" in client.get("/card", params={"url": url, "host": "localhost"}).text
    assert calls == []


def test_allowlisted_host_and_cache_key(monkeypatch, pr_data):
    calls = []

    def fake(url, show_bots=False, host=None):
        calls.append(host)
        return _host_card(pr_data)

    monkeypatch.setattr(web, "make_card", fake)
    monkeypatch.setenv("SHIPIT_ALLOWED_HOSTS", "Ghe.Example.com, other.example.com")
    web._cache.clear()
    client = TestClient(web.app)
    url = "https://ghe.example.com/o/r/pull/1"
    for host in ("ghe.example.com", "GHE.example.com", "other.example.com"):
        assert client.get("/card.png", params={"url": url, "host": host}).status_code == 200
    assert calls == ["ghe.example.com", "other.example.com"]
    page = client.get("/card", params={"url": url, "host": "ghe.example.com"}).text
    assert "host=ghe.example.com" in page


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


def test_card_page_shows_breakdown(monkeypatch, pr_data):
    stats = build_stats(pr_data)
    card = Card(stats, card_png(stats, procedural_art(stats.slug, stats.rarity)), "procedural")
    monkeypatch.setattr(web, "make_card", lambda url, show_bots=False: card)
    web._cache.clear()
    client = TestClient(web.app)
    text = client.get("/card", params={"url": "https://github.com/o/r/pull/1"}).text
    assert text.index("<img") < text.index("How this score was calculated")
    for line in stats.score_breakdown.lines:
        assert line.label in text and line.value in text and f"{line.points:+d}" in text
    assert f'<th class="pts">{stats.ship_score}</th>' in text
    assert "How this score" not in client.get("/").text
    monkeypatch.undo()
    web._cache.clear()
    bad = client.get("/card", params={"url": "nope"}).text
    assert "pull request URL" in bad
    assert "How this score" not in bad


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


def _badge_card(monkeypatch, pr_data, calls=None, **overrides):
    from dataclasses import replace

    stats = replace(build_stats(pr_data), **overrides)
    card = Card(stats, b"", "procedural")

    def fake(url, show_bots=False):
        if calls is not None:
            calls.append(url)
        return card

    monkeypatch.setattr(web, "make_card", fake)
    web._cache.clear()
    return stats


BADGE_URL = {"url": "https://github.com/o/r/pull/1"}


def test_badge_ok_and_cache(monkeypatch, pr_data):
    from xml.etree import ElementTree

    calls = []
    stats = _badge_card(monkeypatch, pr_data, calls, rarity="Rare", ship_score=72)
    client = TestClient(web.app)
    response = client.get("/badge.svg", params=BADGE_URL)
    client.get("/badge.svg", params=BADGE_URL)
    assert len(calls) == 1
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert response.headers["cache-control"].startswith("public, max-age=")
    root = ElementTree.fromstring(response.text)
    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    assert root.get("width") and root.get("height")
    assert stats.repo in root.get("aria-label")
    assert "Rare 72" in response.text
    assert "#58a0ff" in response.text


def test_badge_colours_all_rarities(monkeypatch, pr_data):
    client = TestClient(web.app)
    fills = {}
    for name in ["Common", "Uncommon", "Rare", "Epic", "Legendary", "Mythic"]:
        _badge_card(monkeypatch, pr_data, rarity=name)
        fills[name] = client.get("/badge.svg", params=BADGE_URL).text
    colours = {n: web._hex(web.RARITY_COLOURS[n]) for n in web.RARITY_COLOURS}
    assert len(set(colours.values())) == 5
    for name, colour in colours.items():
        assert f'fill="{colour}"' in fills[name]
    assert f'fill="{colours["Common"]}"' in fills["Mythic"]


def test_badge_escapes_and_truncates(monkeypatch, pr_data):
    from xml.etree import ElementTree

    _badge_card(monkeypatch, pr_data, title='<script>alert(1)</script> & "x"' + "y" * 80)
    text = TestClient(web.app).get("/badge.svg", params=BADGE_URL).text
    assert "<script>" not in text
    assert "…" in text
    ElementTree.fromstring(text)


def test_badge_errors():
    web._cache.clear()
    client = TestClient(web.app)
    response = client.get("/badge.svg", params={"url": "<script>x</script>"})
    assert response.status_code == 400
    assert "<script>" not in response.text
    assert client.get("/badge.svg").status_code == 422


def _flavor_env(monkeypatch, pr_data):
    base = build_stats(pr_data)
    calls = []

    def fake(url, show_bots=False, flavor=None):
        calls.append(flavor)
        stats = base if flavor is None else dataclasses.replace(base, flavor=flavor)
        return Card(stats, b"\x89PNG" + (flavor or "").encode(), "procedural")

    monkeypatch.setattr(web, "make_card", fake)
    _reset()
    return TestClient(web.app), calls


FLAVOR_URL = "https://github.com/o/r/pull/1"


def _style_env(monkeypatch, pr_data):
    base = build_stats(pr_data)
    calls = []

    def fake(url, show_bots=False, style=None):
        calls.append(style)
        return Card(base, b"\x89PNG" + (style or "").encode(), "procedural")

    monkeypatch.setattr(web, "make_card", fake)
    _reset()
    return TestClient(web.app), calls


@pytest.mark.parametrize("style", ["pixel", "anime", "watercolour", "painterly"])
def test_style_valid(monkeypatch, pr_data, style):
    client, calls = _style_env(monkeypatch, pr_data)
    assert client.get("/card.png", params={"url": FLAVOR_URL, "style": style}).status_code == 200
    page = client.get("/card", params={"url": FLAVOR_URL, "style": style})
    assert page.status_code == 200
    assert calls == [style]
    text = page.text
    assert text.count(f"style={style}") >= 3  # img, og:image/twitter:image, og:url


@pytest.mark.parametrize("style", ["Pixel", "neon", "", "pixel&x=1", "<script>"])
def test_style_invalid(monkeypatch, pr_data, style):
    client, calls = _style_env(monkeypatch, pr_data)
    for path in ("/card", "/card.png"):
        response = client.get(path, params={"url": FLAVOR_URL, "style": style})
        assert 400 <= response.status_code < 500
        assert "<script>" not in response.text
    assert calls == []


def test_no_style_links_have_no_style(monkeypatch, pr_data):
    client, _ = _style_env(monkeypatch, pr_data)
    assert "style=" not in client.get("/card", params={"url": FLAVOR_URL}).text


def test_flavor_png_passed_to_make_card(monkeypatch, pr_data):
    client, calls = _flavor_env(monkeypatch, pr_data)
    response = client.get("/card.png", params={"url": FLAVOR_URL, "flavor": "Hello"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert calls == ["Hello"]


def test_flavor_cache_keys_are_separate(monkeypatch, pr_data):
    client, calls = _flavor_env(monkeypatch, pr_data)
    a = client.get("/card.png", params={"url": FLAVOR_URL, "flavor": "A"}).content
    b = client.get("/card.png", params={"url": FLAVOR_URL, "flavor": "B"}).content
    plain = client.get("/card.png", params={"url": FLAVOR_URL}).content
    empty = client.get("/card.png", params={"url": FLAVOR_URL, "flavor": "  "}).content
    assert a.endswith(b"A") and b.endswith(b"B") and plain == b"\x89PNG"
    assert empty == plain
    assert client.get("/card.png", params={"url": FLAVOR_URL, "flavor": "A"}).content == a
    assert calls == ["A", "B", None]


def test_flavor_page_text_and_img_src(monkeypatch, pr_data):
    client, _ = _flavor_env(monkeypatch, pr_data)
    text = client.get("/card", params={"url": FLAVOR_URL, "flavor": "Hello world"}).text
    assert ">Hello world<" in text
    assert "&flavor=Hello%20world" in text
    assert "flavor" not in client.get("/card", params={"url": FLAVOR_URL}).text


def test_flavor_is_escaped(monkeypatch, pr_data):
    client, _ = _flavor_env(monkeypatch, pr_data)
    params = {"url": FLAVOR_URL, "flavor": "<script>alert(1)</script>"}
    text = client.get("/card", params=params).text
    assert "<script>" not in text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text
    assert "&flavor=%3Cscript%3E" in text


def test_flavor_length_limit(monkeypatch, pr_data):
    client, _ = _flavor_env(monkeypatch, pr_data)
    for path in ("/card", "/card.png"):
        assert client.get(path, params={"url": FLAVOR_URL, "flavor": "x" * 81}).status_code == 422
        assert client.get(path, params={"url": FLAVOR_URL, "flavor": "x" * 80}).status_code == 200


def test_flavor_not_added_to_gallery(monkeypatch, pr_data):
    client, _ = _flavor_env(monkeypatch, pr_data)
    client.get("/card.png", params={"url": FLAVOR_URL, "flavor": "A"})
    assert len(web._recent) == 0
    client.get("/card.png", params={"url": FLAVOR_URL})
    client.get("/card.png", params={"url": FLAVOR_URL, "flavor": "B"})
    assert len(web._recent) == 1


OG_URL = "https://github.com/o/r/pull/1"
OG_Q = "url=https%3A%2F%2Fgithub.com%2Fo%2Fr%2Fpull%2F1"


def _meta(text, key):
    m = re.search(rf'<meta (?:property|name)="{key}" content="([^"]*)">', text)
    assert m, key
    return html.unescape(m.group(1))


def test_og_tags_present(monkeypatch, pr_data):
    _reset()
    card = _fake_card(pr_data)
    monkeypatch.setattr(web, "make_card", lambda url, show_bots=False: card)
    text = TestClient(web.app).get("/card", params={"url": OG_URL}).text
    head = text.split("</head>")[0]
    for key in (
        "og:title",
        "og:description",
        "og:image",
        "og:type",
        "og:url",
        "twitter:card",
        "twitter:title",
        "twitter:description",
        "twitter:image",
    ):
        assert f'"{key}"' in head
    assert _meta(text, "twitter:card") == "summary_large_image"
    assert card.stats.title in _meta(text, "og:title")
    assert card.stats.slug in _meta(text, "og:title")
    desc = _meta(text, "og:description")
    assert card.stats.rarity in desc and f"Ship score {card.stats.ship_score}" in desc
    assert _meta(text, "og:image") == f"http://testserver/card.png?{OG_Q}"
    assert _meta(text, "og:url") == f"http://testserver/card?{OG_Q}"
    assert "<title>ship-it-card</title>" in head


def test_og_image_carries_params(monkeypatch, pr_data):
    _reset()
    card = _fake_card(pr_data)
    monkeypatch.setattr(web, "make_card", lambda url, show_bots=False, host=None: card)
    monkeypatch.setenv("SHIPIT_ALLOWED_HOSTS", "ghe.example.com")
    params = {"url": OG_URL, "show_bots": "true", "host": "ghe.example.com"}
    text = TestClient(web.app).get("/card", params=params).text
    expected = f"{OG_Q}&show_bots=true&host=ghe.example.com"
    assert _meta(text, "og:image") == f"http://testserver/card.png?{expected}"
    assert _meta(text, "twitter:image") == f"http://testserver/card.png?{expected}"
    assert _meta(text, "og:url") == f"http://testserver/card?{expected}"


def test_og_tags_escape_hostile_title(monkeypatch, pr_data):
    _reset()
    card = _fake_card(pr_data, title='"><script>alert(1)</script>')
    monkeypatch.setattr(web, "make_card", lambda url, show_bots=False: card)
    text = TestClient(web.app).get("/card", params={"url": OG_URL}).text
    assert "<script>" not in text
    assert "&quot;&gt;&lt;script&gt;" in text.split("</head>")[0]
    assert _meta(text, "og:title").startswith('"><script>')


def test_no_og_tags_on_error_and_index():
    _reset()
    client = TestClient(web.app)
    bad = client.get("/card", params={"url": "nope"}).text
    assert "pull request URL" in bad
    assert "og:" not in bad and "twitter:" not in bad
    assert "og:" not in client.get("/").text


SECRET = "ghp_supersecret123"
PRIVATE_URL = "https://github.com/octo/private/pull/7"
PUBLIC = "https://github.com/octo/widgets/pull/42"


def _token_client(monkeypatch, pr_data, fail_status=None):
    import httpx

    calls = []

    def fake(url, show_bots=False, host=None, token=None):
        calls.append({"url": url, "host": host, "token": token})
        if token is None or fail_status is not None:
            status = fail_status or 404
            request = httpx.Request("GET", "https://api.github.com/x")
            raise httpx.HTTPStatusError(
                "err", request=request, response=httpx.Response(status, request=request)
            )
        return _host_card(pr_data)

    monkeypatch.setattr(web, "make_card", fake)
    monkeypatch.delenv("SHIPIT_ALLOWED_HOSTS", raising=False)
    web._cache.clear()
    web._recent.clear()
    return TestClient(web.app), calls


def test_form_has_password_input_and_posts():
    page = TestClient(web.app).get("/").text
    assert re.search(r'<input type="password" name="token" autocomplete="off"', page)
    assert 'method="post"' in page


def test_post_with_token(monkeypatch, pr_data):
    client, calls = _token_client(monkeypatch, pr_data)
    response = client.post("/card", data={"url": PRIVATE_URL, "token": f" {SECRET} "})
    assert response.status_code == 200
    assert calls == [{"url": PRIVATE_URL, "host": None, "token": SECRET}]
    assert "data:image/png;base64," in response.text
    assert SECRET not in response.text
    assert "/card.png?" not in response.text
    assert "og:" not in response.text and "twitter:" not in response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert not web._cache
    assert not web._recent


def test_tokened_card_not_served_to_others(monkeypatch, pr_data):
    client, calls = _token_client(monkeypatch, pr_data)
    client.post("/card", data={"url": PRIVATE_URL, "token": SECRET})
    response = client.get("/card.png", params={"url": PRIVATE_URL})
    assert response.status_code == 502
    assert calls[-1]["token"] is None
    assert list(web._recent) == []
    assert PRIVATE_URL not in client.get("/").text


def test_token_query_param_ignored(monkeypatch, pr_data):
    client, calls = _token_client(monkeypatch, pr_data)
    for path in ("/card", "/card.png", "/badge.svg"):
        client.get(path, params={"url": PRIVATE_URL, "token": SECRET})
    assert len(calls) == 3 and all(c["token"] is None for c in calls)


def test_blank_token_is_public_flow(monkeypatch, pr_data):
    client, _ = _token_client(monkeypatch, pr_data)
    monkeypatch.setattr(web, "make_card", lambda url, show_bots=False, **kw: _host_card(pr_data))
    response = client.post("/card", data={"url": PUBLIC, "token": "   "})
    assert "/card.png?url=" in response.text
    assert "og:image" in response.text
    assert len(web._recent) == 1 and len(web._cache) == 1
    assert client.get("/card", params={"url": PUBLIC}).status_code == 200


def test_token_error_hides_token(monkeypatch, pr_data):
    for status in (401, 403, 404):
        client, _ = _token_client(monkeypatch, pr_data, fail_status=status)
        response = client.post("/card", data={"url": PRIVATE_URL, "token": SECRET})
        assert SECRET not in response.text
        expected = "PR not found." if status == 404 else f"GitHub returned {status}."
        assert expected in response.text
        assert 'type="password"' in response.text
        assert response.headers["cache-control"] == "private, no-store"


def test_token_with_control_chars_rejected(monkeypatch, pr_data):
    client, calls = _token_client(monkeypatch, pr_data)
    response = client.post("/card", data={"url": PRIVATE_URL, "token": "abc\r\nX-Evil: 1"})
    assert response.status_code == 400
    assert "X-Evil" not in response.text
    assert calls == []


def test_oversized_token_rejected_without_echo(monkeypatch, pr_data):
    client, calls = _token_client(monkeypatch, pr_data)
    big = "S3CR3T" * 200
    assert len(big) > web.TOKEN_MAX
    response = client.post("/card", data={"url": PRIVATE_URL, "token": big})
    assert response.status_code == 400
    assert "S3CR3T" not in response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert calls == []


def test_token_only_sent_to_allowed_host(monkeypatch, pr_data):
    client, calls = _token_client(monkeypatch, pr_data)
    bad = "https://evil.example.com/o/r/pull/1"
    response = client.post("/card", data={"url": bad, "token": SECRET, "host": "evil.example.com"})
    assert "not allowed" in response.text
    assert SECRET not in response.text
    assert calls == []
    monkeypatch.setenv("SHIPIT_ALLOWED_HOSTS", "ghe.example.com")
    good = "https://ghe.example.com/o/r/pull/1"
    client.post("/card", data={"url": good, "token": SECRET, "host": "ghe.example.com"})
    assert calls == [{"url": good, "host": "ghe.example.com", "token": SECRET}]


def _actions_env(monkeypatch, pr_data):
    _reset()
    card = _fake_card(pr_data)
    monkeypatch.setattr(web, "make_card", lambda url, show_bots=False, **kw: card)
    return TestClient(web.app)


def _copy_button(text):
    m = re.search(r'<button type="button" data-url="([^"]*)">Copy link</button>', text)
    return html.unescape(m.group(1)) if m else None


def test_card_page_download_and_copy(monkeypatch, pr_data):
    text = _actions_env(monkeypatch, pr_data).get("/card", params={"url": OG_URL}).text
    img = re.search(r'<img src="([^"]*)"', text).group(1)
    m = re.search(r'<a class="btn" href="([^"]*)" download="([^"]*\.png)">Download PNG</a>', text)
    assert m and m.group(1) == img
    assert _copy_button(text) == _meta(text, "og:url")
    assert "navigator.clipboard.writeText" in text


def test_actions_carry_params(monkeypatch, pr_data):
    client = _actions_env(monkeypatch, pr_data)
    monkeypatch.setenv("SHIPIT_ALLOWED_HOSTS", "x.example")
    params = {"url": OG_URL, "show_bots": "true", "host": "x.example", "flavor": "hi there"}
    text = client.get("/card", params=params).text
    href = re.search(r'<a class="btn" href="([^"]*)"', text).group(1)
    for part in ("show_bots=true", "host=x.example", "flavor=hi%20there"):
        assert part in html.unescape(href)
        assert part in _copy_button(text)


def test_actions_escape_hostile_input(monkeypatch, pr_data):
    client = _actions_env(monkeypatch, pr_data)
    evil = '"><script>alert(1)</script>'
    text = client.get("/card", params={"url": OG_URL, "flavor": evil}).text
    assert evil not in text
    assert _copy_button(text) == _meta(text, "og:url")
    assert text.count("<script") == 1


def test_tokened_card_has_download_only(monkeypatch, pr_data):
    client, _ = _token_client(monkeypatch, pr_data)
    text = client.post("/card", data={"url": PRIVATE_URL, "token": SECRET}).text
    assert re.search(
        r'<a class="btn" href="data:image/png;base64,[^"]+" download="[^"]*\.png">Download PNG</a>',
        text,
    )
    assert "Copy link" not in text and "data-url" not in text
    assert "/card.png" not in text and "clipboard" not in text


def test_no_actions_on_error_or_index():
    client = TestClient(web.app)
    for text in (client.get("/").text, client.get("/card", params={"url": "nope"}).text):
        assert "Download PNG" not in text and "Copy link" not in text
        assert "Share on" not in text


def _share_hrefs(text):
    def find(label):
        m = re.search(
            r'<a class="btn" href="([^"]*)" target="_blank" '
            rf'rel="noopener noreferrer">{label}</a>',
            text,
        )
        return html.unescape(m.group(1)) if m else None

    return find("Share on X"), find("Share on LinkedIn")


def test_share_links_present(monkeypatch, pr_data):
    client = _actions_env(monkeypatch, pr_data)
    text = client.get("/card", params={"url": OG_URL}).text
    x, li = _share_hrefs(text)
    card = _fake_card(pr_data)
    assert x.startswith("https://twitter.com/intent/tweet?")
    q = parse_qs(urlsplit(x).query, strict_parsing=True)
    expected = f"My PR scored {card.stats.ship_score} ({card.stats.rarity}) on ship-it-card 🚀"
    assert q["text"] == [expected]
    assert q["url"] == [_meta(text, "og:url")] == [_copy_button(text)]
    assert li.startswith("https://www.linkedin.com/sharing/share-offsite/?")
    assert parse_qs(urlsplit(li).query) == {"url": [_meta(text, "og:url")]}


def test_share_links_keep_params(monkeypatch, pr_data):
    client = _actions_env(monkeypatch, pr_data)
    monkeypatch.setenv("SHIPIT_ALLOWED_HOSTS", "x.example")
    params = {"url": OG_URL, "show_bots": "true", "host": "x.example", "flavor": "hi there"}
    text = client.get("/card", params=params).text
    for href in _share_hrefs(text):
        shared = parse_qs(urlsplit(href).query)["url"][0]
        assert shared == _meta(text, "og:url")
        for part in ("show_bots=true", "host=x.example", "flavor=hi%20there"):
            assert part in shared
        # The shared URL is fully encoded, so its own '&' never leaks into the outer query.
        assert "&show_bots" not in href


def test_share_links_escape_hostile_input(monkeypatch, pr_data):
    evil = '"><script>alert(1)</script>'
    client = _actions_env(monkeypatch, pr_data)
    text = client.get("/card", params={"url": OG_URL, "flavor": evil}).text
    assert evil not in text
    assert all(_share_hrefs(text))
    assert text.count("<script") == 1
    _reset()
    card = _fake_card(pr_data, title=evil)
    monkeypatch.setattr(web, "make_card", lambda url, show_bots=False, **kw: card)
    assert evil not in client.get("/card", params={"url": OG_URL}).text


def test_no_share_links_for_tokened_card(monkeypatch, pr_data):
    client, _ = _token_client(monkeypatch, pr_data)
    text = client.post("/card", data={"url": PRIVATE_URL, "token": SECRET}).text
    assert "Share on" not in text and "twitter.com" not in text and "linkedin.com" not in text
