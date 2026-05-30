"""
drive_explorer.py
-----------------
Lista solo las carpetas y archivos del PRIMER NIVEL de la carpeta raíz
del Drive de Ratoneando Ingeniería (sin entrar a subcarpetas).

Uso:
    python drive_explorer.py
"""

import os
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

load_dotenv()

API_KEY     = os.environ['GOOGLE_API_KEY']
ROOT_FOLDER = '1WN03K1GkaWITw93C088wgJfm8lx-ttxx'
FOLDER_MIME = 'application/vnd.google-apps.folder'


def main():
    service = build('drive', 'v3', developerKey=API_KEY, cache_discovery=False)

    try:
        root = service.files().get(fileId=ROOT_FOLDER, fields='name').execute()
        print(f'[DIR] {root["name"]}/')
    except HttpError as e:
        print(f'Error accediendo a la carpeta raíz: {e}', file=sys.stderr)
        sys.exit(1)

    items = []
    page_token = None
    while True:
        resp = service.files().list(
            q=f"'{ROOT_FOLDER}' in parents and trashed = false",
            fields='nextPageToken, files(id, name, mimeType)',
            orderBy='folder,name',
            pageSize=1000,
            pageToken=page_token,
        ).execute()
        items.extend(resp.get('files', []))
        page_token = resp.get('nextPageToken')
        if not page_token:
            break

    for i, item in enumerate(items):
        is_last = i == len(items) - 1
        connector = '+-- ' if is_last else '|-- '
        tipo = 'DIR ' if item['mimeType'] == FOLDER_MIME else 'FILE'
        suffix = '/' if item['mimeType'] == FOLDER_MIME else ''
        print(f"{connector}[{tipo}] {item['name']}{suffix}  [{item['id']}]")

    print(f'\n{len(items)} items en el primer nivel.')


if __name__ == '__main__':
    main()
