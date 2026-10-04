from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any


class ImageStore:
    def __init__(self, image_path: Path, keep_history: int = 0, history_dir: Path | None = None) -> None:
        self.image_path = image_path
        self.keep_history = keep_history
        self.history_dir = history_dir or image_path.parent / "history"
        self.image_path.parent.mkdir(parents=True, exist_ok=True)
        if self.keep_history > 0:
            self.history_dir.mkdir(parents=True, exist_ok=True)

    def save_jpeg(self, data: bytes) -> tuple[Path, dict[str, Any]]:
        if not data or len(data) < 100:
            raise ValueError("refusing to save empty/tiny image")
        if data[:2] != b"\xff\xd8":
            raise ValueError("refusing to save non-JPEG payload")

        tmp = self.image_path.with_suffix(self.image_path.suffix + ".tmp")
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.image_path)

        if self.keep_history > 0:
            stamp = time.strftime("%Y%m%dT%H%M%S")
            hist = self.history_dir / f"{stamp}.jpg"
            hist.write_bytes(data)
            self._prune_history()

        meta = self.stat_current()
        return self.image_path, meta

    def _prune_history(self) -> None:
        files = sorted(self.history_dir.glob("*.jpg"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[self.keep_history :]:
            old.unlink(missing_ok=True)

    def stat_current(self) -> dict[str, Any]:
        st = self.image_path.stat()
        return {
            "path": str(self.image_path),
            "size_bytes": st.st_size,
            "mtime": st.st_mtime,
            "mtime_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_mtime)),
        }

    def read_jpeg(self) -> bytes | None:
        if not self.image_path.exists():
            return None
        data = self.image_path.read_bytes()
        if len(data) < 100 or data[:2] != b"\xff\xd8":
            return None
        return data
