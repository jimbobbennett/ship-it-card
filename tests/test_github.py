import pytest

from shipit.github import BadPRUrl, parse_pr_url


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


def _captured_auth(monkeypatch, host=None, token=None):
    import httpx

    from shipit import github

    seen = []

    def handler(request):
        seen.append(request.headers.get("authorization"))
        return httpx.Response(200, json={})

    with monkeypatch.context() as m:
        real = httpx.Client
        m.setattr(
            github.httpx,
            "Client",
            lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs),
        )
        github.fetch_pr(github.PRRef("o", "r", 1), host=host, token=token)
    return seen


def test_token_header(monkeypatch):
    from shipit.github import _headers

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert _headers(token="tok")["Authorization"] == "Bearer tok"
    assert "Authorization" not in _headers()


def test_token_beats_env(monkeypatch):
    from shipit.github import _headers

    monkeypatch.setenv("GITHUB_TOKEN", "envtok")
    monkeypatch.setenv("GHE_TOKEN", "gheenv")
    assert _headers(token="tok")["Authorization"] == "Bearer tok"
    assert _headers("ghe.example.com", "tok")["Authorization"] == "Bearer tok"
    assert _headers()["Authorization"] == "Bearer envtok"
    assert _headers("ghe.example.com")["Authorization"] == "Bearer gheenv"


def test_github_token_never_sent_to_custom_host(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "envtok")
    monkeypatch.delenv("GHE_TOKEN", raising=False)
    assert set(_captured_auth(monkeypatch, host="ghe.example.com")) == {None}
    assert set(_captured_auth(monkeypatch, host="ghe.example.com", token="tok")) == {"Bearer tok"}


def test_fetch_pr_sends_token(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "envtok")
    assert set(_captured_auth(monkeypatch, token="tok")) == {"Bearer tok"}
    assert set(_captured_auth(monkeypatch)) == {"Bearer envtok"}


def test_fetch_pr_token_with_injected_client(monkeypatch):
    import httpx

    from shipit import github

    monkeypatch.setenv("GITHUB_TOKEN", "envtok")
    seen = []

    def handler(request):
        seen.append(request.headers.get("authorization"))
        return httpx.Response(200, json={})

    ref = github.PRRef("o", "r", 1)
    with httpx.Client(
        base_url=github.API,
        headers={"Authorization": "Bearer clienttok"},
        transport=httpx.MockTransport(handler),
    ) as client:
        github.fetch_pr(ref, client=client, token="tok")
        assert set(seen) == {"Bearer tok"} and len(seen) == 4
        seen.clear()
        github.fetch_pr(ref, client=client)
        assert set(seen) == {"Bearer clienttok"}


def _fetch_client(handler):
    import httpx

    return httpx.Client(base_url="https://api.github.com", transport=httpx.MockTransport(handler))


def _ref():
    from shipit.github import PRRef

    return PRRef("octo", "widgets", 7)


def test_fetch_pr_requests_are_concurrent():
    import threading

    import httpx

    from shipit.github import fetch_pr

    barrier = threading.Barrier(4, timeout=5)
    seen = []

    def handler(request):
        barrier.wait()  # only passes if all 4 requests are in flight together
        seen.append((request.url.path, request.url.query.decode()))
        return httpx.Response(200, json={"path": request.url.path})

    client = _fetch_client(handler)
    data = fetch_pr(_ref(), client=client)
    assert sorted(seen) == sorted(
        [
            ("/repos/octo/widgets/pulls/7", ""),
            ("/repos/octo/widgets", ""),
            ("/repos/octo/widgets/pulls/7/commits", "per_page=100"),
            ("/repos/octo/widgets/pulls/7/reviews", "per_page=100"),
        ]
    )
    assert data.pr == {"path": "/repos/octo/widgets/pulls/7"}
    assert not client.is_closed


def test_fetch_pr_maps_results_regardless_of_completion_order():
    import threading
    import time

    import httpx

    from shipit.github import fetch_pr

    delays = {
        "/repos/octo/widgets/pulls/7": 0.3,
        "/repos/octo/widgets": 0.2,
        "/repos/octo/widgets/pulls/7/commits": 0.1,
        "/repos/octo/widgets/pulls/7/reviews": 0.0,
    }
    started = threading.Barrier(4, timeout=5)

    def handler(request):
        started.wait()
        time.sleep(delays[request.url.path])
        return httpx.Response(200, json={"p": request.url.path})

    data = fetch_pr(_ref(), client=_fetch_client(handler))
    assert data.pr == {"p": "/repos/octo/widgets/pulls/7"}
    assert data.repo == {"p": "/repos/octo/widgets"}
    assert data.commits == {"p": "/repos/octo/widgets/pulls/7/commits"}
    assert data.reviews == {"p": "/repos/octo/widgets/pulls/7/reviews"}


def test_fetch_pr_404_raises_http_status_error():
    import httpx

    from shipit.github import fetch_pr

    def handler(request):
        if request.url.path == "/repos/octo/widgets/pulls/7":
            return httpx.Response(404, json={})
        return httpx.Response(200, json={})

    with pytest.raises(httpx.HTTPStatusError):
        fetch_pr(_ref(), client=_fetch_client(handler))


def test_fetch_pr_closes_own_client_on_success_and_failure(monkeypatch):
    import httpx

    from shipit import github

    created = []
    status = {"code": 200}

    def handler(request):
        return httpx.Response(status["code"], json={})

    real = httpx.Client

    def factory(**kw):
        c = real(transport=httpx.MockTransport(handler), **kw)
        created.append(c)
        return c

    monkeypatch.setattr(github.httpx, "Client", factory)
    github.fetch_pr(_ref())
    status["code"] = 500
    with pytest.raises(httpx.HTTPStatusError):
        github.fetch_pr(_ref())
    assert len(created) == 2 and all(c.is_closed for c in created)


def test_fetch_pr_invalid_host_raises_before_any_request(monkeypatch):
    from shipit import github

    def factory(**kw):
        raise AssertionError("no client expected")

    monkeypatch.setattr(github.httpx, "Client", factory)
    with pytest.raises(BadPRUrl):
        github.fetch_pr(_ref(), host="bad host/x")


def test_clean_token():
    from shipit.github import clean_token

    assert clean_token(None) is None
    assert clean_token("  \t") is None
    assert clean_token(" abc ") == "abc"
    with pytest.raises(ValueError) as exc:
        clean_token("abc\nx")
    assert "abc" not in str(exc.value)
