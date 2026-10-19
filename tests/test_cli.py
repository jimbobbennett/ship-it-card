import importlib.metadata
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
