#!/usr/bin/env python3
"""Corre esto UNA VEZ en tu propia computadora (NO en GitHub Actions) para
obtener un refresh token de OAuth2 que autoriza a este proyecto a escribir
en tu Google Drive personal en tu nombre.

Por qué hace falta: las cuentas de servicio de Google NO tienen cuota de
almacenamiento propia en "Mi unidad", así que no pueden crear archivos ahí
(Google devuelve el error "storageQuotaExceeded" al intentarlo), sin
importar cómo compartas la carpeta. La alternativa es autorizar con tu
propia cuenta de Google mediante OAuth2 una sola vez; el refresh token
resultante se guarda como secret de GitHub y el workflow lo reutiliza en
cada corrida sin que tengas que volver a autorizar.

Requisitos previos:
1. En Google Cloud Console (el mismo proyecto donde ya habilitaste la
   Drive API), ve a "APIs y servicios" -> "Credenciales" ->
   "Crear credenciales" -> "ID de cliente de OAuth". Si te pide configurar
   la "pantalla de consentimiento" primero, elige tipo "Externo" (o
   "Interno" si tienes Workspace) y agrégate a ti mismo como usuario de
   prueba.
2. Tipo de aplicación: "App de escritorio". Copia el "ID de cliente" y el
   "Secreto del cliente" que te da.
3. Instala la dependencia extra que solo hace falta para este script
   (no es necesaria en el workflow de GitHub Actions):
       pip install -r dukascopy/requirements-oauth-setup.txt

Uso:
    python dukascopy/get_drive_refresh_token.py \\
        --client-id TU_CLIENT_ID.apps.googleusercontent.com \\
        --client-secret TU_CLIENT_SECRET

Se abre una ventana del navegador pidiéndote iniciar sesión con la cuenta
de Google dueña de la carpeta de Drive destino, y autorizar el acceso.
Al terminar, imprime tres valores: guárdalos como secrets de GitHub
(Settings -> Secrets and variables -> Actions):
    GDRIVE_OAUTH_CLIENT_ID
    GDRIVE_OAUTH_CLIENT_SECRET
    GDRIVE_OAUTH_REFRESH_TOKEN
"""
import argparse

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--client-id", required=True)
    ap.add_argument("--client-secret", required=True)
    args = ap.parse_args()

    client_config = {
        "installed": {
            "client_id": args.client_id,
            "client_secret": args.client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    creds = flow.run_local_server(port=0)

    if not creds.refresh_token:
        raise SystemExit(
            "Google no devolvió un refresh token (puede pasar si ya habías "
            "autorizado esta app antes). Ve a "
            "https://myaccount.google.com/permissions, revoca el acceso de "
            "esta app, y vuelve a correr este script."
        )

    print("\n¡Listo! Guarda estos tres valores como secrets de GitHub Actions:\n")
    print(f"GDRIVE_OAUTH_CLIENT_ID={args.client_id}")
    print(f"GDRIVE_OAUTH_CLIENT_SECRET={args.client_secret}")
    print(f"GDRIVE_OAUTH_REFRESH_TOKEN={creds.refresh_token}")


if __name__ == "__main__":
    main()
