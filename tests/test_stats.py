import pytest

from shipit.stats import (
    build_stats,
    card_type,
    clean_title,
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


def test_crew_detects_agents_humans_and_bots(pr_data):
    crew = {m.name: m.kind for m in build_stats(pr_data).crew}
    assert crew == {
        "octocat": "human",
        "Claude": "agent",
        "Ada Lovelace": "human",
        "dependabot": "bot",
    }
    assert build_stats(pr_data).has_agents


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
