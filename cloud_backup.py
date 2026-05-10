"""
cloud_backup.py — Google Drive への非同期バックアップ（OAuth ユーザー認証）

Streamlit Secrets に以下が設定されていない場合は何もしない（例外も出さない）:
  - gdrive_folder_id
  - gdrive_client_id
  - gdrive_client_secret
  - gdrive_refresh_token

バックアップ失敗時も Streamlit の動作に影響しない。
"""
from __future__ import annotations

import io
import sys
import mimetypes
import threading
from datetime import datetime
from pathlib import Path


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _build_service():
    """Drive API クライアントを OAuth ユーザー認証で生成。secrets 未設定なら None を返す。"""
    try:
        import streamlit as st
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        required = {"gdrive_folder_id", "gdrive_client_id", "gdrive_client_secret", "gdrive_refresh_token"}
        if not required.issubset(st.secrets.keys()):
            return None

        creds = Credentials(
            token=None,
            refresh_token=str(st.secrets["gdrive_refresh_token"]),
            client_id=str(st.secrets["gdrive_client_id"]),
            client_secret=str(st.secrets["gdrive_client_secret"]),
            token_uri="https://oauth2.googleapis.com/token",
        )
        return build("drive", "v3", credentials=creds, cache_discovery=False)
    except Exception as e:
        print(f"[cloud_backup] {_now()} Drive 初期化失敗: {e}", file=sys.stderr)
        return None


def _create_folder(service, name: str, parent_id: str) -> str:
    meta = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    return service.files().create(body=meta, fields="id").execute()["id"]


def _delete_folder(service, folder_id: str) -> None:
    service.files().delete(fileId=folder_id).execute()


def _upload_file(service, path: Path, parent_id: str) -> None:
    from googleapiclient.http import MediaIoBaseUpload

    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    media = MediaIoBaseUpload(io.BytesIO(path.read_bytes()), mimetype=mime)
    service.files().create(
        body={"name": path.name, "parents": [parent_id]},
        media_body=media,
    ).execute()


def _do_upload(local_dir: Path, parent_folder_id: str) -> None:
    service = _build_service()
    if service is None:
        return

    folder_id = None
    try:
        print(f"[cloud_backup] {_now()} アップロード開始 → {local_dir.name}", file=sys.stderr)
        folder_id = _create_folder(service, local_dir.name, parent_folder_id)
        for f in sorted(local_dir.iterdir()):
            if f.is_file():
                _upload_file(service, f, folder_id)
                print(f"[cloud_backup] {_now()}   ✓ {f.name}", file=sys.stderr)
        print(f"[cloud_backup] {_now()} アップロード完了 → {local_dir.name}", file=sys.stderr)
    except Exception as e:
        print(f"[cloud_backup] {_now()} アップロード失敗: {e}", file=sys.stderr)
        # ロールバック: 中途半端に作成されたフォルダを削除
        if folder_id:
            try:
                _delete_folder(service, folder_id)
                print(f"[cloud_backup] {_now()} ロールバック完了: Drive のフォルダを削除しました", file=sys.stderr)
            except Exception as re:
                print(f"[cloud_backup] {_now()} ロールバック失敗: {re}", file=sys.stderr)


def upload_to_drive_async(local_dir: Path) -> None:
    """local_dir を Google Drive にバックアップする（非同期・失敗しても無視）。

    Streamlit Secrets に以下が設定されていない場合は即時リターン:
      - gdrive_folder_id      : バックアップ先フォルダの Drive ID
      - gdrive_client_id      : OAuth クライアント ID
      - gdrive_client_secret  : OAuth クライアントシークレット
      - gdrive_refresh_token  : OAuth リフレッシュトークン
    """
    try:
        import streamlit as st

        required = {"gdrive_folder_id", "gdrive_client_id", "gdrive_client_secret", "gdrive_refresh_token"}
        if not required.issubset(st.secrets.keys()):
            return
        parent_id = str(st.secrets["gdrive_folder_id"])
    except Exception:
        return

    threading.Thread(
        target=_do_upload,
        args=(local_dir, parent_id),
        daemon=False,
    ).start()
