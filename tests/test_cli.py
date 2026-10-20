import importlib.metadata
import json
import tomllib
from pathlib import Path

import pytest

from shipit.__main__ import main


def _installed_version() -> str:
    # pyproject.toml has no [build-system], so `uv sync` doesn't install the project itself
    # and metadata may be absent; tests that need the real version skip in that case.
    try:
        return importlib.metadata.version("ship-it-card")
    except importlib.metadata.PackageNotFoundError:
        pytest.skip("ship-it-card is not installed (no package metadata)")


def _run_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    return capsys.readouterr().out


def test_version_prints_metadata_version(capsys):
    expected = _installed_version()
    out = _run_version(capsys)
    assert expected in out
    assert out.startswith("shipit ")
    assert len(out.strip().splitlines()) == 1


def test_version_fallback_when_not_installed(capsys, monkeypatch):
    def boom(name):
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", boom)
    assert "unknown" in _run_version(capsys)


def test_version_matches_pyproject(capsys):
    _installed_version()
    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    expected = tomllib.loads(pyproject.read_text())["project"]["version"]
    assert _run_version(capsys).strip() == f"shipit {expected}"


@pytest.mark.parametrize(("extra", "expected"), [([], False), (["--show-bots"], True)])
def test_show_bots_flag(monkeypatch, tmp_path, extra, expected):
    from shipit import __main__ as cli
    from shipit.core import Card
    from shipit.stats import CardStats

    seen = {}

    def fake(url, use_gemini=True, show_bots=False):
        seen["show_bots"] = show_bots
        stats = CardStats("o/r#1", "t", "o/r", 1, "a", "Python", "", "Feature", True, 1, 1, 1, 1, 0,
                          None, 10, "Common")  # fmt: skip
        return Card(stats, b"png", "procedural")

    monkeypatch.setattr(cli, "make_card", fake)
    assert main(["https://github.com/o/r/pull/1", "-o", str(tmp_path / "c.png"), *extra]) == 0
    assert seen["show_bots"] is expected


