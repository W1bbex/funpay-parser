from __future__ import annotations

import gzip
import hashlib
import os
import re
import secrets
from pathlib import Path
from typing import Any


def get_data_dir() -> Path:
    data_dir_env = os.environ.get("FUNPAY_DATA_DIR")
    if data_dir_env:
        return Path(data_dir_env).resolve()
    # Resolve relative to project root (funpay-parser/data)
    return Path(__file__).resolve().parents[3] / "data"


def _sanitize_path_component(val: Any, default: str = "unknown") -> str:
    """Sanitizes directory names to prevent path traversal attacks."""
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "_", str(val)).strip("_")
    return cleaned if cleaned else default


def _sanitize_ext(val: Any, default: str = "bin") -> str:
    """Sanitizes file extension."""
    cleaned = re.sub(r"[^a-zA-Z0-9]", "", str(val).lstrip(".")).lower()
    return cleaned if cleaned else default


def save_raw_snapshot(
    source_type: str,
    arg2: Any = b"",
    arg3: Any = "json",
    arg4: Any = None,
) -> tuple[str, str]:
    """Saves raw snapshot compressed with gzip and addressed by SHA-256.

    Supports both signatures:
    Signature A: save_raw_snapshot(source_type, external_id, content, extension="json")
    Signature B: save_raw_snapshot(source_type, content, extension="html", _external_id=None)
    """
    is_sig_a = False
    if arg4 is not None and isinstance(arg2, (str, int)):
        is_sig_a = True
    elif isinstance(arg3, (bytes, bytearray)):
        is_sig_a = True
    elif isinstance(arg3, str) and (len(arg3) > 15 or "\n" in arg3 or "{" in arg3 or "<" in arg3):
        is_sig_a = True

    _external_id: str | None
    if is_sig_a:
        _external_id = str(arg2)
        raw_content = arg3
        extension = str(arg4) if arg4 is not None else "json"
    else:
        _external_id = str(arg4) if arg4 is not None else None
        raw_content = arg2
        extension = str(arg3) if isinstance(arg3, str) else "json"

    if isinstance(raw_content, str):
        content_bytes = raw_content.encode("utf-8")
    elif isinstance(raw_content, (bytes, bytearray)):
        content_bytes = bytes(raw_content)
    else:
        content_bytes = b""

    safe_source = _sanitize_path_component(source_type, default="misc")
    safe_ext = _sanitize_ext(extension, default="bin")

    content_sha256 = hashlib.sha256(content_bytes).hexdigest()
    data_dir = get_data_dir()
    raw_dir = data_dir / "raw" / safe_source
    raw_dir.mkdir(parents=True, exist_ok=True)

    file_name = f"{content_sha256}.{safe_ext}.gz"
    file_path = raw_dir / file_name

    if os.environ.get("FUNPAY_DATA_DIR"):
        compressed_path_relative = str(file_path.resolve()).replace("\\", "/")
    else:
        compressed_path_relative = f"data/raw/{safe_source}/{file_name}"

    if not file_path.exists():
        temp_path = file_path.with_name(f"{file_name}.tmp.{secrets.token_hex(4)}")
        try:
            with gzip.open(temp_path, "wb") as f:
                f.write(content_bytes)
            os.replace(temp_path, file_path)
        except Exception:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            raise

    return content_sha256, compressed_path_relative


__all__ = ["get_data_dir", "save_raw_snapshot"]
