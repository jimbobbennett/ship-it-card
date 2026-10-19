"""Regenerate the example cards in this folder. Needs GEMINI_API_KEY (and ideally GITHUB_TOKEN)."""

from pathlib import Path

from shipit.core import make_card

EXAMPLES = [
    "https://github.com/Arize-ai/phoenix/pull/16178",
    "https://github.com/Arize-ai/phoenix/pull/17062",
    "https://github.com/simonw/llm/pull/1741",
    "https://github.com/astral-sh/uv/pull/22742",
    "https://github.com/openai/codex/pull/55355",
    "https://github.com/jimbobbennett/blog-agent-bot/pull/1",
]

here = Path(__file__).parent
for url in EXAMPLES:
    card = make_card(url)
    s = card.stats
    out = here / f"{s.repo.replace('/', '-').lower()}-{s.number}.png"
    out.write_bytes(card.png)
    print(f"{out.name}: {s.rarity} {s.card_type} {s.ship_score} [{card.art_source}]")
