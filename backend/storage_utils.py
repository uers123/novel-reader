from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

_JSON_LOCKS: dict[str, threading.RLock] = {}
_JSON_LOCKS_GUARD = threading.Lock()


def _path_lock(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _JSON_LOCKS_GUARD:
        lock = _JSON_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _JSON_LOCKS[key] = lock
        return lock


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with _path_lock(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = _path_lock(path)
    with lock:
        tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())

            last_error: OSError | None = None
            for attempt in range(8):
                try:
                    os.replace(tmp, path)
                    return
                except OSError as exc:
                    last_error = exc
                    time.sleep(0.05 * (attempt + 1))

            try:
                path.unlink(missing_ok=True)
                os.replace(tmp, path)
            except OSError as exc:
                raise last_error or exc
        finally:
            tmp.unlink(missing_ok=True)
