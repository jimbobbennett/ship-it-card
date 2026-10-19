"""CLI: python -m shipit <pr-url> [-o card.png] [--no-gemini] [--version]"""

from __future__ import annotations

import argparse
import importlib.metadata
import sys
from pathlib import Path

from .core import make_card
from .github import BadPRUrl


def _version() -> str:
    try:
        return importlib.metadata.version("ship-it-card")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="shipit", description="Make a ship-it card for a PR.")
    parser.add_argument("url", help="GitHub pull request URL")
    parser.add_argument("-o", "--out", type=Path, help="output PNG (default: <repo>-<n>.png)")
    parser.add_argument("--no-gemini", action="store_true", help="use procedural art")
    parser.add_argument("--version", action="version", version=f"shipit {_version()}")
    args = parser.parse_args(argv)

    try:
        card = make_card(args.url, use_gemini=not args.no_gemini)
    except BadPRUrl as exc:
        parser.error(str(exc))

    s = card.stats
    out = args.out or Path(f"{s.repo.split('/')[-1]}-{s.number}.png")
    out.write_bytes(card.png)
    print(f"{s.slug}: {s.rarity} {s.card_type}, ship score {s.ship_score} ({card.art_source} art)")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
