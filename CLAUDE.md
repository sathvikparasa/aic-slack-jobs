# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A long-running poller that watches the SimplifyJobs job boards ([Summer2027-Internships](https://github.com/SimplifyJobs/Summer2027-Internships) and [New-Grad-Positions](https://github.com/SimplifyJobs/New-Grad-Positions)) and posts each newly added listing to Slack through an incoming webhook. It uses only the Python standard library (3.10+), so there's nothing to install.

## Commands

```bash
python3 -m unittest discover -s tests -v                                  # all tests
python3 -m unittest tests.test_jobwatch.CheckSourceTest.test_posts_only_new_and_marks_all_seen  # one test
python3 -m jobwatch.main --once --dry-run   # one live poll, log messages instead of posting
python3 -m jobwatch.main                    # run forever
docker compose up -d --build                # alternative self-hosted deployment (reads .env, state in ./data)
gh workflow run jobwatch                    # trigger a production poll now
```

Configuration comes from environment variables (see `.env.example`): `SLACK_WEBHOOK_URL`, the optional per-source overrides `SLACK_WEBHOOK_URL_<KEY>` (where KEY is `Source.key` uppercased), `POLL_INTERVAL_SECONDS`, `MAX_AGE_HOURS`, `STATE_DB`, and `LOG_LEVEL`.

## Deployment

Production runs on GitHub Actions (`.github/workflows/jobwatch.yml`). It runs `--once` every 5 minutes, and GitHub often starts these runs late. The webhook URLs come from repository secrets. The SQLite state is kept in the Actions cache: each run restores the newest `jobwatch-state-*` entry and saves a new one. If the cache is lost, the next run re-seeds and posts nothing for that run, rather than reposting old jobs. Never run a local poller against the same webhook at the same time, because it would post every job twice. GitHub disables scheduled workflows after 60 days with no repo activity.

## Architecture

- **Data source:** the upstream README tables are generated from `.github/scripts/listings.json` on the `dev` branch. We fetch that JSON from raw.githubusercontent.com instead of parsing markdown. Each file is about 13 MB, so requests send `If-None-Match` with the stored ETag and an unchanged file costs only a 304. The raw CDN caches for 5 minutes, so polling faster than that gains little.
- **Identity:** each listing has a stable UUID `id`. Dedupe is keyed on `(source.key, id)` in SQLite (`jobwatch/state.py`). Listings that are edited or reactivated keep their id and are not reposted.
- **Flow (`jobwatch/main.py: check_source`):**
  1. Fetch the JSON.
  2. On the first run for a source (no rows yet), seed every id without posting.
  3. On later runs, post only ids that are unseen, active, visible, and have a `date_posted` within `MAX_AGE_HOURS`. The age limit guards against upstream bulk re-adds.
  4. After the posts, mark every remaining id as seen and save the ETag.
- **Failure semantics:** ids are marked seen one at a time, right after each successful post. If a post fails, the exception escapes before the ETag is saved, so the next cycle re-downloads and retries only the unposted jobs. Keep this ordering when you change the loop.
- **Adding a board:** append a `Source` to `SOURCES` in `jobwatch/sources.py`. The new board seeds itself on its next poll.
- **Slack app:** `manifest.json` defines the "LeJob" app (ID `A0CB12Z6SLD`). `assets/icon.png` is its icon, which must be under Slack's upload size limit (the original 2.5 MB file was rejected, so resize to 1024 px). To change only the icon, upload it directly with a multipart POST to `apps.icon.set` (fields `app_id` and `file`), which avoids the rename issue below, and the Slack CLI reads it through `.slack/hooks.json`. Run `slack manifest validate` to check it and `slack app install` to install it. `slack app install` also appends " (local)" to the app name; remove it afterwards with an `apps.manifest.update` API call. The CLI can't create webhook URLs, because Slack only makes one after someone picks a channel in the browser (app settings → Incoming Webhooks).
- **Slack (`jobwatch/slack.py`):** Block Kit payload for an incoming webhook. Posts are spaced about 1.1 s apart, and a 429 response is retried after its `Retry-After` delay.
