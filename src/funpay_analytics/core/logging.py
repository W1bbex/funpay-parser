from __future__ import annotations

import os
import sys
from pathlib import Path
from loguru import logger

# Format for console logging
LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)


def is_running_under_pytest() -> bool:
    """Detects whether code is executing in a pytest runner session."""
    return bool(
        os.environ.get("PYTEST_CURRENT_TEST")
        or "pytest" in sys.modules
        or os.environ.get("PYTEST_VERSION")
    )


def setup_file_logging(log_dir: str | Path | None = None) -> None:
    """Configures file sink for Loguru with rotation and retention.

    Skipped automatically in hermetic test environments.
    """
    if is_running_under_pytest():
        return

    if log_dir is None:
        # Dynamic anchor: src/funpay_analytics/core/logging.py -> 3 levels up to project root
        log_dir = Path(__file__).resolve().parents[3] / "logs"
    else:
        log_dir = Path(log_dir)

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "parser.log"
        logger.add(
            str(log_file),
            rotation="10 MB",
            retention="7 days",
            compression="zip",
            encoding="utf-8",
        )
    except Exception as exc:
        sys.stderr.write(f"Warning: Failed to initialize file logger at {log_dir}: {exc}\n")


# Base configuration: stdout handler only
logger.remove()
logger.add(sys.stdout, format=LOG_FORMAT)

# Initialize file logging only when running outside of tests
if not is_running_under_pytest():
    setup_file_logging()

__all__ = ["logger", "setup_file_logging", "is_running_under_pytest"]
