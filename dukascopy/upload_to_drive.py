#!/usr/bin/env python3
"""Sube un archivo a una carpeta de Google Drive.

Soporta dos formas de autenticarse, en este orden de prioridad:

1. OAuth2 con tu propia cuenta de Google (recomendado para Drive personal
   / Gmail normal). Variables de entorno: GDRIVE_OAUTH_REFRESH_TOKEN,
   GDRIVE_OAUTH_CLIENT_ID, GDRIVE_OAUTH_CLIENT_SECRET. El refresh token se
   obtiene una sola vez corriendo get_drive_refresh_token.py localmente
   (ver README). Esto es necesario porque las cuentas de servicio NO
   tienen cuota de almacenamiento propia en "Mi unidad" y no pueden crear
   archivos ahí (error "storageQuotaExceeded") — solo funcionan si el
   destino es una Unidad compartida de Google Workspace.
2. Cuenta de servicio (service account): GDRIVE_SA_JSON (contenido JSON
   crudo) o --credentials-file. Solo funciona si --folder-id apunta a una
   Unidad compartida (Shared Drive), no a una carpeta normal.
"""
import argparse
import json
import os
import sys
from pathlib import Path

from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def get_credentials(credentials_file: Path | None):
    refresh_token = os.environ.get("GDRIVE_OAUTH_REFRESH_TOKEN")
    if refresh_token:
        client_id = os.environ.get("GDRIVE_OAUTH_CLIENT_ID")
        client_secret = os.environ.get("GDRIVE_OAUTH_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise SystemExit(
                "Con GDRIVE_OAUTH_REFRESH_TOKEN definido también hacen falta "
                "GDRIVE_OAUTH_CLIENT_ID y GDRIVE_OAUTH_CLIENT_SECRET"
            )
        return Credentials(
            None,  # sin access token todavía; se obtiene uno nuevo con el refresh token
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=SCOPES,
        )

    if credentials_file:
        return service_account.Credentials.from_service_account_file(str(credentials_file), scopes=SCOPES)
    raw = os.environ.get("GDRIVE_SA_JSON")
    if raw:
        info = json.loads(raw)
        return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)

    raise SystemExit(
        "Define GDRIVE_OAUTH_REFRESH_TOKEN (+ GDRIVE_OAUTH_CLIENT_ID/SECRET) "
        "para subir con tu cuenta de Google, o GDRIVE_SA_JSON / "
        "--credentials-file para una cuenta de servicio (solo válido con "
        "Unidades compartidas)."
    )


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
