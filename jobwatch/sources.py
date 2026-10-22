"""Job sources and fetching.

The SimplifyJobs README tables are generated from `.github/scripts/listings.json`,
so we read that file directly instead of parsing markdown. Every listing has a
stable UUID `id`, which is what we dedupe on.
"""

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

RAW_BASE = "https://raw.githubusercontent.com"
USER_AGENT = "aic-slack-jobs/1.0"


@dataclass(frozen=True)
class Source:
    key: str  # stable identifier used in the state DB and env var names
    label: str  # shown in Slack messages
    repo: str
    branch: str = "dev"
    path: str = ".github/scripts/listings.json"

    @property
    def url(self) -> str:
        return f"{RAW_BASE}/{self.repo}/{self.branch}/{self.path}"


SOURCES = [
    Source("intern", "Summer 2027 Internship", "SimplifyJobs/Summer2027-Internships"),
    Source("newgrad", "New Grad", "SimplifyJobs/New-Grad-Positions"),
]


def fetch_listings(source: Source, etag: str | None, timeout: float = 60):
    """Return (listings, etag). listings is None when unchanged (HTTP 304)."""
    req = urllib.request.Request(source.url, headers={"User-Agent": USER_AGENT})
    if etag:
        req.add_header("If-None-Match", etag)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
            return data, resp.headers.get("ETag")
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return None, etag
        raise


def is_postable(listing: dict) -> bool:
    return bool(listing.get("active")) and listing.get("is_visible", True)
