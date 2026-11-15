from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any

from loguru import logger


def atomic_write_json(filepath: str | Path, data: Any) -> bool:
    """Atomically persists JSON data using an isolated temporary file to avoid partial writes and race conditions."""
    filepath = Path(filepath)
    tmp_path = filepath.with_name(f"{filepath.name}.tmp.{secrets.token_hex(4)}")
    try:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        os.replace(tmp_path, filepath)
        return True
    except Exception as exc:
        logger.error(f"Failed to atomically write JSON to {filepath}: {exc}")
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        return False


def atomic_write_lines(filepath: str | Path, lines: list[str]) -> bool:
    """Atomically persists a list of lines using an isolated temporary file."""
    filepath = Path(filepath)
    tmp_path = filepath.with_name(f"{filepath.name}.tmp.{secrets.token_hex(4)}")
    try:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as f:
            for line in lines:
                f.write(f"{line}\n")
        os.replace(tmp_path, filepath)
        return True
    except Exception as exc:
        logger.error(f"Failed to atomically write lines to {filepath}: {exc}")
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        return False


__all__ = ["atomic_write_json", "atomic_write_lines"]
