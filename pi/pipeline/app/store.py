from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class SaveResult:
    path: Path
    sha256: str
    changed: bool
    captured_at: float


class OriginalStore:
    def __init__(self, original_dir: Path, keep_history: int = 0) -> None:
        self.original_dir = original_dir
        self.keep_history = keep_history
        self.latest_path = original_dir / "latest.jpg"
        self.meta_path = original_dir / "latest.meta.json"
        self.history_dir = original_dir / "history"
        self.original_dir.mkdir(parents=True, exist_ok=True)
        if keep_history > 0:
            self.history_dir.mkdir(parents=True, exist_ok=True)

    def read_meta(self) -> dict[str, Any]:
        if not self.meta_path.exists():
            return {}
        try:
            return json.loads(self.meta_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    def current_sha(self) -> str | None:
        return self.read_meta().get("sha256")

    def save_if_changed(
        self,
        data: bytes,
        sha256: str | None = None,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
        maintenance: bool = False,
    ) -> SaveResult:
        digest = sha256 or hashlib.sha256(data).hexdigest()
        previous = self.current_sha()
        captured_at = time.time()
        if previous == digest and self.latest_path.exists():
            meta = self.read_meta()
            # Refresh validator headers without rewriting the JPEG
            if etag or last_modified or maintenance != bool(meta.get("maintenance")):
                meta["etag"] = etag or meta.get("etag")
                meta["last_modified"] = last_modified or meta.get("last_modified")
                meta["maintenance"] = bool(maintenance)
                self.meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            return SaveResult(
                path=self.latest_path,
                sha256=digest,
                changed=False,
                captured_at=float(meta.get("captured_at", self.latest_path.stat().st_mtime)),
            )

        tmp = self.latest_path.with_suffix(".jpg.tmp")
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.latest_path)

        meta = {
            "sha256": digest,
            "size_bytes": len(data),
            "captured_at": captured_at,
            "captured_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(captured_at)),
            "etag": etag,
            "last_modified": last_modified,
            "maintenance": bool(maintenance),
        }
        self.meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

        if self.keep_history > 0:
            stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime(captured_at))
            hist = self.history_dir / f"{stamp}.jpg"
            hist.write_bytes(data)
            files = sorted(self.history_dir.glob("*.jpg"), key=lambda p: p.stat().st_mtime, reverse=True)
            for old in files[self.keep_history :]:
                old.unlink(missing_ok=True)

        return SaveResult(path=self.latest_path, sha256=digest, changed=True, captured_at=captured_at)
