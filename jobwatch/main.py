"""Poll SimplifyJobs listings and post newly added jobs to Slack.

Usage: python -m jobwatch.main [--once] [--dry-run]
"""

import argparse
import logging
import os
import time

from . import slack
from .sources import SOURCES, Source, fetch_listings, is_postable
from .state import State

log = logging.getLogger("jobwatch")

# Ignore "new" IDs whose date_posted is older than this; guards against the
# upstream repo bulk-restoring or re-adding old listings.
MAX_AGE_SECONDS = int(os.environ.get("MAX_AGE_HOURS", "72")) * 3600
SLACK_POST_INTERVAL = 1.1  # Slack webhooks allow ~1 msg/sec


def webhooks_for(source: Source) -> list[str]:
    """Webhook URLs for a source. Each env var may hold a comma-separated list (one per channel)."""
    raw = os.environ.get(f"SLACK_WEBHOOK_URL_{source.key.upper()}") or os.environ.get("SLACK_WEBHOOK_URL") or ""
    return [u.strip() for u in raw.split(",") if u.strip()]


def deliver(webhooks: list[str], msg: dict, dry_run: bool) -> None:
    """Post to every webhook. A failing channel is logged and skipped so it can't block the
    others; only when every channel fails do we raise, leaving the job unseen for retry."""
    if dry_run or not webhooks:
        log.info("[dry-run] %s", msg["text"])
        return
    failures = 0
    for url in webhooks:
        try:
            slack.post(url, msg)
        except Exception:
            failures += 1
            log.exception("Slack post failed for webhook ...%s", url[-6:])
    if failures == len(webhooks):
        raise RuntimeError("all Slack webhooks failed")
    time.sleep(SLACK_POST_INTERVAL)


def find_new(listings: list[dict], seen: set[str], now: float) -> list[dict]:
    new = [
        l for l in listings
        if l.get("id") not in seen
        and is_postable(l)
        and now - (l.get("date_posted") or now) <= MAX_AGE_SECONDS
    ]
    return sorted(new, key=lambda l: l.get("date_posted") or 0)


def check_source(source: Source, state: State, dry_run: bool) -> None:
    listings, etag = fetch_listings(source, state.get_etag(source.key))
    if listings is None:
        log.debug("%s: unchanged", source.key)
        return

    all_ids = [l["id"] for l in listings if l.get("id")]
    if not state.is_seeded(source.key):
        # First run for this source: record everything, post nothing.
        state.mark_seen(source.key, all_ids)
        state.set_etag(source.key, etag)
        log.info("%s: seeded %d existing listings", source.key, len(all_ids))
        return

    seen = state.seen_ids(source.key)
    new = find_new(listings, seen, time.time())
    webhooks = webhooks_for(source)
    log.info("%s: %d new listings", source.key, len(new))

    for listing in new:
        deliver(webhooks, slack.build_message(listing, source.label), dry_run)
        # Mark per-post so a crash mid-batch doesn't re-post earlier jobs.
        state.mark_seen(source.key, [listing["id"]])

    # Everything else (inactive, too old) is marked seen without posting.
    state.mark_seen(source.key, set(all_ids) - seen)
    state.set_etag(source.key, etag)


def replay(source: Source, count: int, dry_run: bool) -> None:
    """Re-post the newest `count` postable listings. Ignores and doesn't touch state."""
    listings, _ = fetch_listings(source, None)
    newest = sorted((l for l in listings if is_postable(l)), key=lambda l: l.get("date_posted") or 0)[-count:]
    webhooks = webhooks_for(source)
    for listing in newest:
        deliver(webhooks, slack.build_message(listing, source.label), dry_run)
    log.info("%s: replayed %d listings", source.key, len(newest))


def run(once: bool, dry_run: bool) -> None:
    state = State(os.environ.get("STATE_DB", "jobwatch.db"))
    interval = int(os.environ.get("POLL_INTERVAL_SECONDS", "120"))
    for source in SOURCES:
        if not dry_run and not webhooks_for(source):
            log.warning("%s: no Slack webhook configured; messages will only be logged", source.key)

    while True:
        for source in SOURCES:
            try:
                check_source(source, state, dry_run)
            except Exception:
                log.exception("%s: check failed", source.key)
        if once:
            return
        time.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="run a single poll cycle and exit")
    parser.add_argument("--dry-run", action="store_true", help="log messages instead of posting to Slack")
    parser.add_argument("--replay", type=int, metavar="N", help="re-post the N newest listings per source and exit")
    args = parser.parse_args()
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.replay:
        for source in SOURCES:
            replay(source, args.replay, args.dry_run)
        return
    run(args.once, args.dry_run)


if __name__ == "__main__":
    main()
