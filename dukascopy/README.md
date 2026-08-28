# Dukascopy tick data downloader

Downloads historical tick data from Dukascopy's public feed and uploads it
to Google Drive, running as a GitHub Actions workflow (`.github/workflows/dukascopy-tickdata.yml`).

It runs on GitHub's own runners rather than locally because Dukascopy's
servers are not reachable from every environment (e.g. sandboxed CI/agent
containers with restricted egress) — GitHub Actions runners have normal
outbound internet access.

## One-time setup: Google Drive access

1. In Google Cloud Console, create (or reuse) a project and enable the
   **Google Drive API**.
2. Create a **service account**, then create a JSON key for it and download it.
3. In Google Drive, create (or pick) a destination folder, share it with the
   service account's email (looks like `name@project.iam.gserviceaccount.com`)
   as **Editor**, and copy the folder ID from its URL
   (`https://drive.google.com/drive/folders/<FOLDER_ID>`).
4. In the GitHub repo, add two **Actions secrets**
   (Settings -> Secrets and variables -> Actions):
   - `GDRIVE_SA_JSON`: the full contents of the service account JSON key file.
   - `GDRIVE_FOLDER_ID`: the destination folder ID from step 3.

## Running it

Go to the repo's **Actions** tab -> "Dukascopy tick data download" ->
**Run workflow**, and set:
- `symbol`: Dukascopy instrument code, e.g. `XAUUSD`
- `start_date` / `end_date`: `YYYY-MM-DD`, end optional (defaults to today)
- `upload_raw_bi5`: also upload the raw compressed files as a zip
  (useful for re-converting later without re-downloading)

The workflow downloads the raw hourly `.bi5` files first (fast, network-bound),
then converts them locally into a single sorted CSV
(`timestamp_utc,bid,ask,bid_volume,ask_volume`), and uploads both to the
Drive folder. A copy of the CSV is also attached as a workflow artifact as a
fallback in case the Drive secrets aren't set up yet.

Raw files are cached between runs (keyed by symbol + date range), so if a
run times out or fails partway through, re-running it resumes instead of
re-downloading everything.

## Running locally instead

```bash
pip install -r dukascopy/requirements.txt

python dukascopy/download_bi5.py --symbol XAUUSD --start 2026-01-01 --end 2026-08-28 --out-dir data/raw

python dukascopy/convert_to_csv.py --symbol XAUUSD --in-dir data/raw --out-csv data/XAUUSD.csv

GDRIVE_SA_JSON="$(cat service-account.json)" python dukascopy/upload_to_drive.py \
  --file data/XAUUSD.csv --folder-id <FOLDER_ID>
```

## Notes on price scaling

Dukascopy stores tick prices as scaled integers. `convert_to_csv.py` ships
with divisors for a few common instruments (`XAUUSD`, `XAGUSD`, `EURUSD`,
`GBPUSD`, `USDJPY`, `BTCUSD`); for anything else it defaults to 100000. If
the decoded prices look off by a factor of 10/100/1000 from the real market
price, pass `--point-divisor` explicitly.
