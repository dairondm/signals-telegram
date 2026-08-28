#!/usr/bin/env python3
"""Descarga los archivos horarios de ticks crudos (.bi5) del feed histórico
público de Dukascopy.

Dukascopy expone un archivo comprimido en LZMA por instrumento/hora en:
    https://datafeed.dukascopy.com/datafeed/{SYMBOL}/{YYYY}/{MM}/{DD}/{HH}h_ticks.bi5

Nota: el mes en la URL empieza en 0 (enero = 00, diciembre = 11); esa es
la convención propia de Dukascopy, no un error de este script. Las horas
sin operativa (ej. la mayoría de las horas de fin de semana) devuelven
HTTP 200 con cuerpo vacío; se guardan como archivos vacíos "marcadores"
para que las re-ejecuciones no vuelvan a pedirlas.

Los archivos se guardan bajo --out-dir replicando la misma estructura de
rutas de Dukascopy, para que convert_to_csv.py pueda recorrerlos en orden
cronológico.
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
        return "skip"  # ya descargado

    url = remote_url(symbol, hour)
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, timeout=30)
            if resp.status_code == 200:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(resp.content)  # puede estar vacío -> sin ticks esa hora
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
    ap.add_argument("--symbol", required=True, help="Código del instrumento en Dukascopy, ej. XAUUSD")
    ap.add_argument("--start", required=True, help="Fecha de inicio YYYY-MM-DD (inclusive)")
    ap.add_argument("--end", required=True, help="Fecha de fin YYYY-MM-DD (inclusive)")
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--concurrency", type=int, default=16)
    ap.add_argument("--retries", type=int, default=4)
    args = ap.parse_args()

    start = dt.date.fromisoformat(args.start)
    end = dt.date.fromisoformat(args.end)
    if end < start:
        raise SystemExit("--end no puede ser anterior a --start")

    hours = list(hour_range(start, end))
    print(f"Descargando {len(hours)} archivos horarios de {args.symbol} "
          f"desde {start} hasta {end} en {args.out_dir}")

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
                print(f"  progreso: {done}/{len(hours)} "
                      f"(ok={counts['ok']} vacías={counts['empty']} "
                      f"omitidas={counts['skip']} fallidas={counts['failed']})")

    print("Listo.", counts)
    if counts["failed"]:
        print(f"{counts['failed']} horas fallaron tras los reintentos; vuelve a "
              f"correr este script para reanudar (los archivos ya existentes "
              f"se omiten).", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
