import pytest

from shipit.stats import (
    build_stats,
    card_type,
    clean_title,
    find_crew,
    format_duration,
    rarity,
    ship_score,
)


def test_build_stats(pr_data):
    s = build_stats(pr_data)
    assert s.title == "Add sparkle mode"
    assert s.card_type == "Feature"
    assert s.merged and s.minutes_to_merge == 150
    assert s.reviewers == 1  # self-reviews and repeat reviews do not count
    assert [a.name for a in s.abilities] == ["Code Surge", "Blast Radius", "Quick Merge"]


def test_year_fallback_uses_aware_utc_clock(pr_data, monkeypatch):
    from datetime import UTC, datetime, timedelta

    instant = datetime(2025, 12, 31, 23, 30, tzinfo=UTC)

    class FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                # naive local time on a server at UTC+1: already in 2026
                return (instant + timedelta(hours=1)).replace(tzinfo=None)
            return instant.astimezone(tz)

    monkeypatch.setattr("shipit.stats.datetime", FakeDatetime)
    pr_data.pr["merged_at"] = None
    pr_data.pr["created_at"] = None
    assert build_stats(pr_data).year == 2025


def test_crew_detects_agents_humans_and_bots(pr_data):
    crew = {m.name: m.kind for m in build_stats(pr_data, show_bots=True).crew}
    assert crew == {
        "octocat": "human",
        "Claude": "agent",
        "Ada Lovelace": "human",
        "dependabot": "bot",
    }
    assert build_stats(pr_data, show_bots=True).has_agents
    assert {m.name: m.kind for m in find_crew(pr_data, show_bots=True)} == crew


def test_crew_excludes_bots_by_default(pr_data):
    stats = build_stats(pr_data)
    crew = {m.name: m.kind for m in stats.crew}
    assert crew == {"octocat": "human", "Claude": "agent", "Ada Lovelace": "human"}
    assert {m.name: m.kind for m in find_crew(pr_data)} == crew
    assert stats.has_agents
    assert stats.flavor == build_stats(pr_data, show_bots=True).flavor


def test_generic_bots_hidden_and_coding_agents_kept(pr_data):
    for login in ("github-actions[bot]", "codecov[bot]", "copilot[bot]", "claude[bot]"):
        pr_data.commits.append({"author": {"login": login}, "commit": {"message": "x"}})
    default = {m.name: m.kind for m in find_crew(pr_data)}
    assert "github-actions" not in default and "codecov" not in default
    assert "dependabot" not in default
    assert default["Copilot"] == "agent"
    assert default["Claude"] == "agent"
    shown = {m.name: m.kind for m in find_crew(pr_data, show_bots=True)}
    assert shown["github-actions"] == "bot" and shown["codecov"] == "bot"


def test_bot_pr_author_hidden_but_still_author(pr_data):
    pr_data.pr["user"] = {"login": "dependabot[bot]"}
    stats = build_stats(pr_data)
    assert stats.author == "dependabot[bot]"
    assert "dependabot" not in [m.name for m in stats.crew]
    assert "dependabot" in [m.name for m in build_stats(pr_data, show_bots=True).crew]


@pytest.mark.parametrize(
    "title,expected",
    [
        ("fix: crash", "Fix"),
        ("docs(readme): typo", "Docs"),
        ("[perf] faster", "Speed"),
        ("Make it nice", "Feature"),
    ],
)
def test_card_type(title, expected):
    assert card_type(title, []) == expected


def test_card_type_falls_back_to_labels():
    assert card_type("Tidy up", ["security"]) == "Shield"


def test_clean_title():
    assert clean_title("feat(ui)!: skeleton loaders") == "Skeleton loaders"
    assert clean_title("Plain title") == "Plain title"


def test_ship_score_is_bounded():
    assert ship_score(0, 0, 0, None) == 1
    assert ship_score(10**9, 50, 500, 1) == 99


def test_rarity_thresholds():
    assert [rarity(s) for s in (1, 45, 70, 80, 99)] == [
        "Common",
        "Uncommon",
        "Rare",
        "Epic",
        "Legendary",
    ]


def test_format_duration():
    assert format_duration(5) == "5m"
    assert format_duration(150) == "2h 30m"
    assert format_duration(60 * 24 * 6) == "6 days"
