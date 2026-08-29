# Descargador de tick data de Dukascopy

Descarga tick data histórica del feed público de Dukascopy y la sube a
Google Drive, corriendo como un workflow de GitHub Actions
(`.github/workflows/dukascopy-tickdata.yml`).

Corre en los runners de GitHub (y no localmente) porque los servidores de
Dukascopy no son alcanzables desde todos los entornos (por ejemplo,
contenedores de CI/agentes en sandbox con salida de red restringida) — los
runners de GitHub Actions sí tienen acceso normal a internet.

## Configuración inicial: acceso a Google Drive

**Importante:** una cuenta de servicio de Google **no puede** crear
archivos en una carpeta normal de "Mi unidad" — Google las bloquea con el
error `storageQuotaExceeded` porque las cuentas de servicio no tienen
cuota de almacenamiento propia (solo funcionan si el destino es una
Unidad compartida de Google Workspace). Si tu Drive es una cuenta Gmail
normal, tienes que usar **OAuth2 con tu propia cuenta** en su lugar
(opción A). Si sí tienes una Unidad compartida de Workspace, la cuenta de
servicio original funciona (opción B).

### Opción A — OAuth2 con tu cuenta de Google (Gmail personal)

1. En Google Cloud Console, crea (o reutiliza) un proyecto y habilita la
   **Google Drive API**.
2. Ve a "APIs y servicios" -> "Credenciales" -> "Crear credenciales" ->
   "ID de cliente de OAuth". Si te pide configurar la "pantalla de
   consentimiento" primero, elige "Externo" y agrégate como usuario de
   prueba. Tipo de aplicación: **App de escritorio**. Copia el ID de
   cliente y el secreto del cliente que te da.
3. En Google Drive, crea (o elige) la carpeta destino (una carpeta normal
   está bien) y copia su ID desde la URL
   (`https://drive.google.com/drive/folders/<ID_DE_CARPETA>`).
4. En tu computadora (no aquí), corre **una sola vez**:
   ```bash
   pip install -r dukascopy/requirements-oauth-setup.txt
   python dukascopy/get_drive_refresh_token.py \
     --client-id TU_CLIENT_ID.apps.googleusercontent.com \
     --client-secret TU_CLIENT_SECRET
   ```
   Esto abre el navegador para que autorices con la cuenta de Google
   dueña de la carpeta, y al final imprime tres valores.
5. En el repo de GitHub, agrega esos tres valores más el ID de la carpeta
   como **secrets de Actions** (Settings -> Secrets and variables ->
   Actions):
   - `GDRIVE_OAUTH_CLIENT_ID`
   - `GDRIVE_OAUTH_CLIENT_SECRET`
   - `GDRIVE_OAUTH_REFRESH_TOKEN`
   - `GDRIVE_FOLDER_ID`: el ID de la carpeta del paso 3.

### Opción B — Cuenta de servicio (solo con Unidad compartida de Workspace)

1. En Google Cloud Console, habilita la **Google Drive API** y crea una
   **cuenta de servicio**; descarga su clave JSON.
2. Crea una **Unidad compartida** (no una carpeta normal) en Google Drive
   y agrega el email de la cuenta de servicio como miembro con permiso de
   Contenido/Editor. Copia el ID de la carpeta destino dentro de esa
   Unidad compartida.
3. Agrega dos secrets de Actions:
   - `GDRIVE_SA_JSON`: el contenido completo del archivo JSON.
   - `GDRIVE_FOLDER_ID`: el ID de la carpeta dentro de la Unidad compartida.

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

GDRIVE_OAUTH_CLIENT_ID="..." GDRIVE_OAUTH_CLIENT_SECRET="..." GDRIVE_OAUTH_REFRESH_TOKEN="..." \
  python dukascopy/upload_to_drive.py --file data/XAUUSD.csv --folder-id <ID_DE_CARPETA>
```

## Notas sobre la escala de precios

Dukascopy guarda los precios de cada tick como enteros escalados.
`convert_to_csv.py` ya trae divisores para algunos instrumentos comunes
(`XAUUSD`, `XAGUSD`, `EURUSD`, `GBPUSD`, `USDJPY`, `BTCUSD`); para
cualquier otro usa 100000 por defecto. Si los precios decodificados se ven
desfasados por un factor de 10/100/1000 respecto al precio real de
mercado, pasa `--point-divisor` explícitamente para corregirlo.
