import gzip
import hashlib
import os
import secrets
from pathlib import Path
from typing import Any


def get_data_dir() -> Path:
    data_dir_env = os.environ.get("FUNPAY_DATA_DIR")
    if data_dir_env:
        return Path(data_dir_env).resolve()
    # Resolve relative to project root (funpay-parser/data)
    return Path(__file__).resolve().parents[3] / "data"


def save_raw_snapshot(
    source_type: str,
    arg2: Any = b"",
    arg3: Any = "json",
    arg4: Any = None,
) -> tuple[str, str]:
    # Disambiguate signatures:
    # Signature A: save_raw_snapshot(source_type, external_id, content_bytes, extension="json")
    # Signature B: save_raw_snapshot(source_type, content_bytes, extension="html", _external_id=None)
    if isinstance(arg2, (str, int)) and isinstance(arg3, (bytes, bytearray)):
        _external_id = str(arg2)
        content_bytes = bytes(arg3)
        extension = str(arg4) if arg4 is not None else "json"
    else:
        if isinstance(arg2, str):
            content_bytes = arg2.encode("utf-8")
        elif isinstance(arg2, (bytes, bytearray)):
            content_bytes = bytes(arg2)
        else:
            content_bytes = b""
        extension = str(arg3) if isinstance(arg3, str) else "json"
        _external_id = arg4

    content_sha256 = hashlib.sha256(content_bytes).hexdigest()
    data_dir = get_data_dir()
    raw_dir = data_dir / "raw" / source_type
    raw_dir.mkdir(parents=True, exist_ok=True)

    ext = extension if isinstance(extension, str) else "json"
    file_name = f"{content_sha256}.{ext}.gz"
    file_path = raw_dir / file_name

    if os.environ.get("FUNPAY_DATA_DIR"):
        compressed_path_relative = str(file_path.resolve()).replace("\\", "/")
    else:
        compressed_path_relative = f"data/raw/{source_type}/{file_name}"

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
