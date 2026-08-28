# Descargador de tick data de Dukascopy

Descarga tick data histórica del feed público de Dukascopy y la sube a
Google Drive, corriendo como un workflow de GitHub Actions
(`.github/workflows/dukascopy-tickdata.yml`).

Corre en los runners de GitHub (y no localmente) porque los servidores de
Dukascopy no son alcanzables desde todos los entornos (por ejemplo,
contenedores de CI/agentes en sandbox con salida de red restringida) — los
runners de GitHub Actions sí tienen acceso normal a internet.

## Configuración inicial: acceso a Google Drive

1. En Google Cloud Console, crea (o reutiliza) un proyecto y habilita la
   **Google Drive API**.
2. Crea una **cuenta de servicio (service account)**, y luego crea y
   descarga una clave JSON para esa cuenta.
3. En Google Drive, crea (o elige) una carpeta destino, compártela con el
   email de la cuenta de servicio (algo como
   `nombre@proyecto.iam.gserviceaccount.com`) con permiso de **Editor**, y
   copia el ID de la carpeta desde su URL
   (`https://drive.google.com/drive/folders/<ID_DE_CARPETA>`).
4. En el repo de GitHub, agrega dos **secrets de Actions**
   (Settings -> Secrets and variables -> Actions):
   - `GDRIVE_SA_JSON`: el contenido completo del archivo JSON de la cuenta
     de servicio.
   - `GDRIVE_FOLDER_ID`: el ID de la carpeta destino del paso 3.

## Cómo ejecutarlo

Ve a la pestaña **Actions** del repo -> "Descarga de tick data de Dukascopy" ->
**Run workflow**, y configura:
- `symbol`: código del instrumento en Dukascopy, ej. `XAUUSD`
- `start_date` / `end_date`: formato `YYYY-MM-DD`, `end_date` es opcional
  (si se deja vacío usa la fecha de hoy)
- `upload_raw_bi5`: si además quieres subir los archivos comprimidos
  originales como un zip (útil para volver a convertirlos después sin
  tener que descargarlos de nuevo)

El workflow primero descarga los archivos `.bi5` horarios crudos (rápido,
limitado por red), luego los convierte localmente en un único CSV ordenado
cronológicamente (`timestamp_utc,bid,ask,bid_volume,ask_volume`), y sube
ambos a la carpeta de Drive. También se guarda una copia del CSV como
artifact del workflow, como respaldo por si los secrets de Drive aún no
están configurados.

Los archivos crudos quedan en caché entre ejecuciones (según símbolo y
rango de fechas), así que si una corrida se corta o falla a la mitad,
volver a ejecutarla retoma donde quedó en vez de descargar todo de nuevo.

## Si Dukascopy empieza a devolver "demasiadas peticiones" (HTTP 429)

Dukascopy limita cuántas peticiones tolera por minuto desde una misma IP,
y las IPs de los runners de GitHub Actions suelen estar más vigiladas que
una conexión normal. `download_bi5.py` ya trae protección para esto:

- Reparte las peticiones a un ritmo fijo entre todos los hilos
  (`--rate-limit`, 4 por segundo por defecto — antes se mandaban 16 en
  paralelo sin ningún límite, lo cual terminó bloqueando la descarga).
- Si el servidor empieza a responder 429, frena TODAS las peticiones
  durante un enfriamiento que crece con cada 429 nuevo, en vez de seguir
  insistiendo a la misma velocidad.
- Si aun así quedan horas sin poder descargarse, no aborta el resto del
  proceso: convierte y sube a Drive lo que sí se logró, y deja la lista
  de horas faltantes en `_failed_hours_<SYMBOL>.txt` (dentro de la
  carpeta de datos crudos) — el resumen del workflow en GitHub Actions
  también la muestra. **Si ves ese aviso, simplemente vuelve a correr el
  workflow con las mismas fechas**: los archivos ya descargados se
  omiten y solo se reintentan las horas que faltaron.

## Ejecutarlo localmente en vez de con Actions

```bash
pip install -r dukascopy/requirements.txt

python dukascopy/download_bi5.py --symbol XAUUSD --start 2026-01-01 --end 2026-08-28 --out-dir data/raw

python dukascopy/convert_to_csv.py --symbol XAUUSD --in-dir data/raw --out-csv data/XAUUSD.csv

GDRIVE_SA_JSON="$(cat service-account.json)" python dukascopy/upload_to_drive.py \
  --file data/XAUUSD.csv --folder-id <ID_DE_CARPETA>
```

## Notas sobre la escala de precios

Dukascopy guarda los precios de cada tick como enteros escalados.
`convert_to_csv.py` ya trae divisores para algunos instrumentos comunes
(`XAUUSD`, `XAGUSD`, `EURUSD`, `GBPUSD`, `USDJPY`, `BTCUSD`); para
cualquier otro usa 100000 por defecto. Si los precios decodificados se ven
desfasados por un factor de 10/100/1000 respecto al precio real de
mercado, pasa `--point-divisor` explícitamente para corregirlo.
