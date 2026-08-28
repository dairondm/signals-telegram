#!/usr/bin/env python3
"""Convert raw Dukascopy .bi5 tick files (downloaded by download_bi5.py) into
one chronologically sorted CSV suitable for backtesting.

Each .bi5 file is LZMA-compressed. Once decompressed it is a sequence of
20-byte big-endian records, one per tick:
    uint32  milliseconds since the start of that file's hour
    uint32  ask price, scaled by the instrument's point divisor
    uint32  bid price, scaled by the instrument's point divisor
    float32 ask volume
    float32 bid volume

The point divisor differs per instrument (Dukascopy stores prices as
scaled integers). Common defaults are provided below; if the decoded
prices look off by a factor of 10/100/1000 from the real market price,
override with --point-divisor.
"""
import argparse
import csv
import datetime as dt
import lzma
import struct
import sys
from pathlib import Path

RECORD = struct.Struct(">IIIff")

# Known Dukascopy price scaling factors. Extend as needed.
POINT_DIVISORS = {
    "XAUUSD": 1000,
    "XAGUSD": 1000,
    "EURUSD": 100000,
    "GBPUSD": 100000,
    "USDJPY": 1000,
    "BTCUSD": 100,
}
DEFAULT_DIVISOR = 100000


def parse_hour_from_path(path: Path):
    # .../{SYMBOL}/{YYYY}/{MM}/{DD}/{HH}h_ticks.bi5, month is 0-indexed
    hour = int(path.stem.split("h")[0])
    day = int(path.parent.name)
    month0 = int(path.parent.parent.name)
    year = int(path.parent.parent.parent.name)
    return dt.datetime(year, month0 + 1, day, hour)


def iter_ticks(bi5_path: Path):
    raw = bi5_path.read_bytes()
    if not raw:
        return
    try:
        data = lzma.decompress(raw)
    except lzma.LZMAError:
        print(f"WARNING: could not decompress {bi5_path}, skipping", file=sys.stderr)
        return
    hour_start = parse_hour_from_path(bi5_path)
    for offset in range(0, len(data) - RECORD.size + 1, RECORD.size):
        ms, ask_raw, bid_raw, ask_vol, bid_vol = RECORD.unpack_from(data, offset)
        yield hour_start + dt.timedelta(milliseconds=ms), ask_raw, bid_raw, ask_vol, bid_vol


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--in-dir", required=True, type=Path,
                     help="Directory passed as --out-dir to download_bi5.py")
    ap.add_argument("--out-csv", required=True, type=Path)
    ap.add_argument("--point-divisor", type=int, default=None)
    args = ap.parse_args()

    divisor = args.point_divisor or POINT_DIVISORS.get(args.symbol.upper(), DEFAULT_DIVISOR)
    symbol_dir = args.in_dir / args.symbol
    if not symbol_dir.is_dir():
        raise SystemExit(f"No downloaded data found at {symbol_dir}")

    files = sorted(symbol_dir.glob("*/*/*/*h_ticks.bi5"))
    print(f"Converting {len(files)} hourly files for {args.symbol} "
          f"(point divisor={divisor}) -> {args.out_csv}")

    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    tick_count = 0
    with args.out_csv.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["timestamp_utc", "bid", "ask", "bid_volume", "ask_volume"])
        for i, bi5_path in enumerate(files, 1):
            for ts, ask_raw, bid_raw, ask_vol, bid_vol in iter_ticks(bi5_path):
                writer.writerow([
                    ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
                    round(bid_raw / divisor, 6),
                    round(ask_raw / divisor, 6),
                    round(bid_vol, 4),
                    round(ask_vol, 4),
                ])
                tick_count += 1
            if i % 500 == 0 or i == len(files):
                print(f"  progress: {i}/{len(files)} files, {tick_count} ticks written")

    print(f"Done. {tick_count} ticks written to {args.out_csv}")


if __name__ == "__main__":
    main()
