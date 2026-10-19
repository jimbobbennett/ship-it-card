import pytest

from shipit.github import PRData, PRRef


@pytest.fixture
def pr_data() -> PRData:
    return PRData(
        ref=PRRef("octo", "widgets", 42),
        pr={
            "title": "feat(api): add sparkle mode",
            "user": {"login": "octocat"},
            "additions": 320,
            "deletions": 40,
            "changed_files": 7,
            "commits": 3,
            "created_at": "2026-10-01T10:00:00Z",
            "merged_at": "2026-10-01T12:30:00Z",
            "labels": [{"name": "enhancement"}],
        },
        repo={"full_name": "octo/widgets", "language": "Python", "description": "Widgets."},
        commits=[
            {"author": {"login": "octocat"}, "commit": {"message": "Add sparkle mode"}},
            {
                "author": {"login": "octocat"},
                "commit": {
                    "message": "Tests\n\nCo-Authored-By: Claude Sonnet <noreply@anthropic.com>\n"
                    "Co-authored-by: Ada Lovelace <ada@example.com>"
                },
            },
            {"author": {"login": "dependabot[bot]"}, "commit": {"message": "Bump"}},
        ],
        reviews=[
            {"user": {"login": "reviewer1"}, "state": "APPROVED"},
            {"user": {"login": "reviewer1"}, "state": "COMMENTED"},
            {"user": {"login": "octocat"}, "state": "COMMENTED"},
        ],
    )
