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
