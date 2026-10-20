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


def test_clean_token():
    from shipit.github import clean_token

    assert clean_token(None) is None
    assert clean_token("  \t") is None
    assert clean_token(" abc ") == "abc"
    with pytest.raises(ValueError) as exc:
        clean_token("abc\nx")
    assert "abc" not in str(exc.value)
