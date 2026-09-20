"""Access to the official participant bundle (inbox JSON + attachments).

The bundle ZIP is committed to the repository; on first start it is extracted
next to the backend so the same code works locally and on Render.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Optional


class Inbox:
    def __init__(self, data_dir: Path, zip_path: Optional[Path] = None):
        self.data_dir = Path(data_dir)
        self.zip_path = Path(zip_path) if zip_path else None
        self._emails: Optional[list[dict]] = None
        self._by_id: dict[str, dict] = {}

    # -- setup -------------------------------------------------------------
    def ensure(self) -> None:
        inbox_dir = self.data_dir / "inbox"
        if inbox_dir.exists() and any(inbox_dir.glob("email_*.json")):
            return
        if not self.zip_path or not self.zip_path.exists():
            raise FileNotFoundError(
                f"No extracted data in {self.data_dir} and bundle zip not found at {self.zip_path}"
            )
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(self.zip_path) as zf:
            for member in zf.namelist():
                # guard against path traversal inside the archive
                target = (self.data_dir / member).resolve()
                if not str(target).startswith(str(self.data_dir.resolve())):
                    continue
                if member.endswith("/"):
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(target, "wb") as dst:
                    dst.write(src.read())

    # -- listing -----------------------------------------------------------
    def emails(self) -> list[dict]:
        if self._emails is None:
            inbox_dir = self.data_dir / "inbox"
            records = []
            for p in sorted(inbox_dir.glob("email_*.json")):
                try:
                    rec = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    continue
                rec.setdefault("email_id", p.stem)
                rec.setdefault("attachments", [])
                rec.setdefault("subject", "")
                rec.setdefault("body", "")
                rec.setdefault("from", "")
                records.append(rec)
            records.sort(key=lambda r: r["email_id"])
            self._emails = records
            self._by_id = {r["email_id"]: r for r in records}
        return self._emails

    def get(self, email_id: str) -> Optional[dict]:
        self.emails()
        return self._by_id.get(email_id)

    def __len__(self) -> int:
        return len(self.emails())

    # -- attachments -------------------------------------------------------
    def attachment_path(self, att_path: str) -> Path:
        rel = att_path.lstrip("/")
        if not rel.startswith("attachments/") or ".." in rel:
            raise ValueError(f"Illegal attachment path: {att_path}")
        return self.data_dir / rel

    def read_bytes(self, att_path: str) -> bytes:
        p = self.attachment_path(att_path)
        if not p.exists():
            raise FileNotFoundError(att_path)
        return p.read_bytes()

    def attachment_size(self, att_path: str) -> Optional[int]:
        try:
            p = self.attachment_path(att_path)
            return p.stat().st_size if p.exists() else None
        except ValueError:
            return None

    def sample_submission(self) -> dict:
        p = self.data_dir / "sample_submission.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        return {}
