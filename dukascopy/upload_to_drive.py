#!/usr/bin/env python3
"""Upload a file to a Google Drive folder using a service-account.

Requires a service account JSON key with the Drive API enabled, and the
target folder shared with that service account's email (Editor access).

Credentials are read from the GDRIVE_SA_JSON environment variable (the raw
JSON key content) unless --credentials-file points at a file instead.
"""
import argparse
import os
import sys
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def get_credentials(credentials_file: Path | None):
    if credentials_file:
        return service_account.Credentials.from_service_account_file(str(credentials_file), scopes=SCOPES)
    raw = os.environ.get("GDRIVE_SA_JSON")
    if not raw:
        raise SystemExit("Set GDRIVE_SA_JSON env var or pass --credentials-file")
    import json
    info = json.loads(raw)
    return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", required=True, type=Path)
    ap.add_argument("--folder-id", required=True, help="Destination Google Drive folder ID")
    ap.add_argument("--credentials-file", type=Path, default=None)
    ap.add_argument("--name", default=None, help="Name to use in Drive (defaults to local filename)")
    args = ap.parse_args()

    if not args.file.exists():
        raise SystemExit(f"File not found: {args.file}")

    creds = get_credentials(args.credentials_file)
    service = build("drive", "v3", credentials=creds)

    name = args.name or args.file.name
    size_mb = args.file.stat().st_size / (1024 * 1024)
    print(f"Uploading {args.file} ({size_mb:.1f} MB) as '{name}' to folder {args.folder_id}")

    media = MediaFileUpload(str(args.file), resumable=True, chunksize=50 * 1024 * 1024)
    request = service.files().create(
        body={"name": name, "parents": [args.folder_id]},
        media_body=media,
        fields="id,webViewLink",
    )
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  progress: {int(status.progress() * 100)}%")

    print(f"Uploaded. File ID: {response['id']}")
    print(f"Link: {response.get('webViewLink', 'n/a')}")


if __name__ == "__main__":
    main()