def test_show_bots_in_help(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    assert "--show-bots" in capsys.readouterr().out


def test_url_still_required():
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


URL = "https://github.com/o/r/pull/1"
JSON_KEYS = [
    "slug", "title", "repo", "number", "author", "language", "description", "card_type",
    "merged", "additions", "deletions", "changed_files", "commits", "reviewers",
    "minutes_to_merge", "ship_score", "rarity", "abilities", "crew", "flavor", "year",
]  # fmt: skip


def _fake_stats(show_bots=False):
    from shipit.stats import Ability, CardStats, CrewMember

    crew = [CrewMember("alice", "human")]
    if show_bots:
        crew.append(CrewMember("ci[bot]", "bot"))
    return CardStats(
        "o/r#1", "t", "o/r", 1, "alice", "Python", "", "Feature", True, 1, 1, 1, 1, 0,
        None, 10, "Common", [Ability("Speed", "fast")], crew, "nice", 2024,
    )  # fmt: skip


@pytest.fixture
def json_env(monkeypatch, tmp_path):
    from shipit import __main__ as cli
    from shipit import core

    def boom(*a, **k):
        raise AssertionError("must not be called")

    monkeypatch.setattr(core, "get_art", boom)
    monkeypatch.setattr(core, "card_png", boom)
    monkeypatch.setattr(cli, "make_card", boom)
    monkeypatch.setattr(core, "parse_pr_url", lambda url, host=None: url)
    monkeypatch.setattr(core, "fetch_pr", lambda ref, host=None: ref)
    seen = {}

    def fake_build(pr, show_bots=False):
        seen["show_bots"] = show_bots
        return _fake_stats(show_bots)

    monkeypatch.setattr(core, "build_stats", fake_build)
    monkeypatch.chdir(tmp_path)
    return seen, tmp_path


def test_json_output(json_env, capsys):
    _, tmp_path = json_env
    assert main([URL, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert list(data) == JSON_KEYS
    assert data["slug"] == "o/r#1"
    assert data["ship_score"] == 10
    assert data["minutes_to_merge"] is None
    assert data["abilities"] == [{"name": "Speed", "value": "fast"}]
    assert data["crew"] == [{"name": "alice", "kind": "human", "first_timer": False}]
    assert not list(tmp_path.iterdir())


def test_json_ignores_out(json_env):
    _, tmp_path = json_env
    assert main([URL, "--json", "-o", str(tmp_path / "x.png")]) == 0
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(("extra", "expected"), [([], False), (["--show-bots"], True)])
def test_json_show_bots(json_env, capsys, extra, expected):
    seen, _ = json_env
    assert main([URL, "--json", *extra]) == 0
    assert seen["show_bots"] is expected
    names = [c["name"] for c in json.loads(capsys.readouterr().out)["crew"]]
    assert ("ci[bot]" in names) is expected


def test_json_bad_url(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["not-a-url", "--json"])
    assert exc.value.code == 2
    assert capsys.readouterr().out == ""


def test_json_in_help(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    assert "--json" in capsys.readouterr().out


def test_normalize_flavor():
    from shipit.core import normalize_flavor

    assert normalize_flavor(None) is None
    assert normalize_flavor("  \n\t ") is None
    assert normalize_flavor("  hi\nthere\x00 ") == "hi there"
    assert normalize_flavor("x" * 80) == "x" * 80
    with pytest.raises(ValueError):
        normalize_flavor("x" * 81)


def test_flavor_json(json_env, capsys):
    assert main([URL, "--json", "--flavor", "Ship happens"]) == 0
    assert json.loads(capsys.readouterr().out)["flavor"] == "Ship happens"


def test_flavor_png(monkeypatch, tmp_path):
    from shipit import core

    seen = {}
    monkeypatch.setattr(core, "parse_pr_url", lambda url, host=None: url)
    monkeypatch.setattr(core, "fetch_pr", lambda ref, host=None: ref)
    monkeypatch.setattr(core, "build_stats", lambda pr, show_bots=False: _fake_stats())
    monkeypatch.setattr(core, "get_art", lambda stats, use_gemini=True: (None, "procedural"))

    def fake_png(stats, art):
        seen["flavor"] = stats.flavor
        return b"png"

    monkeypatch.setattr(core, "card_png", fake_png)
    out = tmp_path / "out.png"
    assert main([URL, "--flavor", "Ship happens", "-o", str(out)]) == 0
    assert seen["flavor"] == "Ship happens"
    assert out.read_bytes() == b"png"


def test_flavor_too_long(json_env, capsys, tmp_path):
    with pytest.raises(SystemExit) as exc:
        main([URL, "--flavor", "x" * 81, "-o", str(tmp_path / "o.png")])
    assert exc.value.code != 0
    assert "80" in capsys.readouterr().err
    assert not (tmp_path / "o.png").exists()


def _token_env(monkeypatch):
    from shipit import core

    seen = {}

    def fake_fetch(ref, host=None, token=None):
        seen["token"] = token
        return ref

    monkeypatch.setattr(core, "parse_pr_url", lambda url, host=None: url)
    monkeypatch.setattr(core, "fetch_pr", fake_fetch)
    monkeypatch.setattr(core, "build_stats", lambda pr, show_bots=False: _fake_stats())
    monkeypatch.setattr(core, "get_art", lambda stats, use_gemini=True: (None, "procedural"))
    monkeypatch.setattr(core, "card_png", lambda stats, art: b"png")
    return seen


def test_token_png(monkeypatch, tmp_path, capsys):
    seen = _token_env(monkeypatch)
    out = tmp_path / "out.png"
    assert main([URL, "--token", " ghp_secret ", "-o", str(out)]) == 0
    assert seen["token"] == "ghp_secret"
    captured = capsys.readouterr()
    assert "ghp_secret" not in captured.out + captured.err
    assert b"ghp_secret" not in out.read_bytes()


def test_token_json(monkeypatch, tmp_path, capsys):
    seen = _token_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    assert main([URL, "--json", "--token", "ghp_secret"]) == 0
    assert seen["token"] == "ghp_secret"
    captured = capsys.readouterr()
    assert "ghp_secret" not in captured.out + captured.err
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("value", ["", "   "])
def test_blank_token_is_unset(monkeypatch, tmp_path, value):
    seen = _token_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    assert main([URL, "--json", "--token", value]) == 0
    assert seen["token"] is None


def test_token_control_chars_rejected(monkeypatch, capsys):
    _token_env(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        main([URL, "--json", "--token", "abc\r\nX-Evil: 1"])
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert "X-Evil" not in captured.out + captured.err


def test_token_in_docs():
    from shipit import __main__ as cli

    assert "--token" in cli.__doc__
    assert "--token" in (Path(__file__).parent.parent / "README.md").read_text()
