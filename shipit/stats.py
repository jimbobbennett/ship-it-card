"""Turn raw GitHub PR data into the numbers and words printed on a card."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .github import PRData

AGENT_NAMES = {
    "claude": "Claude",
    "codex": "Codex",
    "copilot": "Copilot",
    "cursor": "Cursor",
    "devin": "Devin",
    "aider": "Aider",
    "gemini": "Gemini",
    "jules": "Jules",
    "amp": "Amp",
    "windsurf": "Windsurf",
    "kiro": "Kiro",
    "openhands": "OpenHands",
    "droid": "Factory",
    "droids": "Factory",
}

# Multi-word names, matched as consecutive words. A lone "q", "all" or "hands" is not an agent.
AGENT_PHRASES = {
    ("amazon", "q"): "Amazon Q",
    ("open", "hands"): "OpenHands",
    ("all", "hands"): "OpenHands",
}

AGENT_EMAILS = {
    "noreply@anthropic.com": "Claude",
    "noreply@openai.com": "Codex",
    "cursoragent@cursor.com": "Cursor",
}

CO_AUTHOR = re.compile(r"^co-authored-by:\s*(?P<name>[^<\n]+?)\s*<(?P<email>[^>\n]*)>", re.I | re.M)

CARD_TYPES = {
    "feat": "Feature",
    "feature": "Feature",
    "fix": "Fix",
    "bug": "Fix",
    "docs": "Docs",
    "documentation": "Docs",
    "refactor": "Refactor",
    "perf": "Speed",
    "performance": "Speed",
    "test": "Tests",
    "tests": "Tests",
    "chore": "Chore",
    "ci": "Chore",
    "build": "Chore",
    "security": "Shield",
}

RARITIES = [(40, "Common"), (72, "Uncommon"), (75, "Rare"), (88, "Epic"), (100, "Legendary")]

FLAVOR = [
    "Merged, tagged and out the door.",
    "Another one for the release notes.",
    "Every great release starts with one green check.",
    "Reviewed, approved, shipped. The holy trinity.",
    "Somewhere a changelog just got longer.",
    "The CI was green and the vibes were immaculate.",
    "Production called. This answered.",
]

TEAM_FLAVOR = [
    "Humans and agents, shipping side by side.",
    "Pair programming, upgraded.",
    "One prompt, many hands, zero merge conflicts.",
    "The agents did the typing. The humans did the judgement.",
    "Silicon and carbon, co-authoring the changelog.",
]

TINY_FLAVOR = [
    "Small diff. Big energy.",
    "A few lines, zero fuss.",
    "Tiny change, clean ship.",
    "Proof that small PRs merge fastest.",
]

HUGE_FLAVOR = [
    "A mountain of changes, and it still shipped.",
    "Thousands of lines. One brave reviewer.",
    "This one needed a bigger diff viewer.",
    "Huge in scope, landed anyway.",
]

DOCS_FLAVOR = [
    "Words matter. Shipped them.",
    "The docs are now slightly less lying.",
    "Future readers say thank you.",
    "Documentation: the feature behind every feature.",
]

TINY_MAX_LINES = 10  # total lines changed at or below this is "tiny"
HUGE_MIN_LINES = 1000  # total lines changed at or above this is "huge"


@dataclass
class CrewMember:
    name: str
    kind: str  # "human", "agent" or "bot"


@dataclass
class Ability:
    name: str
    value: str


@dataclass
class ScoreLine:
    label: str
    value: str
    points: int


@dataclass
class ScoreBreakdown:
    lines: list[ScoreLine]
    total: int


@dataclass
class CardStats:
    slug: str
    title: str
    repo: str
    number: int
    author: str
    language: str
    description: str
    card_type: str
    merged: bool
    additions: int
    deletions: int
    changed_files: int
    commits: int
    reviewers: int
    minutes_to_merge: int | None
    ship_score: int
    rarity: str
    abilities: list[Ability] = field(default_factory=list)
    crew: list[CrewMember] = field(default_factory=list)
    flavor: str = ""
    year: int = 0
    score_breakdown: ScoreBreakdown | None = None
    pr_body: str = ""

    @property
    def has_agents(self) -> bool:
        return any(member.kind == "agent" for member in self.crew)


def build_stats(data: PRData, show_bots: bool = False) -> CardStats:
    pr, repo = data.pr, data.repo
    additions = int(pr.get("additions") or 0)
    deletions = int(pr.get("deletions") or 0)
    changed_files = int(pr.get("changed_files") or 0)
    commits = int(pr.get("commits") or len(data.commits))
    merged_at = _parse_time(pr.get("merged_at"))
    created_at = _parse_time(pr.get("created_at"))
    minutes = None
    if merged_at and created_at:
        minutes = max(0, int((merged_at - created_at).total_seconds() // 60))

    reviewers = {
        r["user"]["login"]
        for r in data.reviews
        if r.get("user") and r["user"].get("login") != (pr.get("user") or {}).get("login")
    }
    crew = find_crew(data, show_bots=show_bots)
    type_ = card_type(pr.get("title") or "", [lbl.get("name", "") for lbl in pr.get("labels", [])])
    breakdown = score_breakdown(additions + deletions, len(reviewers), commits, minutes)
    score = breakdown.total

    return CardStats(
        slug=data.ref.slug,
        title=clean_title(pr.get("title") or "") or f"PR #{data.ref.number}",
        repo=repo.get("full_name") or f"{data.ref.owner}/{data.ref.repo}",
        number=data.ref.number,
        author=(pr.get("user") or {}).get("login", "unknown"),
        language=repo.get("language") or "Code",
        description=repo.get("description") or "",
        pr_body=pr.get("body") or "",
        card_type=type_,
        merged=merged_at is not None,
        additions=additions,
        deletions=deletions,
        changed_files=changed_files,
        commits=commits,
        reviewers=len(reviewers),
        minutes_to_merge=minutes,
        ship_score=score,
        rarity=rarity(score),
        abilities=abilities(additions, deletions, changed_files, minutes),
        crew=crew,
        flavor=flavor(
            data.ref.slug, additions + deletions, type_, any(m.kind == "agent" for m in crew)
        ),
        score_breakdown=breakdown,
        year=(merged_at or created_at or datetime.now(timezone.utc)).year,  # noqa: UP017
    )


def find_crew(data: PRData, show_bots: bool = False) -> list[CrewMember]:
    """Everyone who touched the PR: commit authors plus co-author trailers.

    Generic bots (kind "bot") are left out unless show_bots is set; coding agents stay.
    """
    crew: dict[str, CrewMember] = {}

    def add(name: str, kind: str) -> None:
        key = name.lower()
        if key not in crew or (kind == "agent" and crew[key].kind != "agent"):
            crew[key] = CrewMember(name, kind)

    pr_author = (data.pr.get("user") or {}).get("login")
    if pr_author:
        add(*_classify_login(pr_author))

    for commit in data.commits:
        login = (commit.get("author") or {}).get("login")
        if login:
            add(*_classify_login(login))
        message = (commit.get("commit") or {}).get("message", "")
        for match in CO_AUTHOR.finditer(message):
            name, email = match["name"].strip(), match["email"].strip().lower()
            agent = AGENT_EMAILS.get(email) or _agent_name(name)
            if agent:
                add(agent, "agent")
            else:
                add(name, "human")
    return [m for m in crew.values() if show_bots or m.kind != "bot"]


def _classify_login(login: str) -> tuple[str, str]:
    agent = _agent_name(login)
    if agent:
        return agent, "agent"
    if login.endswith("[bot]"):
        return login.removesuffix("[bot]"), "bot"
    return login, "human"


def _agent_name(text: str) -> str | None:
    words = re.findall(r"[a-z]+", text.lower())
    for word in words:
        if word in AGENT_NAMES:
            return AGENT_NAMES[word]
    for pair in zip(words, words[1:], strict=False):
        if pair in AGENT_PHRASES:
            return AGENT_PHRASES[pair]
    return None


def clean_title(title: str) -> str:
    """Drop a conventional-commit prefix like 'feat(ui): ' and capitalise."""
    title = re.sub(r"^\s*\[?[A-Za-z]+(\([^)]*\))?!?[\]:]\s*", "", title).strip()
    return title[:1].upper() + title[1:]


def card_type(title: str, labels: list[str]) -> str:
    prefix = re.match(r"^\s*\[?([A-Za-z]+)[\](:!]", title)
    candidates = ([prefix.group(1)] if prefix else []) + labels
    for candidate in candidates:
        key = candidate.lower().strip()
        if key in CARD_TYPES:
            return CARD_TYPES[key]
    return "Feature"


def score_breakdown(
    lines_changed: int, reviewers: int, commits: int, minutes: int | None
) -> ScoreBreakdown:
    """Points per ship-score factor, plus the clamped total. The one copy of the formula."""
    if minutes is None:
        speed_value, speed = "not merged / unknown", 0
    else:
        speed_value = format_duration(minutes)
        speed = 15 if minutes <= 60 else 10 if minutes <= 24 * 60 else 0
    size = round(20 * math.log10(1 + lines_changed))
    lines = [
        ScoreLine("Size", f"{lines_changed:,} lines changed", size),
        ScoreLine(
            "Reviewers",
            f"{reviewers} reviewer{'s' if reviewers != 1 else ''}",
            5 * min(reviewers, 4),
        ),
        ScoreLine("Commits", f"{commits} commit{'s' if commits != 1 else ''}", min(commits, 10)),
        ScoreLine("Speed", speed_value, speed),
    ]
    raw = sum(line.points for line in lines)
    total = max(1, min(99, raw))
    if total != raw:
        lines.append(ScoreLine("Adjustment", "clamped to 1-99", total - raw))
    return ScoreBreakdown(lines, total)


def ship_score(lines_changed: int, reviewers: int, commits: int, minutes: int | None) -> int:
    return score_breakdown(lines_changed, reviewers, commits, minutes).total


def rarity(score: int) -> str:
    for ceiling, name in RARITIES:
        if score < ceiling:
            return name
    return RARITIES[-1][1]


def abilities(additions: int, deletions: int, files: int, minutes: int | None) -> list[Ability]:
    moves = [
        Ability("Code Surge", f"+{additions:,} / -{deletions:,}"),
        Ability("Blast Radius", f"{files:,} file{'s' if files != 1 else ''}"),
    ]
    if minutes is not None:
        name = "Quick Merge" if minutes <= 24 * 60 else "The Long Game"
        moves.append(Ability(name, format_duration(minutes)))
    return moves


def format_duration(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes}m"
    hours, mins = divmod(minutes, 60)
    if hours < 48:
        return f"{hours}h {mins}m"
    return f"{hours // 24} days"


def flavor(slug: str, lines_changed: int, card_type: str, has_agents: bool) -> str:
    """Pick a deterministic flavour line that fits the PR.

    Pool precedence: docs-only (card_type == "Docs"), then agent-assisted, then
    tiny (<= TINY_MAX_LINES), then huge (>= HUGE_MIN_LINES), then the general pool.
    """
    if card_type == "Docs":
        pool = DOCS_FLAVOR
    elif has_agents:
        pool = TEAM_FLAVOR
    elif lines_changed <= TINY_MAX_LINES:
        pool = TINY_FLAVOR
    elif lines_changed >= HUGE_MIN_LINES:
        pool = HUGE_FLAVOR
    else:
        pool = FLAVOR
    index = int(hashlib.sha256(slug.encode()).hexdigest(), 16) % len(pool)
    return pool[index]


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
