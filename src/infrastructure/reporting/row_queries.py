"""Read-only terminal-row projections; history and lifecycle stay with Reporter."""

from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from src.infrastructure.reporting.classification import (
    _APPLICATION_ERROR_LABEL,
    _FAILED_PUZZLE_SOLVE_REASON,
    _FAILED_PUZZLE_SOLVE_STATUS,
    _NIK_PARSING_FAILED_STATUS,
    is_unregistered_row,
    normalize_error_reason,
)
from src.infrastructure.reporting.models import TransactionRow
from src.privacy import display_nik, sanitize_text


def get_nik_parsing_failure_report(rows: Iterable[TransactionRow]) -> dict[str, Any]:
    """Group parsing skips by their full explanation within this operator run."""
    by_reason: defaultdict[str, list[str]] = defaultdict(list)
    total = 0
    for row in rows:
        if row.status != _NIK_PARSING_FAILED_STATUS:
            continue
        total += 1
        reason = sanitize_text(row.reason) or "Gagal parsing NIK"
        nik = display_nik(row.nik)
        if nik not in by_reason[reason]:
            by_reason[reason].append(nik)
    return {"total": total, "by_reason": dict(by_reason)}


def get_mapping_error_report(rows: Iterable[TransactionRow]) -> dict[str, list[str]]:
    """Group actual failed NIKs by normalized error reason."""
    grouped: defaultdict[str, list[str]] = defaultdict(list)
    for row in rows:
        if row.status != "error" or is_unregistered_row(row):
            continue

        grouped[normalize_error_reason(row.reason)].append(display_nik(row.nik))

    return dict(grouped)


def get_mapping_failed_puzzle_report(
    rows: Iterable[TransactionRow],
) -> dict[str, list[str]]:
    """Group failed puzzle solves by their reporting reason."""
    grouped: defaultdict[str, list[str]] = defaultdict(list)
    for row in rows:
        if row.status != _FAILED_PUZZLE_SOLVE_STATUS:
            continue
        key = row.reason.strip() if row.reason else _FAILED_PUZZLE_SOLVE_REASON
        grouped[key].append(display_nik(row.nik))

    return dict(grouped)


def get_error_niks_by_reason(rows: Iterable[TransactionRow]) -> dict[str, list[str]]:
    """Get failed NIKs grouped by normalized error reason."""
    grouped: defaultdict[str, list[str]] = defaultdict(list)
    for row in rows:
        if row.status != "error" or is_unregistered_row(row):
            continue
        grouped[normalize_error_reason(row.reason)].append(display_nik(row.nik))
    return dict(grouped)


def get_error_niks_by_label(rows: Iterable[TransactionRow]) -> dict[str, list[str]]:
    """Get failed NIKs grouped by error label."""
    grouped: defaultdict[str, list[str]] = defaultdict(list)
    for row in rows:
        if row.status != "error" or is_unregistered_row(row):
            continue
        grouped[row.error_label or _APPLICATION_ERROR_LABEL].append(
            display_nik(row.nik)
        )
    return dict(grouped)


def get_other_status_niks_by_status(
    rows: Iterable[TransactionRow],
) -> dict[str, list[str]]:
    """Get NIKs grouped by any non-standard status."""
    grouped: defaultdict[str, list[str]] = defaultdict(list)
    for row in rows:
        if row.status in {"completed", "error", _FAILED_PUZZLE_SOLVE_STATUS}:
            continue
        if row.status.startswith("skipped_"):
            continue
        grouped[row.status].append(display_nik(row.nik))
    return dict(grouped)
