"""Slack incoming-webhook formatting and delivery."""

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

MAX_LOCATIONS = 4


def _fmt_locations(locations: list[str]) -> str:
    if not locations:
        return "N/A"
    if len(locations) <= MAX_LOCATIONS:
        return ", ".join(locations)
    return ", ".join(locations[:MAX_LOCATIONS]) + f" +{len(locations) - MAX_LOCATIONS} more"


def build_message(listing: dict, label: str) -> dict:
    company = listing.get("company_name", "Unknown")
    title = listing.get("title", "Unknown role")
    url = listing.get("url", "")
    fields = [
        f"*Locations:* {_fmt_locations(listing.get('locations') or [])}",
        f"*Category:* {listing.get('category') or 'N/A'}",
    ]
    if listing.get("terms") and listing["terms"] != ["N/A"]:
        fields.append(f"*Terms:* {', '.join(listing['terms'])}")
    if listing.get("sponsorship") and listing["sponsorship"] != "Other":
        fields.append(f"*Sponsorship:* {listing['sponsorship']}")
    if listing.get("date_posted"):
        posted = datetime.fromtimestamp(listing["date_posted"], tz=timezone.utc)
        fields.append(f"*Posted:* <!date^{listing['date_posted']}^{{date_short_pretty}} {{time}}|{posted:%Y-%m-%d %H:%M} UTC>")

    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*{label}* :briefcase:\n*{company}* — <{url}|{title}>"},
        },
        {"type": "section", "fields": [{"type": "mrkdwn", "text": f} for f in fields]},
    ]
    if url:
        blocks.append(
            {
                "type": "actions",
                "elements": [{"type": "button", "text": {"type": "plain_text", "text": "Apply"}, "url": url}],
            }
        )
    return {"text": f"{label}: {company} — {title}", "blocks": blocks}


def post(webhook_url: str, payload: dict, retries: int = 5) -> None:
    """POST to a Slack webhook, honoring 429 Retry-After. Raises on persistent failure."""
    body = json.dumps(payload).encode()
    for attempt in range(retries):
        req = urllib.request.Request(
            webhook_url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=30):
                return
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                time.sleep(int(e.headers.get("Retry-After", 2 ** attempt)))
                continue
            raise
        except urllib.error.URLError:
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Slack post failed after {retries} attempts")
