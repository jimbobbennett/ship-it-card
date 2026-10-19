"""Fetch the raw facts about a pull request from the GitHub REST API."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

import httpx

API = "https://api.github.com"

PR_URL = re.compile(
    r"^(?:https?://)?(?:www\.)?github\.com/"
    r"(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/"
    r"(?P<repo>[A-Za-z0-9._-]{1,100})/pull/(?P<number>\d{1,9})/?(?:[#?].*)?$"
)


class BadPRUrl(ValueError):
    """The input is not a github.com pull request URL."""


@dataclass(frozen=True)
class PRRef:
    owner: str
    repo: str
    number: int

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.repo}#{self.number}"


@dataclass
class PRData:
    ref: PRRef
    pr: dict
    repo: dict
    commits: list[dict] = field(default_factory=list)
    reviews: list[dict] = field(default_factory=list)


def parse_pr_url(url: str) -> PRRef:
    match = PR_URL.match(url.strip())
    if not match:
        raise BadPRUrl(f"Not a GitHub pull request URL: {url!r}")
    return PRRef(match["owner"], match["repo"], int(match["number"]))


def _headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ship-it-card",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_pr(ref: PRRef, client: httpx.Client | None = None) -> PRData:
    """Fetch the PR, its repo, its commits and its reviews."""
    own_client = client is None
    client = client or httpx.Client(base_url=API, headers=_headers(), timeout=20)
    try:
        base = f"/repos/{ref.owner}/{ref.repo}"
        pr = _get(client, f"{base}/pulls/{ref.number}")
        repo = _get(client, base)
        commits = _get(client, f"{base}/pulls/{ref.number}/commits", params={"per_page": 100})
        reviews = _get(client, f"{base}/pulls/{ref.number}/reviews", params={"per_page": 100})
        return PRData(ref=ref, pr=pr, repo=repo, commits=commits, reviews=reviews)
    finally:
        if own_client:
            client.close()


def _get(client: httpx.Client, path: str, params: dict | None = None):
    response = client.get(path, params=params)
    response.raise_for_status()
    return response.json()
