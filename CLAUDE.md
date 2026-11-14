# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Rollcall: a dependency-free (Python 3.11+ stdlib only, no build step) attendance web service prototype for a Japanese university course (ソフトウェア工学). UI text and docs are in Japanese; `README.md` is the authoritative spec for behavior (decision tables, API payloads, demo credentials).

## Commands

```sh
python3 server.py                                   # serve on http://localhost:3000 (PORT=3001 to change)
python3 -m unittest discover -s tests -v            # all tests
python3 -m unittest tests.test_attendance -v        # one module
python3 -m unittest tests.test_api.<Class>.<test>   # one test
```

On Windows use `python` instead of `python3`. Config comes from env vars or a `.env` file (see `.env.example`; `.env` is loaded with `setdefault`, so real env vars win).

## Architecture

- `attendance.py` — pure, side-effect-free judgment of the two class periods (出席/遅刻/欠席/早退/公欠) from entry/exit times. It transcribes the course's decision table; boundaries are compared to the second and the end time itself counts as 早退. Change the rules here and in the README tables together.
- `server.py` (single file, ~670 lines) — everything else: SQLite schema/seed (`initialize`, `seed`), the `Handler` (`SimpleHTTPRequestHandler` subclass that serves `public/` and routes `/api/*` in `do_GET/POST/PUT/DELETE`), sessions + CSRF + Origin checks, OTP (HMAC-stored, 5 min, single use), the card-event ingest `event()`, a background `mail_worker` draining the DB mail queue (SMTP only when `DEMO_MODE=0`; demo mode just stores mail in the local mailbox), and an `audit` trail.
- `public/` — vanilla JS SPA (`app.js`, `index.html`, `style.css`), no framework or bundler.
- `data/rollcall.sqlite3` — auto-created, git-ignored.

Key flows that span files: a card reader (or the demo "カードリーダー" screen) posts to `/api/integrations/card-events` → `event()` records entry (and issues/validates the OTP) or exit → `attendance.entry_status/exit_status` computes status → `effective()` lets a teacher's manual override win over auto judgment → `notify_record()` queues mail to the single affected student. Entry time is fixed at the first scan; re-scanning "entry" only reissues the OTP. Events are idempotent on `event_id`.

## Conventions worth knowing

- Student APIs derive the student from the session, never from a client-supplied ID.
- All times are Asia/Tokyo (`JST`); all DB writes go through the `database()` context manager (global `RLock`, commit/rollback per block).
- `DEMO_MODE=0` disables demo screens/APIs, requires `INTEGRATION_TOKEN` (≥32 chars) and refuses to run against the demo DB.
- Tests (`tests/test_api.py`) spin up the HTTP server against a temp DB; they never touch the real `data/` DB.
