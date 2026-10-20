import httpx
import pytest

from shipit.github import MAX_PAGES, BadPRUrl, PRRef, fetch_pr, parse_pr_url
from shipit.stats import build_stats


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/octo/widgets/pull/42",
        "github.com/octo/widgets/pull/42/",
        "https://www.github.com/octo/widgets/pull/42#discussion",
        "  https://github.com/octo/widgets/pull/42?w=1  ",
    ],
)
def test_parses_pr_urls(url):
    ref = parse_pr_url(url)
    assert (ref.owner, ref.repo, ref.number) == ("octo", "widgets", 42)
    assert ref.slug == "octo/widgets#42"


@pytest.mark.parametrize(
    "url",
    [
        "https://gitlab.com/octo/widgets/pull/42",
        "https://github.com/octo/widgets/issues/42",
        "https://github.com/octo/widgets",
        "https://evil.example/github.com/octo/widgets/pull/42",
        "https://github.com/../widgets/pull/42",
        "",
    ],
)
def test_rejects_other_urls(url):
    with pytest.raises(BadPRUrl):
        parse_pr_url(url)


REF = PRRef("octo", "widgets", 7)


def _make_client(commit_count=0, review_count=0, base_url="https://api.github.com"):
    log = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = request.url.params
        log.append((path, dict(params)))
        if path.endswith("/commits") or path.endswith("/reviews"):
            is_commits = path.endswith("/commits")
            total = commit_count if is_commits else review_count
            page, per_page = int(params["page"]), int(params["per_page"])
            assert per_page == 100
            start = (page - 1) * per_page
            items = []
            for i in range(start, min(start + per_page, total)):
                item = {"n": i}
                if is_commits:
                    item["author"] = {"login": f"user{i}"}
                else:
                    item["user"] = {"login": f"rev{i}"}
                items.append(item)
            return httpx.Response(200, json=items)
        if path.endswith("/pulls/7"):
            return httpx.Response(200, json={"user": {"login": "octo"}})
        return httpx.Response(200, json={})

    return httpx.Client(transport=httpx.MockTransport(handler), base_url=base_url), log


def _pages(log, suffix):
    return [int(p["page"]) for path, p in log if path.endswith(suffix)]


def test_commits_paginate_across_three_pages():
    client, log = _make_client(commit_count=230)
    data = fetch_pr(REF, client=client)
    assert [c["n"] for c in data.commits] == list(range(230))
    assert _pages(log, "/commits") == [1, 2, 3]


def test_reviews_paginate_across_three_pages():
    client, log = _make_client(review_count=230)
    data = fetch_pr(REF, client=client)
    assert [r["n"] for r in data.reviews] == list(range(230))
    assert _pages(log, "/reviews") == [1, 2, 3]


def test_short_first_page_makes_one_request():
    client, log = _make_client(commit_count=99, review_count=5)
    data = fetch_pr(REF, client=client)
    assert len(data.commits) == 99
    assert _pages(log, "/commits") == [1]
    assert _pages(log, "/reviews") == [1]


def test_exact_multiple_of_page_size_stops_on_empty_page():
    client, log = _make_client(commit_count=100)
    data = fetch_pr(REF, client=client)
    assert len(data.commits) == 100
    assert _pages(log, "/commits") == [1, 2]


def test_author_on_page_two_is_in_crew():
    client, _ = _make_client(commit_count=130)
    stats = build_stats(fetch_pr(REF, client=client))
    names = {m.name for m in stats.crew}
    assert "user0" in names
    assert "user101" in names


def test_page_cap_bounds_requests():
    log = []

    def handler(request: httpx.Request) -> httpx.Response:
        log.append(request.url.path)
        if request.url.path.endswith("/commits"):
            return httpx.Response(200, json=[{}] * 100)
        return httpx.Response(200, json=[] if request.url.path.endswith("/reviews") else {})

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://x/api/v3")
    data = fetch_pr(REF, client=client)
    assert len(data.commits) == MAX_PAGES * 100
    assert sum(p.endswith("/commits") for p in log) == MAX_PAGES


def test_http_error_on_later_page_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/commits"):
            if request.url.params["page"] == "1":
                return httpx.Response(200, json=[{}] * 100)
            return httpx.Response(500, json={})
        return httpx.Response(200, json={})

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://x/api/v3")
    with pytest.raises(httpx.HTTPStatusError):
        fetch_pr(REF, client=client)


def test_pagination_with_custom_host_base_url():
    client, log = _make_client(commit_count=230, base_url="https://ghe.example.com/api/v3")
    data = fetch_pr(REF, client=client)
    assert len(data.commits) == 230
    assert _pages(log, "/commits") == [1, 2, 3]
    assert all(path.startswith("/api/v3/repos/octo/widgets") for path, _ in log)
