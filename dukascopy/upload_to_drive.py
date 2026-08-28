#!/usr/bin/env python3
"""Sube un archivo a una carpeta de Google Drive usando una cuenta de
servicio (service account).

Requiere una clave JSON de cuenta de servicio con la Drive API habilitada,
y la carpeta destino compartida con el email de esa cuenta (acceso de
Editor).

Las credenciales se leen de la variable de entorno GDRIVE_SA_JSON (el
contenido JSON crudo de la clave), salvo que --credentials-file apunte a
un archivo en su lugar.
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
        raise SystemExit("Define la variable de entorno GDRIVE_SA_JSON o pasa --credentials-file")
    import json
    info = json.loads(raw)
    return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", required=True, type=Path)
    ap.add_argument("--folder-id", required=True, help="ID de la carpeta destino en Google Drive")
    ap.add_argument("--credentials-file", type=Path, default=None)
    ap.add_argument("--name", default=None, help="Nombre a usar en Drive (por defecto, el nombre local del archivo)")
    args = ap.parse_args()

    if not args.file.exists():
        raise SystemExit(f"Archivo no encontrado: {args.file}")

    creds = get_credentials(args.credentials_file)
    service = build("drive", "v3", credentials=creds)

    name = args.name or args.file.name
    size_mb = args.file.stat().st_size / (1024 * 1024)
    print(f"Subiendo {args.file} ({size_mb:.1f} MB) como '{name}' a la carpeta {args.folder_id}")

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
            print(f"  progreso: {int(status.progress() * 100)}%")

    print(f"Subido. ID del archivo: {response['id']}")
    print(f"Enlace: {response.get('webViewLink', 'n/a')}")


if __name__ == "__main__":
    main()
