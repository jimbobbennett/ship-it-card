import pytest

from shipit import stats
from shipit.stats import (
    build_stats,
    card_type,
    clean_title,
    find_crew,
    flavor,
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
    cases = [
        (1, "Common"),
        (39, "Common"),
        (40, "Uncommon"),
        (71, "Uncommon"),
        (72, "Rare"),
        (74, "Rare"),
        (75, "Epic"),
        (87, "Epic"),
        (88, "Legendary"),
        (99, "Legendary"),
    ]
    assert [rarity(s) for s, _ in cases] == [name for _, name in cases]


def test_format_duration():
    assert format_duration(5) == "5m"
    assert format_duration(150) == "2h 30m"
    assert format_duration(60 * 24 * 6) == "6 days"


SLUGS = [f"owner/repo#{n}" for n in range(30)]


@pytest.mark.parametrize(
    "lines,type_,agents,pool",
    [
        (1, "Fix", False, stats.TINY_FLAVOR),
        (stats.TINY_MAX_LINES, "Fix", False, stats.TINY_FLAVOR),
        (stats.TINY_MAX_LINES + 1, "Fix", False, stats.FLAVOR),
        (500, "Feature", False, stats.FLAVOR),
        (stats.HUGE_MIN_LINES - 1, "Feature", False, stats.FLAVOR),
        (stats.HUGE_MIN_LINES, "Feature", False, stats.HUGE_FLAVOR),
        (3000, "Refactor", False, stats.HUGE_FLAVOR),
        (500, "Docs", False, stats.DOCS_FLAVOR),
        (500, "Feature", True, stats.TEAM_FLAVOR),
        (500, "Docs", True, stats.DOCS_FLAVOR),
        (1, "Fix", True, stats.TEAM_FLAVOR),
        (3000, "Feature", True, stats.TEAM_FLAVOR),
    ],
)
def test_flavor_pool_selection(lines, type_, agents, pool):
    for slug in SLUGS:
        assert flavor(slug, lines, type_, agents) in pool


def test_flavor_pools_are_distinct_and_sized():
    for pool in (stats.TINY_FLAVOR, stats.HUGE_FLAVOR, stats.DOCS_FLAVOR, stats.TEAM_FLAVOR):
        assert len(pool) >= 3
        assert not set(pool) & set(stats.FLAVOR)
    assert not set(stats.TINY_FLAVOR) & set(stats.HUGE_FLAVOR)


def test_flavor_is_deterministic():
    for slug in SLUGS:
        assert len({flavor(slug, 500, "Feature", False) for _ in range(5)}) == 1


def test_build_stats_flavor_pools(pr_data):
    pr_data.pr["additions"], pr_data.pr["deletions"] = 3, 2
    pr_data.pr["title"] = "fix: typo"
    assert build_stats(pr_data).flavor in stats.TEAM_FLAVOR  # fixture has an agent
    pr_data.pr["title"] = "docs: typo"
    first = build_stats(pr_data).flavor
    assert first in stats.DOCS_FLAVOR
    assert build_stats(pr_data).flavor == first


def _trailer(name, email="x@example.com"):
    return {"author": None, "commit": {"message": f"x\n\nCo-Authored-By: {name} <{email}>"}}


def _kinds(pr_data, **kw):
    return {m.name: m.kind for m in find_crew(pr_data, **kw)}


@pytest.mark.parametrize(
    "trailer,login,expected",
    [
        ("Windsurf", "windsurf[bot]", "Windsurf"),
        ("Kiro", "kiro[bot]", "Kiro"),
        ("OpenHands", "openhands-agent", "OpenHands"),
        ("openhands", "all-hands-bot", "OpenHands"),
        ("Factory Droid", "factory-droid[bot]", "Factory"),
        ("droid", "droids[bot]", "Factory"),
        ("Amazon Q", "amazon-q-developer[bot]", "Amazon Q"),
        ("Amazon Q Developer", "amazon-q[bot]", "Amazon Q"),
    ],
)
def test_new_agents_from_trailer_and_login(pr_data, trailer, login, expected):
    pr_data.commits = [_trailer(trailer)]
    pr_data.pr["user"] = {"login": "octocat"}
    assert _kinds(pr_data)[expected] == "agent"
    assert build_stats(pr_data).has_agents

    pr_data.commits = [{"author": {"login": login}, "commit": {"message": "x"}}]
    assert _kinds(pr_data)[expected] == "agent"  # show_bots False: agents stay
    assert build_stats(pr_data).has_agents


def test_agent_as_login_and_trailer_is_one_entry(pr_data):
    pr_data.pr["user"] = {"login": "octocat"}
    pr_data.commits = [
        {"author": {"login": "factory-droid[bot]"}, "commit": {"message": "x"}},
        _trailer("Factory Droid"),
    ]
    crew = [m for m in find_crew(pr_data) if m.name == "Factory"]
    assert len(crew) == 1 and crew[0].kind == "agent"


def test_lone_q_is_not_an_agent(pr_data):
    pr_data.pr["user"] = {"login": "q-tester"}
    pr_data.commits = [_trailer("Q Smith"), _trailer("Factory Worker")]
    crew = _kinds(pr_data)
    assert crew["q-tester"] == "human"
    assert crew["Q Smith"] == "human"
    assert crew["Factory Worker"] == "human"
    assert not build_stats(pr_data).has_agents


def test_breakdown_typical_pr():
    b = stats.score_breakdown(99, 2, 3, 30)
    assert [(x.label, x.points) for x in b.lines] == [
        ("Size", 40),
        ("Reviewers", 10),
        ("Commits", 3),
        ("Speed", 15),
    ]
    assert b.lines[0].value == "99 lines changed"
    assert b.total == 68


@pytest.mark.parametrize(
    ("minutes", "points"), [(None, 0), (0, 15), (60, 15), (61, 10), (1440, 10), (1441, 0)]
)
def test_breakdown_speed_tiers(minutes, points):
    speed = stats.score_breakdown(100, 0, 0, minutes).lines[3]
    assert speed.points == points
    if minutes is None:
        assert "not merged" in speed.value


def test_breakdown_caps():
    b = stats.score_breakdown(100, 9, 50, None)
    assert b.lines[1].points == 20
    assert b.lines[2].points == 10


def test_breakdown_clamp_rows():
    low = stats.score_breakdown(0, 0, 0, None)
    assert low.total == 1
    assert low.lines[0].points == 0
    assert (low.lines[-1].label, low.lines[-1].points) == ("Adjustment", 1)
    high = stats.score_breakdown(10**9, 50, 500, 1)
    assert high.total == 99
    assert high.lines[-1].label == "Adjustment" and high.lines[-1].points < 0
    assert all(x.label != "Adjustment" for x in stats.score_breakdown(99, 2, 3, 30).lines)


@pytest.mark.parametrize("lines", [0, 1, 9, 10, 99, 1000, 10**5, 10**9])
@pytest.mark.parametrize("reviewers", [0, 2, 4, 50])
@pytest.mark.parametrize("commits", [0, 3, 500])
@pytest.mark.parametrize("minutes", [None, 5, 600, 5000])
def test_breakdown_sums_to_total(lines, reviewers, commits, minutes):
    b = stats.score_breakdown(lines, reviewers, commits, minutes)
    assert sum(x.points for x in b.lines) == b.total
    assert b.total == ship_score(lines, reviewers, commits, minutes)
    assert 1 <= b.total <= 99


def test_card_stats_carries_breakdown(pr_data):
    s = build_stats(pr_data)
    assert s.score_breakdown.total == s.ship_score
