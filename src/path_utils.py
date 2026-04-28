from datetime import datetime
from pathlib import Path


def build_dated_dir(root: Path, timestamp: datetime) -> Path:
    """Build a yyyy/mm/dd directory path under the given root."""
    return (
        root
        / timestamp.strftime("%Y")
        / timestamp.strftime("%m")
        / timestamp.strftime("%d")
    )


def build_timestamped_run_dir(
    root: Path, timestamp: datetime, leaf_name: str | None = None
) -> Path:
    """Build a unique yyyy/mm/dd/hhmmss-style run directory path."""
    dated_dir = build_dated_dir(root, timestamp)
    preferred_leaf = leaf_name or timestamp.strftime("%H%M%S")
    candidate = dated_dir / preferred_leaf
    suffix = 1

    while candidate.exists():
        candidate = dated_dir / f"{preferred_leaf}_{suffix:02d}"
        suffix += 1

    return candidate
