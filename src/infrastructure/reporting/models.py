from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


def now_iso() -> str:
    """Get current timestamp in ISO format."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def parse_iso(iso_str: str) -> datetime:
    """Parse ISO format timestamp to datetime object."""
    try:
        return datetime.fromisoformat(iso_str)
    except TypeError, ValueError:
        # Preserve original behavior: fallback to "now" on any parsing error.
        return datetime.now().astimezone()


@dataclass
class TransactionRow:
    """Data model for a single transaction record."""

    nik: str
    status: str
    operator: str = ""
    run_id: str = ""
    operator_id: str = ""
    started_at: str = ""
    finished_at: str = ""
    url: str = ""
    error: str = ""
    error_label: str = ""
    duration_seconds: float = 0.0
    puzzle_solved: bool | None = None
    puzzle_attempts: int = 0
    puzzle_retry_count: int = 0
    puzzle_retry_process: str = ""
    reason: str = ""
    nama_pengguna: str = ""
    jenis_pengguna: str = ""

    def __post_init__(self) -> None:
        """Keep the legacy ``operator`` field as a safe-ID compatibility alias."""
        if not self.operator_id:
            self.operator_id = self.operator
        if not self.operator:
            self.operator = self.operator_id

    def compute_duration(self) -> None:
        """Calculate duration between started_at and finished_at."""
        if not (self.started_at and self.finished_at):
            return

        try:
            start = parse_iso(self.started_at)
            finish = parse_iso(self.finished_at)
            self.duration_seconds = (finish - start).total_seconds()
        except TypeError, ValueError:
            # Preserve original behavior: default to 0.0 on error.
            self.duration_seconds = 0.0


@dataclass
class RetryEvent:
    """Metadata for a retry attempt without adding a transaction row."""

    operator: str
    nik: str
    process: str
    trigger: str
    attempt_number: int
    retry_number: int
    max_retries: int
    recorded_at: str
    url: str = ""
    reason: str = ""
    error_label: str = ""
    run_id: str = ""
    operator_id: str = ""

    def __post_init__(self) -> None:
        if not self.operator_id:
            self.operator_id = self.operator
        if not self.operator:
            self.operator = self.operator_id


@dataclass(frozen=True)
class WorkflowEvent:
    """Business-state telemetry kept separate from terminal transaction rows."""

    operator: str
    nik: str
    event: str
    recorded_at: str
    stage: str = ""
    url: str = ""
    reason: str = ""
    run_id: str = ""
    operator_id: str = ""

    def __post_init__(self) -> None:
        if not self.operator_id:
            object.__setattr__(self, "operator_id", self.operator)
        if not self.operator:
            object.__setattr__(self, "operator", self.operator_id)
