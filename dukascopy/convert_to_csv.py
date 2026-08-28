#!/usr/bin/env python3
"""Convierte los archivos .bi5 crudos de Dukascopy (descargados con
download_bi5.py) en un único CSV ordenado cronológicamente, listo para
backtesting.

Cada archivo .bi5 está comprimido en LZMA. Una vez descomprimido, es una
secuencia de registros de 20 bytes en big-endian, uno por tick:
    uint32  milisegundos desde el inicio de la hora de ese archivo
    uint32  precio ask, escalado por el divisor del instrumento
    uint32  precio bid, escalado por el divisor del instrumento
    float32 volumen ask
    float32 volumen bid

El divisor de precio varía según el instrumento (Dukascopy guarda los
precios como enteros escalados). Abajo se incluyen valores por defecto
para los más comunes; si los precios decodificados se ven desfasados por
un factor de 10/100/1000 respecto al precio real de mercado, corrígelo
con --point-divisor.
"""
import argparse
import csv
import datetime as dt
import lzma
import struct
import sys
from pathlib import Path

RECORD = struct.Struct(">IIIff")

# Factores de escala de precio conocidos de Dukascopy. Agrega más si hace falta.
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
    # .../{SYMBOL}/{YYYY}/{MM}/{DD}/{HH}h_ticks.bi5, el mes empieza en 0
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
        print(f"ADVERTENCIA: no se pudo descomprimir {bi5_path}, se omite", file=sys.stderr)
        return
    hour_start = parse_hour_from_path(bi5_path)
    for offset in range(0, len(data) - RECORD.size + 1, RECORD.size):
        ms, ask_raw, bid_raw, ask_vol, bid_vol = RECORD.unpack_from(data, offset)
        yield hour_start + dt.timedelta(milliseconds=ms), ask_raw, bid_raw, ask_vol, bid_vol


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--in-dir", required=True, type=Path,
                     help="Directorio pasado como --out-dir a download_bi5.py")
    ap.add_argument("--out-csv", required=True, type=Path)
    ap.add_argument("--point-divisor", type=int, default=None)
    args = ap.parse_args()

    divisor = args.point_divisor or POINT_DIVISORS.get(args.symbol.upper(), DEFAULT_DIVISOR)
    symbol_dir = args.in_dir / args.symbol
    if not symbol_dir.is_dir():
        raise SystemExit(f"No se encontraron datos descargados en {symbol_dir}")

    files = sorted(symbol_dir.glob("*/*/*/*h_ticks.bi5"))
    print(f"Convirtiendo {len(files)} archivos horarios de {args.symbol} "
          f"(divisor de precio={divisor}) -> {args.out_csv}")

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
                print(f"  progreso: {i}/{len(files)} archivos, {tick_count} ticks escritos")

    print(f"Listo. {tick_count} ticks escritos en {args.out_csv}")


if __name__ == "__main__":
    main()
