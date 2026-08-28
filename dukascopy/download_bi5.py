#!/usr/bin/env python3
"""Download raw hourly tick files (.bi5) from Dukascopy's public historical feed.

Dukascopy exposes one LZMA-compressed file per instrument/hour at:
    https://datafeed.dukascopy.com/datafeed/{SYMBOL}/{YYYY}/{MM}/{DD}/{HH}h_ticks.bi5

Note the month in the URL is zero-indexed (January = 00, December = 11) -
that is Dukascopy's own convention, not a bug here. Hours with no trading
(e.g. most weekend hours) come back as HTTP 200 with an empty body; those
are recorded as empty placeholder files so re-runs don't re-request them.

Files are saved under --out-dir mirroring Dukascopy's own path layout, so
convert_to_csv.py can walk the tree back into chronological order.
"""
import argparse
import datetime as dt
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

BASE_URL = "https://datafeed.dukascopy.com/datafeed"


def hour_range(start: dt.date, end: dt.date):
    current = dt.datetime.combine(start, dt.time.min)
    stop = dt.datetime.combine(end, dt.time.min) + dt.timedelta(days=1)
    while current < stop:
        yield current
        current += dt.timedelta(hours=1)


def local_path(out_dir: Path, symbol: str, hour: dt.datetime) -> Path:
    return (
        out_dir
        / symbol
        / f"{hour.year:04d}"
        / f"{hour.month - 1:02d}"  # Dukascopy months are 0-indexed
        / f"{hour.day:02d}"
        / f"{hour.hour:02d}h_ticks.bi5"
    )


def remote_url(symbol: str, hour: dt.datetime) -> str:
    return (
        f"{BASE_URL}/{symbol}/{hour.year:04d}/{hour.month - 1:02d}/"
        f"{hour.day:02d}/{hour.hour:02d}h_ticks.bi5"
    )


def fetch_one(session: requests.Session, symbol: str, hour: dt.datetime, out_dir: Path, retries: int) -> str:
    path = local_path(out_dir, symbol, hour)
    if path.exists():
        return "skip"

    url = remote_url(symbol, hour)
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, timeout=30)
            if resp.status_code == 200:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(resp.content)  # may be empty -> no ticks that hour
                return "empty" if len(resp.content) == 0 else "ok"
            if resp.status_code == 404:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"")
                return "empty"
            last_err = f"HTTP {resp.status_code}"
        except requests.RequestException as exc:
            last_err = str(exc)
        time.sleep(min(2 ** attempt, 30))
    print(f"FAILED {url}: {last_err}", file=sys.stderr)
    return "failed"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbol", required=True, help="Dukascopy instrument code, e.g. XAUUSD")
    ap.add_argument("--start", required=True, help="Start date YYYY-MM-DD (inclusive)")
    ap.add_argument("--end", required=True, help="End date YYYY-MM-DD (inclusive)")
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--concurrency", type=int, default=16)
    ap.add_argument("--retries", type=int, default=4)
    args = ap.parse_args()

    start = dt.date.fromisoformat(args.start)
    end = dt.date.fromisoformat(args.end)
    if end < start:
        raise SystemExit("--end must not be before --start")

    hours = list(hour_range(start, end))
    print(f"Downloading {len(hours)} hourly files for {args.symbol} "
          f"from {start} to {end} into {args.out_dir}")

    counts = {"ok": 0, "empty": 0, "skip": 0, "failed": 0}
    session = requests.Session()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {
            pool.submit(fetch_one, session, args.symbol, hour, args.out_dir, args.retries): hour
            for hour in hours
        }
        done = 0
        for fut in as_completed(futures):
            result = fut.result()
            counts[result] += 1
            done += 1
            if done % 200 == 0 or done == len(hours):
                print(f"  progress: {done}/{len(hours)} "
                      f"(ok={counts['ok']} empty={counts['empty']} "
                      f"skip={counts['skip']} failed={counts['failed']})")

    print("Done.", counts)
    if counts["failed"]:
        print(f"{counts['failed']} hours failed after retries; re-run this "
              f"script to resume (existing files are skipped).", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
