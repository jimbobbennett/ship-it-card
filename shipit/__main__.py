"""CLI: python -m shipit <pr-url> [-o card.png] [--no-gemini] [--show-bots] [--host HOST] [--json]
[--version]"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .core import make_card, make_stats
from .github import BadPRUrl, validate_host


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
    parser.add_argument("--show-bots", action="store_true", help="include CI bots in the crew")
    parser.add_argument("--host", help="GitHub Enterprise hostname, e.g. ghe.example.com")
    parser.add_argument(
        "--json", action="store_true", help="print card stats as JSON instead of rendering a PNG"
    )
    parser.add_argument("--version", action="version", version=f"shipit {_version()}")
    args = parser.parse_args(argv)

    kwargs = {}
    if args.json:
        try:
            if args.host is not None:
                kwargs["host"] = validate_host(args.host)
            stats = make_stats(args.url, show_bots=args.show_bots, **kwargs)
        except BadPRUrl as exc:
            parser.error(str(exc))
        data = asdict(stats)
        data.pop("score_breakdown", None)  # breakdown is shown on the web page only
        print(json.dumps(data, indent=2))
        return 0

    try:
        if args.host is not None:
            kwargs["host"] = validate_host(args.host)
        card = make_card(
            args.url, use_gemini=not args.no_gemini, show_bots=args.show_bots, **kwargs
        )
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
