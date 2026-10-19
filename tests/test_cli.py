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


def test_url_still_required():
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2
