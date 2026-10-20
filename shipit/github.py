"""Fetch the raw facts about a pull request from the GitHub REST API."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

import httpx

API = "https://api.github.com"
PER_PAGE = 100
MAX_PAGES = 30  # hard bound so a misbehaving server cannot loop forever

_PR_PATH = (
    r"/(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/"
    r"(?P<repo>[A-Za-z0-9._-]{1,100})/pull/(?P<number>\d{1,9})/?(?:[#?].*)?$"
)
PR_URL = re.compile(r"^(?:https?://)?(?:www\.)?github\.com" + _PR_PATH)

_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_HOST = re.compile(rf"{_LABEL}(?:\.{_LABEL})*(?::(?P<port>\d{{1,5}}))?")


class BadPRUrl(ValueError):
    """The input is not a github.com pull request URL."""


def validate_host(host: str) -> str:
    """Return the host lowercased if it is a bare hostname (optional port), else raise."""
    match = _HOST.fullmatch(host) if isinstance(host, str) and len(host) <= 253 else None
    if not match or (match["port"] is not None and not 1 <= int(match["port"]) <= 65535):
        raise BadPRUrl(f"Not a valid hostname: {host!r}")
    return host.lower()


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


def parse_pr_url(url: str, host: str | None = None) -> PRRef:
    if host is None:
        match = PR_URL.match(url.strip())
    else:
        pattern = r"^(?:https?://)?" + re.escape(validate_host(host)) + _PR_PATH
        match = re.match(pattern, url.strip(), re.IGNORECASE)
    if not match:
        raise BadPRUrl(f"Not a GitHub pull request URL: {url!r}")
    return PRRef(match["owner"], match["repo"], int(match["number"]))


def _headers(host: str | None = None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ship-it-card",
    }
    # Never send the github.com token to a custom host.
    token = os.environ.get("GITHUB_TOKEN" if host is None else "GHE_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_pr(ref: PRRef, client: httpx.Client | None = None, host: str | None = None) -> PRData:
    """Fetch the PR, its repo, its commits and its reviews."""
    own_client = client is None
    if client is None:
        if host is None:
            base_url, headers = API, _headers()
        else:
            base_url, headers = f"https://{validate_host(host)}/api/v3", _headers(host)
        client = httpx.Client(base_url=base_url, headers=headers, timeout=20)
    try:
        base = f"/repos/{ref.owner}/{ref.repo}"
        pr = _get(client, f"{base}/pulls/{ref.number}")
        repo = _get(client, base)
        commits = _get_all(client, f"{base}/pulls/{ref.number}/commits")
        reviews = _get_all(client, f"{base}/pulls/{ref.number}/reviews")
        return PRData(ref=ref, pr=pr, repo=repo, commits=commits, reviews=reviews)
    finally:
        if own_client:
            client.close()


def _get_all(client: httpx.Client, path: str) -> list:
    """Fetch every page of a list endpoint, stopping on a short or empty page."""
    items: list = []
    for page in range(1, MAX_PAGES + 1):
        batch = _get(client, path, params={"per_page": PER_PAGE, "page": page})
        items.extend(batch)
        if len(batch) < PER_PAGE:
            break
    return items


def _get(client: httpx.Client, path: str, params: dict | None = None):
    response = client.get(path, params=params)
    response.raise_for_status()
    return response.json()
