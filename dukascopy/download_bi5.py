#!/usr/bin/env python3
"""Descarga los archivos horarios de ticks crudos (.bi5) del feed histórico
público de Dukascopy.

Dukascopy expone un archivo comprimido en LZMA por instrumento/hora en:
    https://datafeed.dukascopy.com/datafeed/{SYMBOL}/{YYYY}/{MM}/{DD}/{HH}h_ticks.bi5

Nota: el mes en la URL empieza en 0 (enero = 00, diciembre = 11); esa es
la convención propia de Dukascopy, no un error de este script. Las horas
sin operativa (ej. la mayoría de las horas de fin de semana) devuelven
HTTP 200 con cuerpo vacío; se guardan como archivos vacíos "marcadores"
para que las re-ejecuciones no vuelvan a pedirlas. Nunca se pide la hora
UTC actual ni horas futuras, porque Dukascopy aún no tiene datos para
ellas y quedarían marcadas como "vacías" para siempre.

Todos los hilos comparten un limitador de velocidad (Throttle): reparte
las peticiones a un ritmo fijo (--rate-limit por segundo, sumando todos
los hilos) y, si el servidor empieza a responder HTTP 429 ("too many
requests"), pausa TODAS las peticiones durante un enfriamiento que crece
con cada 429 nuevo, en vez de seguir insistiendo a la misma velocidad.

Si al final quedan horas sin descargar, no se aborta el resto del
pipeline: se listan en un archivo _failed_hours_<SYMBOL>.txt dentro de
--out-dir para poder reintentarlas después (basta con volver a correr el
script con las mismas fechas; los archivos ya descargados se omiten).

Los archivos se guardan bajo --out-dir replicando la misma estructura de
rutas de Dukascopy, para que convert_to_csv.py pueda recorrerlos en orden
cronológico.
"""
import argparse
import datetime as dt
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

BASE_URL = "https://datafeed.dukascopy.com/datafeed"


class Throttle:
    """Ritmo de peticiones compartido entre hilos, con freno automático
    ante HTTP 429. Todos los hilos llaman a wait() antes de cada intento;
    si el servidor está devolviendo 429, wait() los bloquea a todos hasta
    que pase el enfriamiento vigente."""

    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._lock = threading.Lock()
        self._next_slot = 0.0
        self._cooldown_until = 0.0
        self._recent_429 = 0

    def wait(self):
        while True:
            with self._lock:
                now = time.monotonic()
                target = max(self._next_slot, self._cooldown_until)
                if now >= target:
                    self._next_slot = now + self.min_interval
                    return
                sleep_for = target - now
            time.sleep(sleep_for)

    def report_429(self, retry_after: float | None):
        with self._lock:
            self._recent_429 += 1
            backoff = retry_after if retry_after else min(20 * self._recent_429, 300)
            self._cooldown_until = max(self._cooldown_until, time.monotonic() + backoff)

    def report_success(self):
        with self._lock:
            if self._recent_429 > 0:
                self._recent_429 -= 1


def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None  # también puede venir como fecha HTTP; se ignora y se usa el backoff propio


def hour_range(start: dt.date, end: dt.date):
    current = dt.datetime.combine(start, dt.time.min)
    stop = dt.datetime.combine(end, dt.time.min) + dt.timedelta(days=1)
    # nunca pedir la hora UTC en curso ni horas futuras: Dukascopy todavía
    # no tiene datos para ellas y quedarían cacheadas como "vacías" siempre
    now_hour = dt.datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    stop = min(stop, now_hour)
    while current < stop:
        yield current
        current += dt.timedelta(hours=1)


def local_path(out_dir: Path, symbol: str, hour: dt.datetime) -> Path:
    return (
        out_dir
        / symbol
        / f"{hour.year:04d}"
        / f"{hour.month - 1:02d}"  # Dukascopy months son 0-indexados
        / f"{hour.day:02d}"
        / f"{hour.hour:02d}h_ticks.bi5"
    )


def remote_url(symbol: str, hour: dt.datetime) -> str:
    return (
        f"{BASE_URL}/{symbol}/{hour.year:04d}/{hour.month - 1:02d}/"
        f"{hour.day:02d}/{hour.hour:02d}h_ticks.bi5"
    )


def fetch_one(session: requests.Session, symbol: str, hour: dt.datetime, out_dir: Path,
              retries: int, throttle: Throttle) -> str:
    path = local_path(out_dir, symbol, hour)
    if path.exists():
        return "skip"  # ya descargado

    url = remote_url(symbol, hour)
    last_err = None
    for attempt in range(1, retries + 1):
        throttle.wait()
        try:
            resp = session.get(url, timeout=30)
            if resp.status_code == 200:
                throttle.report_success()
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(resp.content)  # puede estar vacío -> sin ticks esa hora
                return "empty" if len(resp.content) == 0 else "ok"
            if resp.status_code == 404:
                throttle.report_success()
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"")
                return "empty"
            if resp.status_code == 429:
                throttle.report_429(parse_retry_after(resp.headers.get("Retry-After")))
                last_err = "HTTP 429"
                continue  # el freno de throttle.wait() ya se encarga de la espera
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
    ap.add_argument("--concurrency", type=int, default=6,
                     help="Hilos en paralelo (default: 6, antes 16 -> gatillaba bloqueos)")
    ap.add_argument("--rate-limit", type=float, default=4.0,
                     help="Peticiones por segundo como máximo, sumando todos los hilos (default: 4)")
    ap.add_argument("--retries", type=int, default=6)
    args = ap.parse_args()

    start = dt.date.fromisoformat(args.start)
    end = dt.date.fromisoformat(args.end)
    if end < start:
        raise SystemExit("--end no puede ser anterior a --start")

    hours = list(hour_range(start, end))
    print(f"Descargando {len(hours)} archivos horarios de {args.symbol} "
          f"desde {start} hasta {end} en {args.out_dir} "
          f"(concurrencia={args.concurrency}, límite={args.rate_limit}/s)")

    counts = {"ok": 0, "empty": 0, "skip": 0, "failed": 0}
    failed_hours = []
    throttle = Throttle(min_interval=1.0 / args.rate_limit)
    session = requests.Session()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {
            pool.submit(fetch_one, session, args.symbol, hour, args.out_dir, args.retries, throttle): hour
            for hour in hours
        }
        done = 0
        for fut in as_completed(futures):
            hour = futures[fut]
            result = fut.result()
            counts[result] += 1
            if result == "failed":
                failed_hours.append(hour)
            done += 1
            if done % 200 == 0 or done == len(hours):
                print(f"  progreso: {done}/{len(hours)} "
                      f"(ok={counts['ok']} vacías={counts['empty']} "
                      f"omitidas={counts['skip']} fallidas={counts['failed']})")

    print("Listo.", counts)

    if failed_hours:
        manifest = args.out_dir / f"_failed_hours_{args.symbol}.txt"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text("\n".join(h.strftime("%Y-%m-%dT%H") for h in sorted(failed_hours)) + "\n")
        print(f"{len(failed_hours)} horas no se pudieron descargar tras los reintentos. "
              f"Quedaron listadas en {manifest}. Vuelve a correr el workflow con las "
              f"mismas fechas para reintentarlas (lo ya descargado se omite).",
              file=sys.stderr)

    # solo se considera un fallo total si no se obtuvo ningún dato usable;
    # una falla parcial no debe frenar la conversión/subida de lo que sí se logró
    if hours and counts["ok"] + counts["empty"] == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
